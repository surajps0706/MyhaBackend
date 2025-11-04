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
from datetime import datetime
from . import db  # adjust if needed

async def get_next_order_id() -> str:
    """
    Generates order IDs like 04112501, 04112502, ...
    Date (DDMMYY) updates daily, but counter continues globally.
    """
    counters = db["counters"]
    now = datetime.now()
    date_part = now.strftime("%d%m%y")  # e.g., 041125

    # single global counter document
    record = await counters.find_one_and_update(
        {"_id": "global_order_counter"},
        {"$inc": {"sequence_value": 1}},
        upsert=True,
        return_document=True
    )

    next_num = record["sequence_value"]
    return f"{date_part}{next_num:02d}"
