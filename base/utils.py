import datetime
import random
from typing import Dict, Optional
from django.utils import timezone
import requests
from .models import Item, Inventory, InventoryItem, Price, Site
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import logging
from decimal import Decimal
from django.db.models import OuterRef, Subquery, Sum, F, FloatField, ExpressionWrapper
from .models import Price
from django.db import transaction
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/javascript,*/*;q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://steamcommunity.com/market/",
    "X-Requested-With": "XMLHttpRequest",
}

logger = logging.getLogger(__name__)

# Pool simples de UAs e idiomas (troca/adicione se quiser)
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]
_LANG_POOL = ["en-US,en;q=0.9", "pt-BR,pt;q=0.9", "es-ES,es;q=0.9"]

IMG_BASE = "https://steamcommunity-a.akamaihd.net/economy/image/"

def _icon_url_from_desc(desc: dict) -> str | None:
    ico = desc.get("icon_url") or desc.get("icon_url_large")
    return f"{IMG_BASE}{ico}" if ico else None

def _fetch_inventory(steam_id: str, count: int = 1000) -> dict:
    """Busca o inventário paginando se necessário."""
    base = f"https://steamcommunity.com/inventory/{steam_id}/730/2"
    headers = {"User-Agent": "Mozilla/5.0"}

    all_assets = []
    all_descs  = []
    params = {"l": "english", "count": str(count)}
    while True:
        r = requests.get(base, params=params, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        all_assets.extend(data.get("assets") or [])
        all_descs.extend(data.get("descriptions") or [])
        if data.get("more_items") and data.get("last_assetid"):
            params["start_assetid"] = data["last_assetid"]
        else:
            break
    return {"assets": all_assets, "descriptions": all_descs}

@transaction.atomic
def importar_inventario(steam_id: str, inventory_obj: Inventory) -> dict:
    """
    Importa e AGREGA o inventário da Steam para 'inventory_obj'.
    - quantity é a contagem de assets por classid
    - mantém 1 linha de InventoryItem por (inventory,item)
    """
    payload = _fetch_inventory(steam_id, count=1000)
    assets = payload.get("assets") or []
    descs  = payload.get("descriptions") or []

    # 1) Contar quantas vezes cada classid aparece (cada asset vem com amount "1")
    counts = Counter(
        a["classid"]
        for a in assets
        if a.get("appid") == 730 and a.get("contextid") == "2" and a.get("classid")
    )

    # 2) Uma description representativa por classid
    desc_by_classid: Dict[str, dict] = {}
    for d in descs:
        cid = d.get("classid")
        if cid and cid not in desc_by_classid:
            desc_by_classid[cid] = d

    # 3) Indexar InventoryItem existentes (para atualizar/remover)
    existentes = {
        ii.item_id: ii
        for ii in InventoryItem.objects.select_for_update().filter(inventory=inventory_obj)
    }
    vistos = set()

    # 4) Upsert por classid -> Item -> InventoryItem.quantity
    for classid, qty in counts.items():
        d = desc_by_classid.get(classid, {})
        market_hash_name = d.get("market_hash_name") or classid
        type_ = d.get("type")
        icon_url = _icon_url_from_desc(d)
        tradable = bool(d.get("tradable", 0))

        # Item (UNIQUE por classid)
        item, _ = Item.objects.update_or_create(
            classid=classid,
            defaults={
                "market_hash_name": market_hash_name,
                "type": type_,
                "icon_url": icon_url,
            },
        )

        # InventoryItem (um por conta+item), quantity agregada
        ii = existentes.get(item.id)
        if ii:
            fields = []
            if ii.quantity != qty:
                ii.quantity = qty
                fields.append("quantity")
            if ii.tradable != tradable:
                ii.tradable = tradable
                fields.append("tradable")
            if fields:
                ii.save(update_fields=fields)
        else:
            # asset_id é irrelevante para empilháveis; pode deixar vazio ou usar qualquer asset como referência
            InventoryItem.objects.create(
                inventory=inventory_obj,
                item=item,
                asset_id="",
                tradable=tradable,
                quantity=qty,
            )
        vistos.add(item.id)

    # 5) Remover o que saiu do inventário
    removidos = InventoryItem.objects.filter(inventory=inventory_obj).exclude(item_id__in=vistos).delete()[0]

    # 6) Atualizar timestamp da conta
    inventory_obj.updated_at = timezone.now()
    inventory_obj.save(update_fields=["updated_at"])

    return {
        "itens_total": sum(counts.values()),
        "itens_distintos": len(counts),
        "removidos": removidos,
    }


def atualizar_precos_batch(item_names, max_workers=1):
    """
    Processa em série (1 worker), respeitando o delay de cada request.
    Pode aumentar max_workers se quiser um pouco de concorrência.
    """
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(get_steam_price, name): name for name in item_names}
        for future in as_completed(future_to_item):
            item_name = future_to_item[future]
            try:
                results[item_name] = future.result()
            except Exception as e:
                logger.error(f"[ERRO] Batch falhou em {item_name}: {e}")
                results[item_name] = None
    return results


def atualizar_precos_steam(inventory_obj):
    site, _ = Site.objects.get_or_create(
        name="Steam Market",
        defaults={"url": "https://steamcommunity.com/market/"}
    )

    item_names = [inv_item.item.market_hash_name for inv_item in inventory_obj.items.all()]
    resultados = atualizar_precos_batch(item_names, max_workers=10)

    for inv_item in inventory_obj.items.all():
        result = resultados.get(inv_item.item.market_hash_name)

        # Debug pra ver exatamente o que voltou
        print(f"[DEBUG] {inv_item.item.market_hash_name} → {result}")

        if result and result.get("lowest_price"):
            try:
                preco = to_float(result.get("lowest_price"))
                if preco:
                    Price.objects.create(
                        item=inv_item.item,
                        site=site,
                        price=preco,
                        timestamp=timezone.now()
                    )
            except Exception as e:
                print(f"[ERRO] {inv_item.item.market_hash_name} falhou: {e}")
                continue

def to_float(price_str):
    if not price_str:
        return None
    try:
        return float(
            price_str.replace("$", "")
            .replace("USD", "")
            .replace("R$", "")
            .replace("€", "")
            .replace(",", "")
            .strip()
        )
    except Exception:
        return None


def _rand_headers() -> Dict[str, str]:
    # Se você já tem HEADERS globais, herdamos e sobrescrevemos UA/idioma
    base = {}
    try:
        from .utils import HEADERS  # se existir
        if isinstance(HEADERS, dict):
            base.update(HEADERS)
    except Exception:
        pass
    base["User-Agent"] = random.choice(_UA_POOL)
    base["Accept"] = "application/json,text/*;q=0.9,*/*;q=0.8"
    base["Accept-Language"] = random.choice(_LANG_POOL)
    base["Cache-Control"] = "no-cache"
    return base

