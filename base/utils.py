import datetime
import random
from typing import Optional, Dict, Any, List, Tuple
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
from collections import Counter, defaultdict, deque
import cloudscraper


log = logging.getLogger(__name__)

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

SCRAPER = cloudscraper.create_scraper(browser={"custom": "firefox"})
HEADERS = {"User-Agent": "Mozilla/5.0"}

def _get(d: Dict[str, Any], path: str, default=None):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur

def _extract_fields(it: Dict[str, Any]):
    classid = _get(it, "asset.names.identifier")
    classid = str(classid) if classid is not None else None

    name = (_get(it, "asset.names.full")
            or _get(it, "marketHashName")
            or _get(it, "name"))

    type_ = (_get(it, "asset.rarity")
             or _get(it, "asset.quality")
             or _get(it, "rarity")
             or _get(it, "quality"))

    icon_url = (_get(it, "asset.images.steam")
                or _get(it, "asset.images.screenshot")
                or _get(it, "iconUrl"))

    price = (_get(it, "pricing.computed")
             or _get(it, "pricing.default")
             or _get(it, "pricing.basePrice"))

    return classid, name, type_, icon_url, price

def _fetch_page_raw(offset: int, limit: int) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Retorna (status_code, items_list). NÃO lança exceção.
    """
    url = f"https://cs.money/1.0/market/sell-orders?limit={limit}&offset={offset}"
    try:
        resp = SCRAPER.get(url, headers=HEADERS, timeout=60)
        code = resp.status_code
        if code == 200:
            data = resp.json()
            items = data.get("items", []) if isinstance(data, dict) else data
            if not isinstance(items, list):
                items = []
            return code, items
        else:
            return code, []
    except Exception as e:
        log.warning(f"[CSMONEY] Exceção no offset={offset}: {e}")
        return -1, []

def atualizar_precos_csmoney_minimos(
    limit: int = 60,
    max_pages: int = 200,
    pause: float = 1.0,
    retries: int = 3,
    create_missing_items: bool = True,
    epsilon: float = 1e-9,
    cooldown_retries: int = 3,     # quantas vezes re-tentar offsets com 400
    cooldown_wait_sec: int = 120,  # espera longa (2 min) antes de re-enfileirar 400
) -> Dict[str, int]:

    site, _ = Site.objects.get_or_create(
        name="CS.MONEY",
        defaults={"url": "https://cs.money/market/"},
    )

    # Agregador de menores preços por classid
    best_by_classid: Dict[str, Tuple[float, str, Any, Any]] = {}

    # Fila de offsets a explorar (0, 60, 120, ...)
    pending = deque([i * limit for i in range(max_pages)])

    # Tentativas curtas e de cooldown por offset
    short_attempts: Dict[int, int] = {}
    cool_attempts: Dict[int, int] = {}
    cool_queue: List[Tuple[float, int]] = []  # (timestamp_para_reinserir, offset)

    itens_lidos = 0
    pages_ok = 0

    def _pop_ready_cooldowns(now_ts: float):
        # Reinsere offsets da cool_queue cujo tempo já venceu
        still = []
        for when, off in cool_queue:
            if when <= now_ts:
                pending.append(off)
            else:
                still.append((when, off))
        cool_queue[:] = still

    while pending:
        now_ts = time.time()
        _pop_ready_cooldowns(now_ts)

        offset = pending.popleft()

        code, items = _fetch_page_raw(offset, limit)

        # Sucesso
        if code == 200:
            pages_ok += 1
            for it in items:
                classid, name, type_, icon_url, price = _extract_fields(it)
                if classid is None or price is None:
                    continue
                try:
                    p = float(price)
                except Exception:
                    continue
                if p <= 0:
                    continue

                atual = best_by_classid.get(classid)
                if (atual is None) or (p < atual[0] - epsilon):
                    best_by_classid[classid] = (p, name, type_, icon_url)
                itens_lidos += 1

            log.warning(f"[CSMONEY] offset={offset}: itens={len(items)} | agregados={len(best_by_classid)}")
            # pausa curta entre páginas boas
            time.sleep(pause + random.uniform(0, 0.4))
            continue

        # 429/5xx: re-tentativa curta com backoff linear
        if code in (429, 500, 502, 503, 504, -1):
            n = short_attempts.get(offset, 0) + 1
            short_attempts[offset] = n
            if n <= retries:
                wait = 1.5 * n
                log.warning(f"[CSMONEY] {code} em offset={offset} (tentativa {n}/{retries}) – retry em {wait:.1f}s")
                time.sleep(wait)
                pending.appendleft(offset)  # tenta de novo cedo
            else:
                log.warning(f"[CSMONEY] DROP offset={offset} após {retries} tentativas curtas")
            continue

        # 400: pode ser fim de dados OU bloqueio; entra em cooldown
        if code == 400:
            c = cool_attempts.get(offset, 0) + 1
            cool_attempts[offset] = c
            if c <= cooldown_retries:
                when = time.time() + cooldown_wait_sec
                cool_queue.append((when, offset))
                log.warning(f"[CSMONEY] 400 em offset={offset} → cooldown {c}/{cooldown_retries} (+{cooldown_wait_sec}s)")
            else:
                log.warning(f"[CSMONEY] DROP offset={offset} após {cooldown_retries} cooldowns")
            # pequena pausa pra não martelar
            time.sleep(0.5)
            continue

        # Outros códigos: desiste desse offset
        log.warning(f"[CSMONEY] Código {code} inesperado em offset={offset} – descartando")
        time.sleep(0.2)

        # Loop continua até fila e cooldowns esvaziarem
        if not pending and cool_queue:
            # Se nada pronto agora, espera até o próximo cooldown vencer
            next_when = min(when for when, _ in cool_queue)
            sleep_sec = max(0, next_when - time.time())
            if sleep_sec > 0:
                time.sleep(sleep_sec + 0.1)

    # Persistência (um registro por item se preço caiu)
    salvos = 0
    criados = 0
    atualizados_meta = 0
    ignorados_maior_ou_igual = 0
    now = timezone.now()

    with transaction.atomic():
        for classid, (pmin, name, type_, icon_url) in best_by_classid.items():
            try:
                item = Item.objects.get(classid=classid)
                changed = False
                if not item.market_hash_name and name:
                    item.market_hash_name = name
                    changed = True
                if not item.type and type_:
                    item.type = str(type_)
                    changed = True
                if not item.icon_url and icon_url:
                    item.icon_url = icon_url
                    changed = True
                if changed:
                    item.save(update_fields=["market_hash_name", "type", "icon_url"])
                    atualizados_meta += 1
            except Item.DoesNotExist:
                if not (create_missing_items and name):
                    continue
                item = Item.objects.create(
                    classid=classid,
                    market_hash_name=name,
                    type=str(type_) if type_ else None,
                    icon_url=icon_url,
                )
                criados += 1

            last = (
                Price.objects
                .filter(item=item, site=site)
                .order_by("-timestamp")
                .only("price")
                .first()
            )
            if last is None or (pmin < float(last.price) - epsilon):
                Price.objects.create(item=item, site=site, price=pmin, timestamp=now)
                salvos += 1
            else:
                ignorados_maior_ou_igual += 1

    log.warning(
        "[CSMONEY] FIM | itens_lidos=%d, distintos=%d, salvos=%d, criados=%d, "
        "atualizados_meta=%d, ignorados(>=último)=%d, pages_ok=%d",
        itens_lidos, len(best_by_classid), salvos, criados, atualizados_meta,
        ignorados_maior_ou_igual, pages_ok
    )

    return {
        "itens_lidos": itens_lidos,
        "distintos": len(best_by_classid),
        "salvos": salvos,
        "criados": criados,
        "atualizados_meta": atualizados_meta,
        "ignorados_maior_ou_igual": ignorados_maior_ou_igual,
        "pages_ok": pages_ok,
    }