import asyncio
from datetime import datetime
from bson import ObjectId
from database import db   # your existing MongoDB connection

async def migrate_products():
    products_cursor = db["products"].find({"createdAt": {"$exists": False}})
    count = 0
    async for product in products_cursor:
        product_id = product["_id"]
        # Extract timestamp from ObjectId
        created_at = product_id.generation_time  # UTC datetime
        await db["products"].update_one(
            {"_id": product_id},
            {"$set": {"createdAt": created_at}}
        )
        count += 1
        print(f"✅ Updated product {product_id} with createdAt={created_at}")

    print(f"\nMigration complete. {count} products updated.")

if __name__ == "__main__":
    asyncio.run(migrate_products())