def get_steam_price(
    market_hash_name: str,
    *,
    currency: int = 1,           # 1 = USD; compatível com chamada antiga get_steam_price(..., currency=1)
    retries: int = 3,
    delay: float = 2.0,          # atraso base entre tentativas (será exponencial + jitter)
) -> Optional[Dict[str, str]]:
    """
    Busca preço de 1 item no Steam Market (de forma 'menos robótica').
    - currency: 1=USD (default), ver docs da Steam para outros códigos
    - retries: número de tentativas
    - delay: atraso base (aplica backoff exponencial com jitter)
    Retorna dict com chaves: steam_lowest, steam_median, steam_volume; ou None.
    """
    url = "https://steamcommunity.com/market/priceoverview/"

    # Jitter inicial antes da 1ª requisição
    time.sleep(random.uniform(0.8, 2.4))

    with requests.Session() as s:
        for attempt in range(retries):
            params = {
                "currency": currency,
                "appid": 730,
                "market_hash_name": market_hash_name,
                "_": str(random.randint(1, 10_000_000)),  # muda a URL a cada tentativa
            }
            headers = _rand_headers()

            try:
                # timeout=(conectar, ler)
                resp = s.get(url, params=params, headers=headers, timeout=(4, 12))

                # Tratamento específico para 429 (rate limit)
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    # espera indicada pelo servidor OU backoff exponencial com jitter
                    if retry_after:
                        try:
                            wait = float(retry_after)
                        except ValueError:
                            wait = delay * (2 ** attempt)
                    else:
                        wait = delay * (2 ** attempt)
                    wait += random.uniform(0.5, 2.0)
                    wait = min(wait, 60)  # cap
                    logger.warning("[RATE] 429 para %s (tentativa %s/%s). Aguardando %.1fs",
                                   market_hash_name, attempt + 1, retries, wait)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if data.get("success"):
                    return {
                        "steam_lowest": data.get("lowest_price"),
                        "steam_median": data.get("median_price"),
                        "steam_volume": data.get("volume"),
                    }
                else:
                    logger.warning("[WARN] Resposta sem sucesso para %s: %s",
                                   market_hash_name, data)
                    # Pequeno jitter antes de desistir/retentar
                    time.sleep(random.uniform(0.3, 1.0))
                    return None

            except requests.exceptions.RequestException as e:
                # Backoff exponencial + jitter
                wait = delay * (2 ** attempt) + random.uniform(0.5, 2.0)
                wait = min(wait, 45)  # cap
                logger.warning("[ERRO] Falha ao buscar %s (tentativa %s/%s): %s | aguardando %.1fs",
                               market_hash_name, attempt + 1, retries, e, wait)
                time.sleep(wait)

    return None

def calcular_valor_total_bruto(conta) -> Decimal:
    latest_price_sq = (
        Price.objects.filter(item=OuterRef("item"))
        .order_by("-timestamp").values("price")[:1]
    )
    qs = conta.items.annotate(preco=Subquery(latest_price_sq))
    total = qs.aggregate(
        total=Sum(ExpressionWrapper(F("preco") * F("quantity"), output_field=FloatField()))
    )["total"] or 0.0
    return Decimal(str(total))

def calcular_valor_total_liquido(conta) -> Decimal:
    total = conta.items.aggregate(
        total=Sum(ExpressionWrapper(F("price_usd") * F("quantity"), output_field=FloatField()))
    )["total"] or 0.0
    return Decimal(str(total))