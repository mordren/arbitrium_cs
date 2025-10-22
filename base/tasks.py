# base/tasks.py
from __future__ import annotations   # <-- primeira linha do arquivo

import time
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from base.import_prices import get_steam_price
from celery import shared_task
from django.utils import timezone
from .models import Inventory, Site, Price

STEAM_FEE = Decimal("0.15")
TWOPLACES = Decimal("0.01")

def _parse_price_to_decimal(raw) -> Decimal | None:
    if not raw:
        return None
    s = str(raw).strip()
    # remove símbolos e textos comuns
    for sym in ["US$", "$", "R$", "€", "£", "¥", "USD", "BRL", " "]:
        s = s.replace(sym, "")
    # normaliza separadores
    if "," in s and "." in s:
        s = s.replace(",", "")             # vírgula como milhar
    elif "," in s and "." not in s:
        s = s.replace(",", ".")            # vírgula como decimal
    try:
        val = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    return val.quantize(TWOPLACES)

@shared_task
def atualizar_precos_steam_task(conta_id: int):
    site, _ = Site.objects.get_or_create(
        name="Steam Market",
        defaults={"url": "https://steamcommunity.com/market/"}
    )
    
    conta = Inventory.objects.get(id=conta_id)
    inv_items = conta.items.select_related("item").all()

    # cache por execução (evita consultar a mesma skin várias vezes)
    cache = {}
    updated = 0
    checked = 0

    for inv in inv_items:
        mhn = inv.item.market_hash_name
        checked += 1

        if mhn in cache:
            result = cache[mhn]
        else:
            # sua função já faz backoff/jitter; currency=1 = USD
            result = get_steam_price(mhn, currency=1)
            cache[mhn] = result

        if not result:
            continue

        # suporta tanto o formato novo (steam_*) quanto antigo
        raw = (
            result.get("steam_lowest")
            or result.get("lowest_price")
            or result.get("steam_median")
            or result.get("median_price")
        )
        bruto = _parse_price_to_decimal(raw)
        if not bruto or bruto <= 0:
            continue

        # salva histórico (preço bruto no Price)
        Price.objects.create(
            item=inv.item,
            site=site,
            price=float(bruto),  # seu model é FloatField
            timestamp=timezone.now(),
        )

        # aplica taxa de 15% e salva no InventoryItem
        liquido = (bruto * (Decimal("1.00") - STEAM_FEE)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        inv.price_usd = liquido
        inv.save(update_fields=["price_usd"])

        updated += 1

    print(f"[TASK] conta={conta_id} | itens={checked} | atualizados={updated}")

@shared_task
def atualizar_precos_todos():
    for conta in Inventory.objects.all():
        atualizar_precos_steam_task.delay(conta.id)
