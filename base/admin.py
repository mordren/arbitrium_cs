from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Inventory, InventoryItem, Item, Site, Price

admin.site.register(Item)
admin.site.register(Site)
admin.site.register(Inventory)
admin.site.register(InventoryItem)


@admin.register(Price)
class PriceAdmin(admin.ModelAdmin):
    list_display = ("item", "site", "price", "timestamp")  # mostra na lista
    fields = ("item", "site", "price", "timestamp")  # mostra no form
    readonly_fields = ("timestamp",)  # impede edição manual