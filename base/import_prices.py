import requests
import cloudscraper

headers = {"User-Agent": "Mozilla/5.0"}

# ===== Steam =====
def get_steam_price(item_name, currency=1):
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"currency": currency, "appid": 730, "market_hash_name": item_name}
    r = requests.get(url, params=params, headers=headers).json()
    if r.get("success"):
        return {
            "steam_lowest": r.get("lowest_price"),
            "steam_median": r.get("median_price"),
            "steam_volume": r.get("volume")
        }
    return None

# ===== CS.MONEY =====
def get_cs_money(limit=60, offset=0):
    url = f"https://cs.money/1.0/market/sell-orders?limit={limit}&offset={offset}"
    scraper = cloudscraper.create_scraper()
    r = scraper.get(url, headers=headers).json()
    return r.get("items", [])

def get_csfloat(item_name, limit=5):
    url = "https://csfloat.com/api/v1/listings"
    params = {
        "market_hash_name": item_name,
        "type": "sell",
        "order": "asc",
        "limit": limit
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        print("CSFloat URL:", resp.url)       # 👈 mostra URL real consultada
        print("Resposta bruta:", resp.text)   # 👈 vê o que voltou
        data = resp.json()
        r = requests.get(url, params=params, headers=headers, timeout=15).json()
        listings = r.get("listings", [])
        return [
            {
                "price_usd": l["price"] / 100,  # preço vem em centavos
                "float": l.get("float_value"),
                "stickers": [s["name"] for s in l.get("asset", {}).get("stickers", [])]
            }
            for l in listings
        ]
    except Exception as e:
        print(f"⚠️ Erro CSFloat: {e}")
        return []


# ==== Teste ====
if __name__ == "__main__":
    item = "AK-47 | Redline (Field-Tested)"

    steam = get_steam_price(item)
    csmoney = get_cs_money(limit=60, offset=0)
    csfloat = get_csfloat(item, limit=5)

    print("Steam:", steam)
    print("CS.MONEY (primeira página):", len(csmoney))
    print("CSFloat (primeiras ofertas):", csfloat)

