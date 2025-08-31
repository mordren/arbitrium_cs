from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Item, Site, Price

admin.site.register(Item)
admin.site.register(Site)
admin.site.register(Price)
