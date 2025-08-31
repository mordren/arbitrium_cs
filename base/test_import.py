import requests
import json
import csv

steam_id = "76561197994758803"
url = f"https://steamcommunity.com/inventory/{steam_id}/730/2?l=english&count=1000"

resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
data = resp.json()

items = []
for desc in data.get("descriptions", []):
    item = {
        "classid": desc.get("classid"),
        "market_hash_name": desc.get("market_hash_name"),
        "type": desc.get("type"),
        "icon_url": f"https://steamcommunity-a.akamaihd.net/economy/image/{desc.get('icon_url')}"
    }
    items.append(item)

# Salvar em JSON
with open("inventario.json", "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

# Salvar em CSV
with open("inventario.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=items[0].keys())
    writer.writeheader()
    writer.writerows(items)

print(f"Inventário salvo: {len(items)} itens")
