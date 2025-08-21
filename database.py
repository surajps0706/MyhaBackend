from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
import ssl

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")

# Explicitly enforce TLS/SSL
client = AsyncIOMotorClient(
    MONGODB_URL,
    tls=True,
    tlsAllowInvalidCertificates=False,
    tlsCAFile=None  # Let system CA be used
)

db = client["myha"]
