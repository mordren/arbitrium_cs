from django.db import models

# Create your models here.
from django.db import models

class Item(models.Model):
    classid = models.CharField(max_length=50, unique=True)  # ex: 3186046283
    market_hash_name = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=100, blank=True, null=True)
    icon_url = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.market_hash_name
    

class Site(models.Model):
    name = models.CharField(max_length=100, unique=True)
    url = models.URLField()

    def __str__(self):
        return self.name

class Price(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    site = models.ForeignKey(Site, on_delete=models.CASCADE)
    price = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)


class Inventory(models.Model):
    name = models.CharField(max_length=100)  # Nome da conta (texto livre)
    steam_id = models.CharField(max_length=50)  # ID numérico extraído do link
    updated_at = models.DateTimeField(auto_now_add=True)
    csmoney_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    csmoney_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    csmoney_price_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.steam_id})"
    
    
class InventoryItem(models.Model):
    inventory = models.ForeignKey(Inventory, related_name="items", on_delete=models.CASCADE)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    asset_id = models.CharField(max_length=50)  # ID único dentro da Steam
    tradable = models.BooleanField(default=False)
    price_usd = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    float_value = models.FloatField(null=True, blank=True)  # só se disponível
    wear_name = models.CharField(max_length=50, blank=True, null=True)

    quantity = models.PositiveIntegerField(default=1)
    def __str__(self):
        return f"{self.item.market_hash_name} ({self.asset_id})"
    

class PriceAlvo(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE)
    preco_alvo = models.DecimalField(max_digits=12, decimal_places=2)
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('item', 'inventory')
    
    def __str__(self):
        return f"{self.item.market_hash_name} - ${self.preco_alvo} ({self.inventory.name})"