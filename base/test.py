import requests

url = "https://steamcommunity.com/market/search/render/"
params = {
    "appid": 730,
    "norender": 1,
    "count": 10,
    "start": 0,
    "category_730_ItemSet[]": "tag_set_weapons_ii"
}

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest"
}

resp = requests.get(url, params=params, headers=headers).json()

for item in resp["results"]:
    print(f"{item['name']} → {item['sell_price_text']}")
