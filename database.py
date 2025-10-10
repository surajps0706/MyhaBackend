from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
import ssl

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")

# Connect with TLS
client = AsyncIOMotorClient(
    MONGODB_URL,
    tls=True,
    tlsAllowInvalidCertificates=False,
    tlsCAFile=None
)

db = client["myha"]

# ==============================
# ORDER ID AUTO-INCREMENT LOGIC
# ==============================
async def get_next_order_id() -> int:
    """
    Fetches the next sequential order ID.
    Starts from 999990632 and increments by 1 for each new order.
    Auto-creates counter document if missing.
    """
    counters = db["counters"]

    # increment (or create)
    result = await counters.find_one_and_update(
        {"_id": "orderid"},
        {"$inc": {"sequence_value": 1}},
        upsert=True,
        return_document=True
    )

    # 🧠 Handle first-time creation (result will be None)
    if not result or "sequence_value" not in result:
        await counters.update_one(
            {"_id": "orderid"},
            {"$set": {"sequence_value": 999990632}},
            upsert=True
        )
        # fetch again (recursive call ensures correct next value)
        return await get_next_order_id()

    return int(result["sequence_value"])
