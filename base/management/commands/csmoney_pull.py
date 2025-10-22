# base/management/commands/csmoney_pull.py
from __future__ import annotations
from django.core.management.base import BaseCommand
from django.utils import timezone
from base.models import Inventory
from base.utils_csmoney import fetch_sell_order_by_id, extract_price

class Command(BaseCommand):
    help = "Consulta preços por csmoney_id no Inventory (read-only); use --update para gravar no Inventory."

    def add_arguments(self, parser):
        parser.add_argument("--conta", type=int, required=True)
        parser.add_argument("--update", action="store_true")
        parser.add_argument("--proxy")

    def handle(self, *args, **opts):
        conta_id = opts["conta"]
        proxy = opts.get("proxy")
        update = opts["update"]

        qs = (Inventory.objects
              .filter(conta_id=conta_id)
              .exclude(csmoney_id__isnull=True)
              .exclude(csmoney_id=0))

        ok = miss = 0
        for inv in qs.iterator():
            order = fetch_sell_order_by_id(inv.csmoney_id, proxy=proxy)
            price = extract_price(order) if order else None
            self.stdout.write(f"[{inv.id}] {getattr(inv, 'item', inv)} -> {price}")
            if update and price is not None:
                fields = []
                if hasattr(inv, "csmoney_price"):
                    inv.csmoney_price = price
                    fields.append("csmoney_price")
                if hasattr(inv, "csmoney_price_at"):
                    inv.csmoney_price_at = timezone.now()
                    fields.append("csmoney_price_at")
                if fields:
                    inv.save(update_fields=fields)
            ok += int(price is not None)
            miss += int(price is None)

        self.stdout.write(self.style.SUCCESS(f"OK={ok} MISS={miss} TOTAL={qs.count()}"))