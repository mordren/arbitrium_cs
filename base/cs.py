import requests

url = "https://cs.money/1.0/market/sell-orders"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://cs.money/market/"
}

cookies = {
    "cf_clearance": "AZM05_.e4CymV5Zvi0Cv0NQgBh8kpp8S6ukEupTfoGA-1756664853-1.2.1.1-iVXqBxi_3U.ggghH58JXS647K2Fs.zNVc.QJUR8UOkmkpek1IT5FetIICs.yqtXNNk.sJ3KSZkLYNMcux6io45dP__w8FNwMa6gTfHY0xnJ4LpQDxZxlUEYOoobQlOazQLunPo2f6hepZNs1EQ3dhLYSLqbiVAUshGzOqkA6zwa.FPCI7Iov2FGo__zsXzP0SU2H9sQSREFO23hgN7jLlYR5n7v4AyWHdY65YJggeYU",  # seu valor real
    "steamid": "76561198087887154",
    "csgo_ses": "8cdbe889562fa0ef9de983aa28d11f3418f6f33459f2e47125adf35116c0f255"  # seu valor real
}

resp = requests.get(url, headers=headers, cookies=cookies)
print("Status:", resp.status_code)
print("Primeiros 500 chars:", resp.text[:500])