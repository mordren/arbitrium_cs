import asyncio
from csfloat_api.csfloat_client import Client

async def main():
    async with Client(api_key="YOUR_API_KEY") as client:
        # Fetch up to 50 listings priced between $1.00 and $10.00 (i.e., 100–1000 cents)
        listings = await client.get_all_listings(min_price=100, max_price=1000)
        for listing in listings["listings"]:
            print(f"ID: {listing.id}, Price: {listing.price} cents, Float: {listing.item.float_value}")

        # Create a buy order for an item
        buy_order = await client.create_buy_order(
            market_hash_name="AK-47 | Redline (Field-Tested)",
            max_price=5000,  # 5000 cents = $50.00
            quantity=1
        )
        print(buy_order)

asyncio.run(main())