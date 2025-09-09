# base/tasks.py
from celery import shared_task
from django.utils import timezone
from .models import Inventory, Site, Price
from .utils import get_steam_price


@shared_task
def atualizar_precos_steam_task(conta_id):
    site, _ = Site.objects.get_or_create(
        name="Steam Market",
        defaults={"url": "https://steamcommunity.com/market/"}
    )

    conta = Inventory.objects.get(id=conta_id)
    for inv_item in conta.items.all():
        result = get_steam_price(inv_item.item.market_hash_name, currency=1)
        if result and result.get("lowest_price"):
            try:
                preco = float(result["lowest_price"].replace("$", "").replace(",", "").strip())
            except ValueError:
                preco = None

            if preco:
                Price.objects.create(
                    item=inv_item.item,
                    site=site,
                    price=preco,
                    timestamp=timezone.now()
                )
                print(f"[OK] {inv_item.item.market_hash_name} → {preco}")

@shared_task
def atualizar_precos_todos():
    for conta in Inventory.objects.all():
        atualizar_precos_steam_task.delay(conta.id)