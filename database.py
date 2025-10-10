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

async def get_next_order_id():
    """
    Fetches the next sequential order ID.
    Starts from 999990632 and increments by 1 for each new order.
    """
    counter = await db.counters.find_one_and_update(
        {"_id": "orderid"},
        {"$inc": {"sequence_value": 1}},
        upsert=True,  # create if not exists
        return_document=True
    )

    # If this is the very first order (document just created)
    if "sequence_value" not in counter:
        await db.counters.update_one(
            {"_id": "orderid"},
            {"$set": {"sequence_value": 999990632}}
        )
        return 999990632

    return counter["sequence_value"]
