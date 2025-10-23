from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
import ssl
from datetime import datetime

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
async def get_next_order_id() -> str:
    """
    Generates daily Myha order IDs like MYHA2310251 (MYHA + DDMMYY + counter).
    Counter resets every new day.
    """
    counters = db["counters"]
    now = datetime.now()
    date_part = now.strftime("%d%m%y")  # 231025 for 23 Oct 2025
    prefix = f"MYHA{date_part}"

    # find today’s counter
    record = await counters.find_one({"_id": prefix})

    if record:
        next_num = record.get("sequence_value", 0) + 1
        await counters.update_one({"_id": prefix}, {"$set": {"sequence_value": next_num}})
    else:
        next_num = 1
        await counters.insert_one({"_id": prefix, "sequence_value": next_num})

    return f"{prefix}{next_num}"