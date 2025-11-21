from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
import ssl
from datetime import datetime
from pymongo import ReturnDocument

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")

client = AsyncIOMotorClient(
    MONGODB_URL,
    tls=True,
    tlsAllowInvalidCertificates=False,
    tlsCAFile=None
)

db = client["myha"]

# ==============================
# USERS COLLECTION
# ==============================
users_collection = db["users"]

# ==============================
# ORDER ID AUTO-INCREMENT LOGIC
# ==============================
async def get_next_order_id() -> str:
    counters = db["counters"]
    now = datetime.now()
    date_part = now.strftime("%d%m%y")

    record = await counters.find_one_and_update(
        {"_id": "global_order_counter"},
        {"$inc": {"sequence_value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )

    next_num = record["sequence_value"]
    return f"{date_part}{next_num:02d}"
