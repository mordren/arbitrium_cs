from django.shortcuts import render
from .models import Item, Price
import requests


def dashboard(request):
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {
        "currency": 1,
        "appid": 730,
        "market_hash_name": "Danger Zone Case"
    }

    resp = requests.get(url, params=params).json()
    data = {}
    if resp.get("success"):
        data = {
            "name": "Danger Zone Case",
            "lowest": resp.get("lowest_price"),
            "median": resp.get("median_price"),
            "volume": resp.get("volume"),
        }

    return render(request, "dashboard.html", {"data": data})
