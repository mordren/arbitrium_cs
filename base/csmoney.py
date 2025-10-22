import cloudscraper
import json
import time

scraper = cloudscraper.create_scraper(browser={'custom': 'firefox'})
headers = {"User-Agent": "Mozilla/5.0"}

def fetch_all_csmoney(limit=60, max_pages=200):
    all_items = []
    for page in range(max_pages):
        offset = page * limit
        url = f"https://cs.money/1.0/market/sell-orders?limit={limit}&offset={offset}"
        resp = scraper.get(url, headers=headers, timeout=60)

        try:
            data = resp.json()
        except Exception:
            print(f"⚠️ Página {page} não retornou JSON")
            print(resp.text[:200])
            break

        items = data.get("items", [])
        if not items:
            break  # acabou os resultados
        all_items.extend(items)
        print(f"✅ Página {page} → {len(items)} itens")
        time.sleep(1)  # pausa p/ não ser bloqueado

    return all_items

if __name__ == "__main__":
    items = fetch_all_csmoney(limit=60, max_pages=200)
    print(f"Total coletado: {len(items)} itens")

    # salvar localmente
    with open("csmoney_all.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)