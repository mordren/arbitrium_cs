import datetime
import random
from django.utils import timezone
import requests
from .models import Item, Inventory, InventoryItem, Price, Site
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import logging

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


def importar_inventario(steam_id, inventory_obj):
    url = f"https://steamcommunity.com/inventory/{steam_id}/730/2?l=english&count=1000"
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    data = resp.json()

    for desc in data.get("descriptions", []):
        classid = desc.get("classid")
        market_hash_name = desc.get("market_hash_name")
        type_ = desc.get("type")
        icon_url = f"https://steamcommunity-a.akamaihd.net/economy/image/{desc.get('icon_url')}"

        # Criar ou atualizar Item
        item, created = Item.objects.get_or_create(
            classid=classid,
            defaults={
                "market_hash_name": market_hash_name,
                "type": type_,
                "icon_url": icon_url,
            }
        )

        if not created:
            # atualizar info se mudou
            item.market_hash_name = market_hash_name
            item.type = type_
            item.icon_url = icon_url
            item.save()

        # Criar relação InventoryItem
        InventoryItem.objects.get_or_create(
            inventory=inventory_obj,
            item=item,
            asset_id=classid,  # pode ser outro campo, ajuste conforme os dados
        )

def get_steam_price(market_hash_name, retries=3, delay=5):
    """
    Busca preço de 1 item no Steam Market.
    - retries: quantas tentativas antes de desistir
    - delay: tempo de espera entre tentativas (segundos)
    """
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"currency": 1, "appid": 730, "market_hash_name": market_hash_name}

    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if data.get("success"):
                return {
                    "steam_lowest": data.get("lowest_price"),
                    "steam_median": data.get("median_price"),
                    "steam_volume": data.get("volume"),
                }
            else:
                logger.warning(f"[WARN] Resposta sem sucesso para {market_hash_name}: {data}")
                return None

        except requests.exceptions.RequestException as e:
            logger.warning(f"[ERRO] Falha ao buscar {market_hash_name}: {e}")
            time.sleep(delay + random.uniform(0, 1))  # espera entre tentativas

    return None


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
