from fastapi import FastAPI, HTTPException, Request, Header, UploadFile, File, Form,APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from models import ProductCreate
from pymongo.errors import OperationFailure
from models import ForgotPasswordRequest, ResetPasswordRequest
import asyncio
from pydantic import BaseModel
import re

import boto3
from botocore.client import Config

from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import timedelta, datetime, timezone, date
from models import UserCreate, UserLogin
from database import users_collection
import random

from models import Product
from database import db, get_next_order_id
from bson import ObjectId

import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
import uuid

from fastapi import UploadFile, File, Form, HTTPException

from io import BytesIO

import razorpay
import os
import smtplib
import io
import pandas as pd
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
import random
from typing import List, Optional, Dict, Any
import cloudinary
import cloudinary.uploader
import httpx   # ⭐ Delhivery API calls
import json    # ⭐ for payload formatting


# =============================
# Load env vars
# =============================
load_dotenv()


# =============================
# JWT + PASSWORD HASHING SETTINGS
# =============================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_SECRET = os.getenv("JWT_SECRET", "myha-user-secret")
JWT_ALGO = "HS256"
JWT_EXPIRY_MIN = 60 * 24 * 14  # 14 days



DEFAULT_SIZES = [
    {"label": "XXS", "available": True},
    {"label": "XS", "available": True},
    {"label": "S", "available": True},
    {"label": "M", "available": True},
    {"label": "L", "available": True},
    {"label": "XL", "available": True},
    {"label": "2XL", "available": True},
    {"label": "3XL", "available": True},
]

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)

def create_jwt_token(data: dict, expires_minutes: int = JWT_EXPIRY_MIN):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGO)


def config_cloudinary(account="old"):
    """Switch between Cloudinary accounts (4 total supported)."""

    if account == "split1":  # 🔹 New Account for first 10 products
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME_SPLIT1"),
            api_key=os.getenv("CLOUDINARY_API_KEY_SPLIT1"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET_SPLIT1"),
            secure=True
        )

    elif account == "split2":  # 🔹 New Account for next 13 products
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME_SPLIT2"),
            api_key=os.getenv("CLOUDINARY_API_KEY_SPLIT2"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET_SPLIT2"),
            secure=True
        )

    elif account == "new":  # 🔹 Your 3rd account — for all *future uploads*
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME_NEW"),
            api_key=os.getenv("CLOUDINARY_API_KEY_NEW"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET_NEW"),
            secure=True
        )

    else:  # 🔹 Old account (23 products, quota full)
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET"),
            secure=True
        )


def upload_image(file, folder="products", account="old"):
    """Upload to the chosen Cloudinary account."""
    config_cloudinary(account)
    result = cloudinary.uploader.upload(file, folder=folder)
    return result["secure_url"]



# router = APIRouter()


ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "myha-secret")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_FROM = os.getenv("EMAIL_FROM", EMAIL_USER)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", EMAIL_USER)  # fallback to main email if not set

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

# ⭐ Delhivery credentials
DELHIVERY_API_TOKEN = os.getenv("DELHIVERY_API_TOKEN", "")
DELHIVERY_BASE_URL = os.getenv("DELHIVERY_BASE_URL",  "https://track.delhivery.com")
ORIGIN_PINCODE = os.getenv("ORIGIN_PINCODE")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# cloudinary.config(
#     cloud_name=CLOUDINARY_CLOUD_NAME,
#     api_key=CLOUDINARY_API_KEY,
#     api_secret=CLOUDINARY_API_SECRET,
#     secure=True
# )

app = FastAPI()
# app.include_router(router, prefix="") 


@app.get("/")
def root():
    return {"message": "Welcome to Myha Backend 🚀"}


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "https://taupe-cannoli-010c45.netlify.app",
        "https://myhacouture.com",
        "https://www.myhacouture.com",
        "https://myhafrontend.pages.dev"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================
# Helpers
# =============================
def fix_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    doc["id"] = str(doc["_id"])
    doc.pop("_id", None)
    return doc


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()

# =============================
# Image URL Builder (R2)
# =============================
R2_BASE = os.getenv("R2_PUBLIC_BASE_URL")
print("🔥 R2_BASE =", R2_BASE)

# =============================
# Cloudflare R2 Upload Client
# =============================

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")

r2_client = boto3.client(
    "s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
    region_name="auto"
)


def build_product_image_urls(product_id: str, image_count: int):
    if not R2_BASE or not image_count:
        return []
    return [
        f"{R2_BASE}/products/{product_id}/{i}.jpg"
        for i in range(1, image_count + 1)
    ]


from io import BytesIO

def upload_to_r2(file_bytes: bytes, object_key: str, content_type: str = "image/jpeg"):
    r2_client.upload_fileobj(
        BytesIO(file_bytes),
        R2_BUCKET_NAME,
        object_key,
        ExtraArgs={
            "ContentType": content_type
        }
    )



def upload_exchange_evidence_to_r2(
    file_bytes: bytes,
    object_key: str,
    content_type: str
) -> str:

    if not file_bytes:
        raise ValueError("Exchange evidence file is empty.")

    if not object_key or not isinstance(object_key, str):
        raise ValueError("Exchange evidence object key is invalid.")

    if not content_type:
        raise ValueError("Exchange evidence content type is invalid.")

    if not R2_BUCKET_NAME:
        raise RuntimeError("R2 bucket is not configured.")

    if not R2_BASE:
        raise RuntimeError("R2 public URL is not configured.")

    # Upload using the existing configured R2 client
    r2_client.upload_fileobj(
        BytesIO(file_bytes),
        R2_BUCKET_NAME,
        object_key,
        ExtraArgs={
            "ContentType": content_type
        }
    )

    return object_key



def delete_from_r2(object_key: str):
    r2_client.delete_object(
        Bucket=R2_BUCKET_NAME,
        Key=object_key
    )




@app.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    user = await users_collection.find_one({"email": req.email})
    if not user:
        raise HTTPException(404, "Email not registered")

    otp = str(random.randint(100000, 999999))
    expiry = datetime.utcnow() + timedelta(minutes=10)

    await users_collection.update_one(
        {"email": req.email},
        {"$set": {
            "resetOtp": otp,
            "resetOtpExpiry": expiry
        }}
    )

    # Send OTP Email
    try:
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = BREVO_API_KEY
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": req.email}],
            sender={"name": "Myha Couture", "email": "order@myhacouture.com"},
            subject="Myha Couture - Password Reset OTP",
            html_content=f"<p>Your OTP for resetting the password is <b>{otp}</b>.<br>Valid for 10 minutes.</p>"
        )
        api_instance.send_transac_email(send_smtp_email)

    except ApiException as e:
        print("❌ Brevo API error")
        print("Status:", e.status)
        print("Body:", e.body)
        raise HTTPException(
            status_code=500,
            detail="Email service failed. Please try again later."
        )

    except Exception as e:
        print("❌ Unexpected email error:", str(e))
        raise HTTPException(
            status_code=500,
            detail="Unexpected email error"
        )

    return {"message": "OTP sent to your email"}

# reset pass

@app.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    user = await users_collection.find_one({"email": req.email})
    if not user:
        raise HTTPException(404, "Invalid email")

    # Check OTP
    if str(user.get("resetOtp")) != req.otp:
        raise HTTPException(400, "Invalid OTP")

    # Check expiry
    if datetime.utcnow() > user.get("resetOtpExpiry"):
        raise HTTPException(400, "OTP expired")

    # Hash new password
    hashed = pwd_context.hash(req.newPassword)

    # Update password + clear OTP
    await users_collection.update_one(
        {"email": req.email},
        {"$set": {"password": hashed},
         "$unset": {"resetOtp": "", "resetOtpExpiry": ""}}
    )

    return {"message": "Password reset successful"}


# =============================
# App startup: indexes
# =============================
@app.on_event("startup")
async def _ensure_indexes():
    coll = db["orders"]

    # Ensure orderId unique
    try:
        await coll.create_index([("orderId", 1)], name="orderId_1", unique=True)
    except OperationFailure as e:
        print(f"Index create warning (orderId): {e}")

    # Handle createdAt index: if TTL exists, drop and recreate without TTL
    try:
        idx_list = await coll.list_indexes().to_list(length=None)
        for idx in idx_list:
            if idx.get("key") == {"createdAt": 1}:
                # If TTL present, drop it
                if "expireAfterSeconds" in idx:
                    try:
                        await coll.drop_index(idx["name"])
                        print(f"Dropped TTL index {idx['name']} on createdAt")
                    except OperationFailure as e:
                        print(f"Drop index warning: {e}")
                break

        # Recreate plain index (non-TTL)
        await coll.create_index([("createdAt", 1)], name="createdAt_1")
    except OperationFailure as e:
        print(f"Index create warning (createdAt): {e}")



from fastapi import Depends
from jose import jwt, JWTError

# ============================
# Helper: Decode User JWT
# ============================
def get_current_user(token: str = Header(None)):
    if not token:
        raise HTTPException(status_code=401, detail="Token missing")

    try:
        payload = jwt.decode(token.replace("Bearer ", ""), JWT_SECRET, algorithms=[JWT_ALGO])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ============================
# ✨ My Orders (Customer Only)
# ============================
@app.get("/my-orders")
async def my_orders(user=Depends(get_current_user)):
    email = user.get("email")

    orders_cursor = db["orders"].find(
        {"checkoutData.email": email},
        {
            "_id": 0,
            "orderId": 1,
            "status": 1,
            "createdAt": 1,
            "grandTotal": 1,
            "cartItems": 1,
            "awb": 1
        }
    ).sort("createdAt", -1)

    orders = [o async for o in orders_cursor]
    return {"orders": orders}


# =============================
# Utility: Generate Professional Order ID (kept for reference if needed elsewhere)
# =============================
def generate_order_id():
    now = datetime.utcnow()
    return f"MYHA{now.strftime('%Y%m%d%H%M%S')}{random.randint(100,999)}"



#delete
# ================

@app.delete("/delete-order/{order_id}")
async def delete_order(order_id: str):
    try:
        result = await db.orders.delete_one({"orderId": order_id})
        if result.deleted_count == 1:
            return {"success": True, "message": f"Order {order_id} deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Order not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================
# Send Email (Order Confirmation with Shipping + Product Images)
# =============================
def send_order_email(to_email, order_data, is_admin=False):

    print("🚨 send_order_email FUNCTION CALLED 🚨")
    print("➡️ to_email:", to_email)
    print("➡️ orderId:", order_data.get("orderId"))

    try:
        # 📌 Subject line
        if is_admin:
            subject = f"📦 New Order Received – Myha Couture #{order_data.get('orderId')}"
        else:
            subject = f"Myha Couture - Order Confirmation #{order_data.get('orderId')}"

        checkout = order_data.get("checkoutData", {})
        cart_items = order_data.get("cartItems", [])
        items_html = ""

        # 🛒 Cart items table
        if cart_items:
            items_html += """
            <table style="width:100%; border-collapse:collapse; margin-top:20px; font-size:14px;">
              <thead>
                <tr style="background:#f9f9f9;">
                  <th style="border:1px solid #ddd; padding:8px; text-align:left;">Image</th>
                  <th style="border:1px solid #ddd; padding:8px; text-align:left;">Product</th>
                  <th style="border:1px solid #ddd; padding:8px; text-align:center;">Qty</th>
                  <th style="border:1px solid #ddd; padding:8px; text-align:right;">Total</th>
                </tr>
              </thead>
              <tbody>
            """
            for item in cart_items:
                name = item.get("name", "N/A")
                price = item.get("price", 0)
                if isinstance(price, str):
                    price = price.replace("₹", "").replace(",", "").strip()
                price = float(price or 0)

                qty = int(item.get("quantity", 1))
                total = price * qty
                image = item.get("images", [""])[0] if item.get("images") else item.get("image", "")

                # extra details
                size = item.get("selectedSize", "")
                sleeve = item.get("sleeveType", "")
                sleeve_price = float(item.get("sleevePrice", 0) or 0)
                height = item.get("preferredHeight", "")
                height_price = float(item.get("extraHeightPrice", 0) or 0)

                extra_html = ""
                if size:
                    extra_html += f"Size: {size}<br>"
                if sleeve:
                    extra_html += f"Sleeve: {sleeve} (+₹{sleeve_price})<br>"
                if height:
                    extra_html += f"Height: {height} (+₹{height_price})<br>"

                items_html += f"""
                <tr>
                  <td style="border:1px solid #ddd; padding:8px; text-align:center;">
                    <img src="{image}" alt="{name}" style="max-width:60px; border-radius:6px;" />
                  </td>
                  <td style="border:1px solid #ddd; padding:8px;">
                    <strong>{name}</strong><br>
                    {extra_html}
                  </td>
                  <td style="border:1px solid #ddd; padding:8px; text-align:center;">{qty}</td>
                  <td style="border:1px solid #ddd; padding:8px; text-align:right;">₹{total:.2f}</td>
                </tr>
                """
            items_html += "</tbody></table>"

        # 🧾 Total
        total_amount = order_data.get("totalAmount", 0)
        if isinstance(total_amount, str):
            total_amount = total_amount.replace("₹", "").replace(",", "").strip()
        total_amount = float(total_amount or 0)

        # 👋 Greeting / Intro
        if is_admin:
            greeting = f"<h2 style='color:#000;'>🚨 New Order Alert</h2>"
            intro = f"<p>A new order <b>#{order_data.get('orderId')}</b> has been placed by <b>{checkout.get('name')}</b>.</p>"
        else:
            greeting = f"<h2 style='color:#000;'>Thank you for shopping with <span style='color:#d63384;'>Myha Couture</span>, {checkout.get('name')}!</h2>"
            intro = f"<p>Your order <b>#{order_data.get('orderId')}</b> has been placed successfully. We’ll notify you once it is shipped.</p>"

        # 📦 Shipping details
        shipping_html = f"""
        <div style="margin-top:20px; font-size:14px; line-height:1.5;">
          <h3 style="margin-bottom:8px;">📍 Shipping Details</h3>
          <p>
            {checkout.get('name')}<br>
            {checkout.get('addressLine1')}<br>
            {checkout.get('addressLine2', '')}<br>
            {checkout.get('city')}, {checkout.get('state')} - {checkout.get('pincode')}<br>
            Phone: {checkout.get('phone')}<br>
            Email: {checkout.get('email')}
          </p>
        </div>
        """

        # 📧 Final HTML
        html = f"""
        <div style="font-family: Arial, sans-serif; color: #333; max-width: 650px; margin: auto; border:1px solid #eee; border-radius:8px; overflow:hidden;">
          <div style="background:#000; padding:20px; text-align:center;">
            <img src="https://res.cloudinary.com/dw35epojg/image/upload/v1754020493/logo_v5px6x.jpg" alt="Myha Logo" style="max-height:50px;" />
          </div>
          <div style="padding:20px;">
            {greeting}
            {intro}
            {shipping_html}
            {items_html}
            <p style="margin-top:20px; font-size:16px;"><b>Grand Total: ₹{total_amount:.2f}</b></p>
          </div>
        </div>
        """

        # 🔑 Brevo Config
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = BREVO_API_KEY
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

        # 📤 Build email object
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": to_email}],
            sender={"name": "Myha Couture", "email": "order@myhacouture.com"},  # must match verified sender
            subject=subject,
            html_content=html
        )

        # 🚀 Send email
        response = api_instance.send_transac_email(send_smtp_email)
        print(f"✅ Order email sent to {to_email}, messageId={response.message_id}")

    except ApiException as e:
        print("❌ Brevo API error")
        print("Status:", e.status)
        print("Body:", e.body)
        raise HTTPException(
            status_code=500,
            detail="Email service failed. Please try again later."
        )

    except Exception as e:
        print("❌ Unexpected email error:", str(e))
        raise HTTPException(
            status_code=500,
            detail="Unexpected email error"
        )


        
# =============================
# ⭐ Delhivery Tracking Helper
# =============================
async def fetch_delhivery_tracking(awb: str):
    url = (
        f"{DELHIVERY_BASE_URL}/api/v1/packages/json/"
        f"?waybill={awb}"
    )

    headers = {
        "Authorization": f"Token {DELHIVERY_API_TOKEN}",
        "Accept": "application/json"
    }

    # =========================================
    # 1. Fetch tracking information
    # =========================================
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url,
                headers=headers
            )

            print(
                f"[DELHIVERY] HTTP status: "
                f"{response.status_code}"
            )

            response.raise_for_status()
            data = response.json()

    except httpx.HTTPStatusError as exc:
        print(
            f"[DELHIVERY] HTTP error: "
            f"{exc.response.status_code}"
        )
        print(
            f"[DELHIVERY] Response body: "
            f"{exc.response.text[:1000]}"
        )
        return []

    except Exception as exc:
        print(
            f"[DELHIVERY] API request failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return []

    # =========================================
    # 2. Validate response structure
    # =========================================
    timeline = []

    try:
        shipment_data = data.get("ShipmentData", [])

        if not isinstance(shipment_data, list):
            print(
                "[DELHIVERY] Unexpected ShipmentData format."
            )
            return []

        if not shipment_data:
            print(
                f"[DELHIVERY] No shipment data returned "
                f"for AWB {awb}"
            )
            print(
                f"[DELHIVERY] Response: {repr(data)[:2000]}"
            )
            return []

        shipment = shipment_data[0].get("Shipment", {})

        if not isinstance(shipment, dict):
            print(
                "[DELHIVERY] Invalid Shipment structure."
            )
            return []

        scans = shipment.get("Scans", [])

        if not isinstance(scans, list):
            print(
                "[DELHIVERY] Invalid Scans structure."
            )
            return []

        # =========================================
        # 3. Extract ALL available scan events
        # =========================================
        for scan in scans:

            if not isinstance(scan, dict):
                continue

            detail = scan.get("ScanDetail", {})

            if not isinstance(detail, dict):
                continue

            status = str(
                detail.get("Scan", "")
            ).strip()

            scan_time = detail.get("ScanDateTime")

            location = detail.get("ScannedLocation")

            print(
                f"[DELHIVERY] AWB={awb}, "
                f"status={status!r}, "
                f"time={scan_time!r}"
            )

            # Do not filter out Manifested or other statuses.
            # Exchange eligibility is determined separately.
            if not status:
                continue

            timeline.append({
                "status": status,
                "time": scan_time,
                "source": "Delhivery",
                "location": location
            })

        print(
            f"[DELHIVERY] Extracted {len(timeline)} "
            f"tracking events for AWB {awb}"
        )

        return timeline

    except Exception as exc:
        print(
            f"[DELHIVERY] Response parsing failed: "
            f"{type(exc).__name__}: {exc}"
        )

        return []

# =============================
# Product APIs
# =============================
@app.get("/products")
async def get_products():
    try:
        products_cursor = db["products"].find().sort([("displayOrder", 1), ("createdAt", -1)])
        products = []
        async for product in products_cursor:
            product = fix_id(product)
            product["images"] = build_product_image_urls(
                product["id"],
                 product.get("image_count", 0)
            )
            products.append(product)
        return products
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/product/{product_id}")
async def get_product(product_id: str):
    try:
        if not ObjectId.is_valid(product_id):
            raise HTTPException(
                status_code=400,
                detail="Invalid product ID"
            )

        product = await db["products"].find_one(
            {"_id": ObjectId(product_id)}
        )

        if not product:
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        product = fix_id(product)

        product["images"] = build_product_image_urls(
            product["id"],
            product.get("image_count", 0)
        )

        return product

    except HTTPException:
        raise

    except Exception as e:
        print(f"Error retrieving product {product_id}: {e}")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve product details"
        )



# =========================================================
# HOMEPAGE CATEGORY HERO IMAGES
# =========================================================

@app.get("/homepage/categories")
async def get_homepage_categories():

    try:

        cursor = db["homepage_categories"].find(
            {},
            {
                "_id": 0,
                "category": 1,
                "productId": 1,
                "imageIndex": 1
            }
        )

        settings = []

        async for item in cursor:

            category = item.get("category")
            product_id = item.get("productId")
            image_index = int(item.get("imageIndex", 0) or 0)

            hero_image = None

            # ==========================================
            # Build R2 image URL
            # ==========================================

            if (
                product_id
                and image_index > 0
                and R2_BASE
            ):

                hero_image = (
                    f"{R2_BASE}/products/"
                    f"{product_id}/"
                    f"{image_index}.jpg"
                )

            settings.append({
                "category": category,
                "productId": product_id,
                "imageIndex": image_index,
                "heroImage": hero_image
            })

        return settings

    except Exception as e:

        print(
            "❌ Failed to load homepage categories:",
            e
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to load homepage settings"
        )


# =========================================================
# SAVE HOMEPAGE CATEGORY HERO IMAGE
# =========================================================

@app.put("/homepage/categories/{category}")
async def save_homepage_category(
    category: str,
    request: Request,
    authorization: str = Header(None)
):

    # ==========================================
    # 1. ADMIN AUTHENTICATION
    # ==========================================

    if authorization != f"Bearer {ADMIN_TOKEN}":

        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )


    # ==========================================
    # 2. READ REQUEST
    # ==========================================

    data = await request.json()

    product_id = data.get("productId")
    image_index = data.get("imageIndex")


    # ==========================================
    # 3. VALIDATE PRODUCT ID
    # ==========================================

    if not product_id:

        raise HTTPException(
            status_code=400,
            detail="productId is required"
        )

    try:

        product_object_id = ObjectId(product_id)

    except Exception:

        raise HTTPException(
            status_code=400,
            detail="Invalid productId"
        )


    # ==========================================
    # 4. VALIDATE IMAGE INDEX
    # ==========================================

    try:

        image_index = int(image_index)

    except Exception:

        raise HTTPException(
            status_code=400,
            detail="imageIndex must be a number"
        )


    if image_index < 1:

        raise HTTPException(
            status_code=400,
            detail="imageIndex must be at least 1"
        )


    # ==========================================
    # 5. VERIFY PRODUCT EXISTS
    # ==========================================

    product = await db["products"].find_one(
        {"_id": product_object_id}
    )

    if not product:

        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )


    # ==========================================
    # 6. VERIFY IMAGE ACTUALLY EXISTS
    # ==========================================

    image_count = int(
        product.get("image_count", 0) or 0
    )

    if image_index > image_count:

        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid imageIndex. "
                f"This product has {image_count} images."
            )
        )


    # ==========================================
    # 7. VERIFY CATEGORY
    # ==========================================

    product_category = str(
        product.get("category", "")
    ).strip()

    requested_category = category.strip()


    if product_category.lower() != requested_category.lower():

        raise HTTPException(
            status_code=400,
            detail=(
                "Selected product does not belong "
                "to the selected category."
            )
        )


    # ==========================================
    # 8. SAVE HOMEPAGE SETTING
    # ==========================================

    await db["homepage_categories"].update_one(

        {
            "category": requested_category
        },

        {
            "$set": {
                "category": requested_category,
                "productId": product_id,
                "imageIndex": image_index,
                "updatedAt": iso_now()
            }
        },

        upsert=True
    )


    # ==========================================
    # 9. BUILD IMAGE URL FOR RESPONSE
    # ==========================================

    hero_image = (
        f"{R2_BASE}/products/"
        f"{product_id}/"
        f"{image_index}.jpg"
    )


    return {

        "success": True,

        "category": requested_category,

        "productId": product_id,

        "imageIndex": image_index,

        "heroImage": hero_image

    }

# @app.post("/admin/test-email")
# async def test_email():
#     print("🚨 TEST EMAIL ENDPOINT HIT 🚨")

#     dummy_order = {
#         "orderId": "TEST123",
#         "checkoutData": {
#             "name": "Test User",
#             "email": "snmsss2002l@gmail.com",
#             "phone": "9999999999",
#             "addressLine1": "Test Address",
#             "city": "Chennai",
#             "state": "Tamil Nadu",
#             "pincode": "600001"
#         },
#         "cartItems": [
#             {
#                 "name": "Test Product",
#                 "price": 1000,
#                 "quantity": 1,
#                 "images": ["https://via.placeholder.com/150"]
#             }
#         ],
#         "totalAmount": 1000
#     }

#     send_order_email(
#         to_email="snmsss2002@gmail.com",
#         order_data=dummy_order,
#         is_admin=False
#     )

#     return {"status": "test email triggered"}




@app.post("/add-product")
async def add_product(product: ProductCreate):
    if product.image_count < 0:
        raise HTTPException(
            status_code=400,
            detail="image_count must be greater than 0"
        )

    product_data = product.dict()

    # 🔑 system-generated defaults
    product_data.update({
        "sizes": DEFAULT_SIZES.copy(),
        "selectedSize": "M",
        "selectedColor": product.colors[0] if product.colors else "",
        "images": [],               # images come from R2
        "isSoldOut": False,
        "displayOrder": 0,
        "createdAt": iso_now()
    })

    result = await db["products"].insert_one(product_data)

    return {
        "message": "Product added",
        "id": str(result.inserted_id)
    }


@app.post("/upload-product-images/{product_id}")
async def upload_product_images(
    product_id: str,
    images: List[UploadFile] = File(...),
    authorization: str = Header(None)
):
    # =============================
    # Admin Authentication
    # =============================
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    # =============================
    # Validate Product ID
    # =============================
    try:
        object_id = ObjectId(product_id)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid product ID"
        )

    # =============================
    # Verify Product Exists
    # =============================
    product = await db["products"].find_one({"_id": object_id})

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    # =============================
    # Validate Images
    # =============================
    if not images:
        raise HTTPException(
            status_code=400,
            detail="No images uploaded"
        )

    if len(images) > 20:
        raise HTTPException(
            status_code=400,
            detail="Maximum 20 images allowed"
        )

    allowed_types = {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif"
    }

    image_count = 0

    try:

        for index, image in enumerate(images, start=1):

            if image.content_type not in allowed_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {image.filename}"
                )

            print(f"⬆ Uploading {image.filename} -> products/{product_id}/{index}.jpg")

            contents = await image.read()

            upload_to_r2(
                contents,
                f"products/{product_id}/{index}.jpg",
                "image/jpeg"
            )

            image_count += 1

        # =============================
        # Update MongoDB
        # =============================
        await db["products"].update_one(
            {"_id": object_id},
            {
                "$set": {
                    "image_count": image_count
                }
            }
        )

        return {
            "success": True,
            "message": "Images uploaded successfully",
            "productId": product_id,
            "image_count": image_count
        }

    except HTTPException:
        raise

    except Exception as e:
        print(f"❌ Image upload failed: {e}")

        raise HTTPException(
            status_code=500,
            detail="Failed to upload images"
        )

@app.post("/upload-product")
async def upload_product(
    name: str = Form(...),
    price: float = Form(...),
    description: str = Form(""),
    category: str = Form(...),
    sizes: List[str] = Form(default=["Free Size"]),
    colors: List[str] = Form(default=["Default"]),
    images: List[UploadFile] = File(None),
    authorization: str = Header(None)
):
   raise HTTPException(
        status_code=410,
        detail="Product image upload is temporarily disabled. Use R2 manual upload."
    )


# =============================
# Razorpay Order Creation
# =============================
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from database import db, get_next_order_id  # ✅ make sure this import exists
import httpx



@app.post("/create-order")
async def create_order(request: Request):
    try:
        data = await request.json()

        amount = float(data.get("amount", 0))
        currency = data.get("currency", "INR")
        notes = data.get("notes", {})
        destination_pincode = data.get("destination_pincode")

        if amount <= 0:
            raise HTTPException(
                status_code=400,
                detail="Amount is required"
            )

        # 1. Generate Myha order ID
        order_id = await get_next_order_id()

        # 2. Create Razorpay order
        razorpay_order = razorpay_client.order.create({
            "amount": int(round(amount * 100)),
            "currency": currency,
            "receipt": f"MYHA{order_id}",
            "notes": notes,
            "payment_capture": 1
        })

        # 3. Prepare pending order document
        now = iso_now()

        order_document = {
            "orderId": order_id,
            "razorpayOrderId": razorpay_order["id"],
            "razorpayPaymentId": None,

            "paymentStatus": "Pending",
            "paymentConfirmed": False,

            "status": "Payment Pending",
            "createdAt": now,
            "updatedAt": now,

            "statusTimeline": {
                "Payment Pending": now
            },

            "mode": data.get("mode", "guest"),
            "userId": data.get("userId"),

            "checkoutData": data.get("checkoutData", {}),
            "cartItems": data.get("cartItems", []),

            "cartTotal": float(data.get("cartTotal", 0)),
            "shippingCost": float(data.get("shippingCost", 0)),
            "grandTotal": amount,

            "amountPaise": int(round(amount * 100)),
            "currency": currency,

            "destination_pincode": destination_pincode,
            "paymentType": "Prepaid"
        }

        # 4. Save order BEFORE payment
        await db["orders"].insert_one(order_document)

        print(f"✅ Pending order saved: {order_id}")

        # 5. Return Razorpay details
        return {
            "success": True,
            "message": "Pending order created",
            "orderId": order_id,
            "razorpay_order": razorpay_order,
            "shippingCharge": data.get("shippingCost", 0)
        }

    except HTTPException:
        raise

    except Exception as e:
        print(f"❌ Error creating order: {e}")

        raise HTTPException(
            status_code=500,
            detail="Could not create order"
        )


# ===================================================
# Helper: Delhivery Shipping Charge Fetch
# ===================================================
async def fetch_shipping_charge(destination_pincode: str, weight: int = 500, pt: str = "Pre-paid"):
    """Fetch live shipping cost from Delhivery API."""
    params = {
        "md": "E",
        "ss": "Delivered",
        "d_pin": destination_pincode,
        "o_pin": ORIGIN_PINCODE,
        "cgm": weight,
        "pt": pt
    }
    headers = {
        "Authorization": f"Token {DELHIVERY_API_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{DELHIVERY_BASE_URL}/api/kinko/v1/invoice/charges/.json",
            params=params,
            headers=headers
        )

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch shipping charges")

    data = response.json()
    print("EXCHANGE DELHIVERY RAW RESPONSE:", data)

    # Some Delhivery accounts return a list; handle both formats
    if isinstance(data, list) and data:
        return float(data[0].get("total_amount", 0))
    elif isinstance(data, dict):
        return float(data.get("total_amount", 0))
    return 0.0


# =============================
# Save Order & Send Email
# (Normalized cartItems + ISO timestamps)
# =============================
from database import db, get_next_order_id  # ✅ ensure this import is at the top
@app.post("/save-order")
async def save_order(request: Request):
    data = await request.json()

    # =========================
    # 1️⃣ Validate orderId
    # =========================
    myha_order_id = data.get("orderId")

    if not myha_order_id:
        raise HTTPException(
            status_code=400,
            detail="Missing orderId from frontend"
        )

    data["orderId"] = myha_order_id
    data["razorpayOrderId"] = data.get("razorpayOrderId")
    data["razorpayPaymentId"] = data.get("razorpayPaymentId")


    # =========================
    # 2️⃣ Status + timestamps
    # =========================
    now = iso_now()

    data["status"] = "Ordered"
    data["createdAt"] = now

    data["statusTimeline"] = {
        "Ordered": now
    }


    # =========================
    # 3️⃣ Normalize cart items
    # =========================
    normalized_items = []

    for it in data.get("cartItems", []):

        try:
            price = it.get("price", 0)

            if isinstance(price, str):
                price = (
                    price
                    .replace("₹", "")
                    .replace(",", "")
                    .strip()
                )

            price = float(price or 0)

            qty = int(it.get("quantity", 1))

            sleeve_price = float(
                it.get("sleevePrice", 0) or 0
            )

            height_price = float(
                it.get("extraHeightPrice", 0) or 0
            )

            bust_price = float(
                it.get("bustExtra", 0) or 0
            )


            line_total = (
                price
                + sleeve_price
                + height_price
                + bust_price
            ) * qty


            normalized_items.append({
                "productId": it.get("productId") or it.get("_id"),
                "name": it.get("name", "N/A"),

                "image": (
                    (it.get("images") or [""])[0]
                    if it.get("images")
                    else it.get("image", "")
                ),

                "price": price,
                "quantity": qty,

                "selectedSize": it.get("selectedSize"),

                "sleeveType": it.get("sleeveType"),
                "sleevePrice": sleeve_price,

                "preferredHeight": it.get("preferredHeight"),
                "extraHeightPrice": height_price,

                "neckCustomization": it.get("neckCustomization"),

                "bustExtra": bust_price,

                "lineTotal": line_total,

                "measurements": it.get("measurements", {}),

                "customizationNotes": it.get(
                    "customizationNotes",
                    ""
                )
            })


        except Exception as e:
            print(
                "⚠️ Cart item normalization failed:",
                e
            )


    data["cartItems"] = normalized_items



    # =========================
    # 4️⃣ Calculate totals
    # =========================

    cart_total = sum(
        item["lineTotal"]
        for item in normalized_items
    )


    checkout = data.get("checkoutData") or {}

    if isinstance(checkout, list):
        checkout = checkout[0] if checkout else {}


    # IMPORTANT FIX
    # Use already paid shipping amount
    # Do NOT call Delhivery again here

    shipping_cost = float(
        data.get("shippingCost", 0) or 0
    )


    grand_total = cart_total + shipping_cost


    data["cartTotal"] = cart_total
    data["shippingCost"] = shipping_cost
    data["grandTotal"] = grand_total



    # =========================
    # 5️⃣ Save order
    # =========================

    try:

        existing = await db["orders"].find_one(
            {
                "orderId": myha_order_id
            }
        )


        if existing:

            await db["orders"].update_one(
                {
                    "orderId": myha_order_id
                },
                {
                    "$set": data
                }
            )

            result_id = existing["_id"]


        else:

            result = await db["orders"].insert_one(
                data
            )

            result_id = result.inserted_id



    except Exception as e:

        print(
            "❌ DATABASE SAVE FAILED:",
            e
        )

        raise HTTPException(
            status_code=500,
            detail="Order save failed"
        )



    # =========================
    # 6️⃣ Emails
    # =========================

    customer_email = checkout.get("email")


    try:

        if customer_email:
            send_order_email(
                customer_email,
                data,
                is_admin=False
            )

    except Exception as e:
        print(
            "⚠️ Customer email failed:",
            e
        )



    try:

        if ADMIN_EMAIL:
            send_order_email(
                ADMIN_EMAIL,
                data,
                is_admin=True
            )


    except Exception as e:

        print(
            "⚠️ Admin email failed:",
            e
        )



    # =========================
    # 7️⃣ Response
    # =========================

    return {
        "message": "Order saved successfully",
        "orderId": myha_order_id,
        "id": str(result_id),
        "cartTotal": cart_total,
        "shippingCost": shipping_cost,
        "grandTotal": grand_total
    }

# =============================
# Admin: View Orders (projection + sort)
# =============================
@app.get("/orders")
async def get_orders(authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    cursor = db["orders"].find(
        {},
        {
            "_id": 0,
            "orderId": 1,
            "status": 1,
            "createdAt": 1,
            "awb": 1,
            "totalAmount": 1,
            "checkoutData.name": 1,
            "checkoutData.phone": 1,
        }
    ).sort("createdAt", -1)

    orders = [o async for o in cursor]
    return orders



#drag and drop
# ==================

@app.post("/update-order")
async def update_order(request: Request):
    """
    Accepts a list of { _id, displayOrder } from the admin frontend
    and updates each product’s displayOrder in MongoDB.
    """
    try:
        data = await request.json()  # list of dicts
        if not isinstance(data, list):
            return {"error": "Invalid payload format. Expected a list."}

        # Update each product individually
        for item in data:
            _id = item.get("_id")
            order = item.get("displayOrder", 0)
            if not _id:
                continue
            await db["products"].update_one(
                {"_id": ObjectId(_id)},
                {"$set": {"displayOrder": order}}
            )

        return {"message": "✅ Product order updated successfully"}

    except Exception as e:
        print("🔥 Error updating order:", e)
        return {"error": str(e)}



# =============================
# Admin: Update Status (with AWB)
# =============================
@app.put("/orders/{order_id}/status")
async def update_order_status(order_id: str, request: Request, authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()
    new_status = data.get("status")

    valid_statuses = ["Ordered", "Preparing", "Packed", "Shipped", "Delivered", "Cancelled"]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")

    # ✅ find order by string or numeric orderId
    order = await db["orders"].find_one({"orderId": order_id})
    if not order:
        try:
            numeric_id = int(order_id)
            order = await db["orders"].find_one({"orderId": numeric_id})
        except ValueError:
            pass
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # ✅ update timeline
    status_timeline = order.get("statusTimeline", {})
    status_timeline[new_status] = iso_now()
    update_data: Dict[str, Any] = {"status": new_status, "statusTimeline": status_timeline}

    # ⭐ Shipment creation when Packed
    if new_status == "Packed" and not order.get("awb"):
        checkout = order.get("checkoutData") or {}
        if isinstance(checkout, list) and checkout:
            checkout = checkout[0]

        try:
            shipment_payload = {
                "shipments": [
                    {
                        "name": checkout.get("name", "Unknown"),
                        "add": checkout.get("address", checkout.get("addressLine1", "Not Provided")),
                        "pin": checkout.get("pincode", ""),
                        "city": checkout.get("city", "Chennai"),
                        "state": checkout.get("state", "Tamil Nadu"),
                        "country": "India",
                        "phone": checkout.get("phone", ""),
                        "order": order["orderId"],
                        "payment_mode": "Prepaid" if order.get("paymentType") == "Prepaid" else "COD",
                        "cod_amount": float(order.get("totalAmount", 0)) if order.get("paymentType") == "COD" else 0,
                        "total_amount": float(order.get("totalAmount", 0) or 0),
                        "products_desc": ", ".join([p.get("name", "") for p in order.get("cartItems", [])]),
                        "quantity": len(order.get("cartItems", [])),
                        "weight": 0.5,
                        "shipment_width": "20",
                        "shipment_height": "5",
                        "shipping_mode": "Surface",
                        "return_add": "Myha Return Address",
                        "return_pin": "600002",
                        "return_city": "Chennai",
                        "return_state": "Tamil Nadu",
                        "return_country": "India",
                        "return_phone": "9876543210"
                    }
                ],
                "pickup_location": {"name": "Myha"}
            }

            headers = {
                "Authorization": f"Token {DELHIVERY_API_TOKEN}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json"
            }

            # === first attempt ===
            async with httpx.AsyncClient(timeout=40.0) as client:
                resp = await client.post(
                    f"{DELHIVERY_BASE_URL}/api/cmu/create.json",
                    headers=headers,
                    data={"format": "json", "data": json.dumps(shipment_payload)}
                )

            data_resp = resp.json()
            print("📦 Delhivery Response:", data_resp)

            awb = None
            if (
                resp.status_code == 200
                and "packages" in data_resp
                and data_resp["packages"]
                and data_resp["packages"][0].get("waybill")
            ):
                awb = data_resp["packages"][0]["waybill"]

            # === retry once if AWB missing ===
            if not awb:
                print(f"⚠️ AWB missing for {order_id}, retrying once...")
                await asyncio.sleep(2)
                async with httpx.AsyncClient(timeout=40.0) as client:
                    retry_resp = await client.post(
                        f"{DELHIVERY_BASE_URL}/api/cmu/create.json",
                        headers=headers,
                        data={"format": "json", "data": json.dumps(shipment_payload)}
                    )
                retry_data = retry_resp.json()
                print("📦 Retry Response:", retry_data)
                if (
                    retry_resp.status_code == 200
                    and "packages" in retry_data
                    and retry_data["packages"]
                    and retry_data["packages"][0].get("waybill")
                ):
                    awb = retry_data["packages"][0]["waybill"]

            # === final assignment ===
            if awb:
                update_data["awb"] = awb
            else:
                print(f"❌ AWB not received even after retry for {order_id}")
                update_data["awb"] = None  # no dummy assigned

        except Exception as e:
            print(f"❌ Delhivery Shipment creation error: {e}")
            update_data["awb"] = None  # ensure never dummy

    # ✅ commit update
    result = await db["orders"].update_one({"orderId": order_id}, {"$set": update_data})
    if result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to update status")

    return {
        "message": "Status updated successfully",
        "orderId": order_id,
        "status": new_status,
        "statusTimeline": status_timeline,
        "awb": update_data.get("awb", order.get("awb"))
    }


# =============================
# ⭐ Unified Timeline Endpoint
# =============================
@app.get("/orders/{order_id}/timeline")
async def get_order_timeline(order_id: str):

    # Try as string
    order = await db["orders"].find_one({"orderId": order_id})

    # Try as number
    if not order:
        try:
            numeric_id = int(order_id)
            order = await db["orders"].find_one({"orderId": numeric_id})
        except:
            pass

    # Not found at all
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Build admin timeline
    admin_timeline = []
    for status, time in order.get("statusTimeline", {}).items():
        admin_timeline.append({
            "status": status,
            "time": time,
            "source": "Admin"
        })

    # Build courier timeline
    courier_timeline = []
    if order.get("awb"):
        courier_timeline = await fetch_delhivery_tracking(order["awb"])

    # Merge & sort
    full_timeline = admin_timeline + courier_timeline
    full_timeline.sort(key=lambda x: x.get("time", ""))

    # Return all order details + tracking
    return {
        "orderId": order.get("orderId"),
        "awb": order.get("awb"),
        "timeline": full_timeline,
        "checkoutData": order.get("checkoutData"),
        "cartItems": order.get("cartItems"),
        "grandTotal": order.get("grandTotal"),
        "shippingCost": order.get("shippingCost"),
        "totalAmount": order.get("totalAmount"),
        "status": order.get("status"),
        "createdAt": order.get("createdAt")
    }


# =============================
# Admin: Export Orders
# =============================
@app.get("/orders/export")
async def export_orders(authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    orders_cursor = db["orders"].find().sort("createdAt", -1)
    rows = []
    async for order in orders_cursor:
        created_at = str(order.get("createdAt", ""))
        rows.append({
            "Order ID": order.get("orderId"),
            "Customer": order.get("checkoutData", {}).get("name"),
            "Email": order.get("checkoutData", {}).get("email"),
            "Phone": order.get("checkoutData", {}).get("phone"),
            "Total Amount": order.get("totalAmount"),
            "Status": order.get("status"),
            "AWB": order.get("awb") or "—",
            "Created At": created_at
        })

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Orders")
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=orders.xlsx"}
    )





# =============================
# USER SIGNUP
# =============================
@app.post("/signup")
async def signup(user: UserCreate):
    # Check duplicate email
    existing = await users_collection.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = hash_password(user.password)

    user_data = {
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "password": hashed,
        "createdAt": iso_now()
    }

    await users_collection.insert_one(user_data)

    return {"message": "Account created successfully"}


# =============================
# USER LOGIN
# =============================
@app.post("/login")
async def login(user: UserLogin):
    # Find user by email
    existing = await users_collection.find_one({"email": user.email})
    if not existing:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(user.password, existing["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # JWT payload
    token_data = {
        "userId": str(existing["_id"]),
        "email": existing["email"],
        "role": "customer"
    }

    token = create_jwt_token(token_data)

    return {
        "token": token,
        "role": "customer",
        "name": existing["name"]
    }



# =============================
# Admin Login
# =============================
@app.post("/admin/login")
async def admin_login(request: Request):
    data = await request.json()
    username = data.get("username")
    password = data.get("password")

    ADMIN_USER = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "super-secret")
    ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "myha-secret")

    if username == ADMIN_USER and password == ADMIN_PASSWORD:
        return {
            "token": ADMIN_TOKEN,
            "role": "admin",
            "name": "Admin"
        }

    raise HTTPException(status_code=401, detail="Invalid credentials")



# =============================
# Admin: Delete Product
# =============================
@app.delete("/products/{product_id}")
async def delete_product(product_id: str, authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = await db["products"].delete_one({"_id": ObjectId(product_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product deleted"}


# =============================
# Admin: Update Product
# =============================
@app.put("/products/{product_id}")
async def update_product(
    product_id: str,
    request: Request,
    authorization: str = Header(None)
):
    # =========================
    # 1. Admin authentication
    # =========================
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    # =========================
    # 2. Validate ObjectId
    # =========================
    try:
        product_object_id = ObjectId(product_id)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid product ID"
        )

    # =========================
    # 3. Get existing product
    # =========================
    existing_product = await db["products"].find_one(
        {"_id": product_object_id}
    )

    if not existing_product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    # =========================
    # 4. Read request body
    # =========================
    data = await request.json()

    # =========================
    # 5. Existing images
    # =========================
    old_images = existing_product.get("images", [])

    if not isinstance(old_images, list):
        old_images = []

    # =========================
    # 6. New image array
    # =========================
    new_images = data.get("images", old_images)

    if not isinstance(new_images, list):
        raise HTTPException(
            status_code=400,
            detail="images must be an array"
        )

    # =========================
    # 7. Find removed images
    # =========================
    removed_images = [
        image
        for image in old_images
        if image not in new_images
    ]

    # =========================
    # 8. Delete removed images from R2
    # =========================
    for image_url in removed_images:

        try:
            prefix = "/products/"

            if prefix not in image_url:
                print(
                    f"⚠️ Could not determine R2 key: {image_url}"
                )
                continue

            r2_key = image_url.split(prefix, 1)[1]

            print(
                f"🗑️ Deleting R2 image: {r2_key}"
            )

            delete_from_r2(r2_key)

        except Exception as e:

            print(
                f"⚠️ Failed to delete R2 image "
                f"{image_url}: {e}"
            )

    # =========================
    # 9. Image count
    # =========================
    data["images"] = new_images
    data["image_count"] = len(new_images)

    # =========================
    # 10. Update MongoDB
    # =========================
    result = await db["products"].update_one(
        {"_id": product_object_id},
        {
            "$set": data
        }
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    return {
        "message": "Product updated successfully",
        "image_count": len(new_images),
        "images": new_images
    }


@app.post("/products/{product_id}/add-images")
async def add_product_images(
    product_id: str,
    images: List[UploadFile] = File(...),
    authorization: str = Header(None)
):
    # =============================
    # 1. Admin Authentication
    # =============================
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    # =============================
    # 2. Validate Product ID
    # =============================
    try:
        object_id = ObjectId(product_id)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid product ID"
        )

    # =============================
    # 3. Get Existing Product
    # =============================
    product = await db["products"].find_one(
        {"_id": object_id}
    )

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    # =============================
    # 4. Validate Upload
    # =============================
    if not images:
        raise HTTPException(
            status_code=400,
            detail="No images uploaded"
        )

    # IMPORTANT:
    # Your system uses image_count as the
    # source of truth for R2 numbered images.
    existing_count = int(
        product.get("image_count", 0) or 0
    )

    if existing_count + len(images) > 20:
        raise HTTPException(
            status_code=400,
            detail="Maximum 20 images allowed"
        )

    allowed_types = {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif"
    }

    try:

        # =============================
        # 5. Start AFTER existing images
        # =============================
        start_index = existing_count + 1

        for offset, image in enumerate(images):

            if image.content_type not in allowed_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {image.filename}"
                )

            image_number = start_index + offset

            object_key = (
                f"products/{product_id}/{image_number}.jpg"
            )

            print(
                f"⬆ Adding image: {image.filename} "
                f"-> {object_key}"
            )

            contents = await image.read()

            upload_to_r2(
                contents,
                object_key,
                "image/jpeg"
            )

        # =============================
        # 6. New total count
        # =============================
        new_image_count = existing_count + len(images)

        # =============================
        # 7. Update MongoDB
        # =============================
        await db["products"].update_one(
            {"_id": object_id},
            {
                "$set": {
                    "image_count": new_image_count
                }
            }
        )

        # =============================
        # 8. Build ALL image URLs
        # =============================
        all_images = build_product_image_urls(
            product_id,
            new_image_count
        )

        return {
            "success": True,
            "message": "Images added successfully",
            "productId": product_id,
            "images": all_images,
            "image_count": new_image_count
        }

    except HTTPException:
        raise

    except Exception as e:

        print(
            f"❌ Add image upload failed: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to add images"
        )

    
@app.get("/orders/{order_id}")
async def get_order(order_id: str, authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        # 🔍 Try matching string orderId first
        order = await db["orders"].find_one({"orderId": order_id}, {"_id": 0})

        # 🔁 If not found, try converting to int and match again
        if not order:
            try:
                numeric_id = int(order_id)
                order = await db["orders"].find_one({"orderId": numeric_id}, {"_id": 0})
            except ValueError:
                pass  # order_id wasn't numeric, skip

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        return order

    except Exception as e:
        print(f"❌ Error fetching order details for {order_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# =============================
# Track Order (Customer)
# =============================
@app.post("/track-order")
async def track_order(request: Request):
    data = await request.json()
    order_id = data.get("orderId")

    if not order_id:
        raise HTTPException(status_code=400, detail="Order ID is required")

    try:
        # try finding order by string id first
        order = await db["orders"].find_one({"orderId": order_id})

        # fallback for numeric order IDs stored as int
        if not order:
            try:
                numeric_id = int(order_id)
                order = await db["orders"].find_one({"orderId": numeric_id})
            except ValueError:
                pass  # ignore if conversion fails

        if not order:
            raise HTTPException(status_code=404, detail="No order found with the provided Order ID")

        return fix_id(order)

    except Exception as e:
        print(f"❌ Error tracking order {order_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/add-product-url")
async def add_product_url(request: Request, authorization: str = Header(None)):
    raise HTTPException(
        status_code=410,
        detail="Product image upload is temporarily disabled. Use R2 manual upload."
    )


# =============================
# Reviews API
# =============================
@app.get("/products/{product_id}/reviews")
async def get_reviews(product_id: str):
    try:
        reviews_cursor = db["reviews"].find({"productId": product_id}).sort("createdAt", -1)
        reviews = []
        async for review in reviews_cursor:
            reviews.append(fix_id(review))  # ✅ converts _id → id (string)
        return reviews
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/products/{product_id}/reviews")
async def add_review(
    product_id: str,
    name: str = Form(...),
    rating: int = Form(...),
    comment: str = Form(...),
    image: UploadFile = File(None)
):
    try:
        image_url = None
        if image:
            contents = await image.read()
            upload_result = cloudinary.uploader.upload(contents, folder="reviews")
            image_url = upload_result["secure_url"]

        review_data = {
            "productId": product_id,
            "name": name,
            "rating": rating,
            "comment": comment,
            "image": image_url,
            "createdAt": iso_now()
        }

        result = await db["reviews"].insert_one(review_data)

        # ✅ Instead of returning raw review_data (which has no _id), fetch + fix
        saved_review = await db["reviews"].find_one({"_id": result.inserted_id})
        saved_review = fix_id(saved_review)  # removes ObjectId, adds string id

        return JSONResponse(
            content={
                "success": True,
                "message": "✅ Review added",
                "review": saved_review
            },
            status_code=201
        )

    except Exception as e:
        print("❌ Error adding review:", e)
        raise HTTPException(status_code=500, detail=f"Review add failed: {str(e)}")


# ============================================================
# ADMIN REPLY TO REVIEW
# ============================================================

@app.put("/reviews/{review_id}/reply")
async def reply_to_review(
    review_id: str,
    request: Request,
    authorization: str = Header(None)
):
    try:

        # ========================================================
        # ADMIN AUTHENTICATION
        # ========================================================

        if authorization != f"Bearer {ADMIN_TOKEN}":
            raise HTTPException(
                status_code=401,
                detail="Unauthorized"
            )


        # ========================================================
        # VALIDATE REVIEW ID
        # ========================================================

        try:
            review_object_id = ObjectId(review_id)

        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid review ID"
            )


        # ========================================================
        # REQUEST BODY
        # ========================================================

        data = await request.json()

        reply_comment = str(
            data.get("comment", "")
        ).strip()


        if not reply_comment:

            raise HTTPException(
                status_code=400,
                detail="Reply comment is required"
            )


        # ========================================================
        # FIND REVIEW
        # ========================================================

        review = await db["reviews"].find_one({
            "_id": review_object_id
        })


        if not review:

            raise HTTPException(
                status_code=404,
                detail="Review not found"
            )


        # ========================================================
        # SAVE ADMIN REPLY
        # ========================================================

        admin_reply = {
            "comment": reply_comment,
            "createdAt": iso_now()
        }


        await db["reviews"].update_one(
            {
                "_id": review_object_id
            },
            {
                "$set": {
                    "adminReply": admin_reply
                }
            }
        )


        # ========================================================
        # RETURN UPDATED REVIEW
        # ========================================================

        updated_review = await db["reviews"].find_one({
            "_id": review_object_id
        })

        updated_review = fix_id(updated_review)


        return {
            "success": True,
            "message": "Admin reply added successfully",
            "review": updated_review
        }


    except HTTPException:
        raise

    except Exception as e:

        print(
            "❌ Error replying to review:",
            e
        )

        raise HTTPException(
            status_code=500,
            detail=f"Failed to reply to review: {str(e)}"
        )



# ============================================================
# ADMIN - GET ALL CUSTOMER REVIEWS
# ============================================================

@app.get("/admin/reviews")
async def get_all_reviews(
    authorization: str = Header(None)
):
    try:

        # ========================================================
        # ADMIN AUTH
        # ========================================================

        if authorization != f"Bearer {ADMIN_TOKEN}":
            raise HTTPException(
                status_code=401,
                detail="Unauthorized"
            )


        # ========================================================
        # GET ALL REVIEWS
        # ========================================================

        reviews_cursor = db["reviews"].find(
            {}
        ).sort(
            "createdAt",
            -1
        )


        reviews = []


        # ========================================================
        # GET REVIEWS
        # ========================================================

        async for review in reviews_cursor:

            review = fix_id(review)

            # --------------------------------------------
            # Find product name
            # --------------------------------------------

            product_name = "Unknown Product"

            product_id = review.get("productId")

            if product_id:

                try:

                    product_object_id = ObjectId(
                        product_id
                    )

                    product = await db["products"].find_one(
                        {
                            "_id": product_object_id
                        },
                        {
                            "name": 1
                        }
                    )

                    if product:

                        product_name = product.get(
                            "name",
                            "Unknown Product"
                        )

                except Exception:
                    pass


            # --------------------------------------------
            # Add product name
            # --------------------------------------------

            review["productName"] = product_name


            reviews.append(review)


        return reviews


    except HTTPException:
        raise

    except Exception as e:

        print(
            "❌ Error loading admin reviews:",
            e
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to load reviews"
        )

# =============================
# shipment charge
# =============================
@app.get("/shipping-charge")
async def get_shipping_charge(d_pin: str, weight: int = 500, pt: str = "Pre-paid"):
    params = {
        "md": "S",
        "ss": "Delivered",
        "d_pin": d_pin,
        "o_pin": ORIGIN_PINCODE or "603109",
        "cgm": weight,
        "pt": pt
    }

    headers = {
        "Authorization": f"Token {DELHIVERY_API_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DELHIVERY_BASE_URL}/api/kinko/v1/invoice/charges/.json",
            params=params,
            headers=headers
        )

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch shipping charges")

    data = response.json()
    print("📦 Raw shipping response:", data)

    # ✅ Correct extraction from list
    try:
        amount = float(data[0].get("total_amount", 0)) if isinstance(data, list) and data else 0
    except Exception:
        amount = 0

    return {"total_amount": amount}

# =============================
# Admin: Cancel Order
# =============================
@app.put("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Find the order
    order = await db["orders"].find_one({"orderId": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    awb = order.get("awb")
    delhivery_response = None

    if awb:
        # Cancel shipment in Delhivery
        url = f"{DELHIVERY_BASE_URL}/api/p/edit"
        headers = {
            "Authorization": f"Token {DELHIVERY_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {"waybill": awb, "cancellation": "true"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                delhivery_response = resp.json()
                print("📦 Cancel Response:", delhivery_response)
        except Exception as e:
            print(f"❌ Error cancelling shipment: {e}")

    # Update DB
    await db["orders"].update_one(
        {"orderId": order_id},
        {"$set": {"status": "Cancelled", "statusTimeline.Cancelled": iso_now()}}
    )

    return {
        "message": "Order cancelled successfully",
        "orderId": order_id,
        "awb": awb,
        "delhiveryResponse": delhivery_response
    }

class ExchangeOrderValidationRequest(BaseModel):
    order_id: str

# ==========================================
# EXCHANGE: VALIDATE ORDER ELIGIBILITY
# ==========================================




@app.post("/exchange/validate-order")
async def validate_exchange_order(
    request: ExchangeOrderValidationRequest
):
    # =========================================
    # 1. Validate Order ID
    # =========================================
    order_id = str(request.order_id or "").strip()

    if not order_id:
        raise HTTPException(
            status_code=400,
            detail="Please enter your Order ID."
        )

    print(f"[EXCHANGE] Requested order ID: {order_id!r}")
    print(f"[EXCHANGE] Database: {db.name}")

    # =========================================
    # 2. Find order by string or numeric ID
    # =========================================
    order = await db["orders"].find_one(
        {"orderId": order_id}
    )

    if not order:
        try:
            numeric_id = int(order_id)

            order = await db["orders"].find_one(
                {"orderId": numeric_id}
            )

        except ValueError:
            pass

    if not order:
        print(
            f"[EXCHANGE] Order not found: {order_id!r}"
        )

        raise HTTPException(
            status_code=404,
            detail="Order not found. Please check your Order ID."
        )

    print(
        f"[EXCHANGE] Matched order ID: "
        f"{order.get('orderId')!r}"
    )

    print(
        f"[EXCHANGE] Order status: "
        f"{order.get('status')!r}"
    )

    # =========================================
    # 3. Validate AWB
    # =========================================
    awb = order.get("awb")

    if not awb or not str(awb).strip():
        print(
            f"[EXCHANGE] AWB missing for order "
            f"{order.get('orderId')!r}"
        )

        raise HTTPException(
            status_code=400,
            detail=(
                "Tracking information is not available "
                "for this order yet."
            )
        )

    awb = str(awb).strip()

    print(
        f"[EXCHANGE] Stored AWB: {awb!r}"
    )

    # =========================================
    # 4. Fetch live Delhivery tracking
    # =========================================
    try:
        courier_timeline = await fetch_delhivery_tracking(
            awb
        )

    except Exception as exc:
        print(
            f"[EXCHANGE] Tracking function exception "
            f"for AWB {awb}: "
            f"{type(exc).__name__}: {exc}"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to retrieve delivery information "
                "right now. Please try again later."
            )
        )

    print(
        "[EXCHANGE] Tracking response type:",
        type(courier_timeline).__name__
    )

    print(
        "[EXCHANGE] Tracking response:",
        repr(courier_timeline)
    )

    if not courier_timeline:
        print(
            f"[EXCHANGE] Empty tracking response "
            f"for AWB {awb}"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to retrieve delivery information "
                "right now. Please try again later."
            )
        )

    # =========================================
    # 5. Validate tracking response structure
    # =========================================
    if not isinstance(courier_timeline, list):
        print(
            "[EXCHANGE] Unexpected tracking response "
            "structure."
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "The courier tracking response could not "
                "be verified. Please contact customer support."
            )
        )

    # =========================================
    # 6. Find actual Delivered scan
    # =========================================
    delivered_scans = []

    for scan in courier_timeline:

        if not isinstance(scan, dict):
            continue

        status = str(
            scan.get("status", "")
        ).strip().lower()

        delivered_time = scan.get("time")

        if status == "delivered" and delivered_time:
            delivered_scans.append(scan)

    if not delivered_scans:
        print(
            f"[EXCHANGE] No valid Delivered scan "
            f"found for AWB {awb}"
        )

        raise HTTPException(
            status_code=400,
            detail=(
                "This order has not been confirmed as "
                "delivered by the courier."
            )
        )

    # =========================================
    # 7. Parse delivery timestamps
    # =========================================
    parsed_delivery_times = []

    for scan in delivered_scans:

        raw_time = scan.get("time")

        try:
            delivered_at = datetime.fromisoformat(
                str(raw_time)
                .strip()
                .replace("Z", "+00:00")
            )

            # Assume IST for timestamps without a timezone.
            # Confirm Delhivery's timestamp convention.
            if delivered_at.tzinfo is None:
                delivered_at = delivered_at.replace(
                    tzinfo=timezone(
                        timedelta(hours=5, minutes=30)
                    )
                )

            delivered_at = delivered_at.astimezone(
                timezone.utc
            )

            parsed_delivery_times.append(delivered_at)

        except (
            ValueError,
            TypeError,
            AttributeError
        ) as exc:

            print(
                f"[EXCHANGE] Invalid delivery timestamp "
                f"{raw_time!r} for AWB {awb}: {exc}"
            )

    if not parsed_delivery_times:
        raise HTTPException(
            status_code=503,
            detail=(
                "The courier's delivery timestamp could "
                "not be verified. Please contact customer support."
            )
        )

    # Use the latest valid Delivered timestamp.
    delivered_at = max(parsed_delivery_times)

    # =========================================
    # 8. Calculate seven-day eligibility
    # =========================================
    now = datetime.now(timezone.utc)

    age = now - delivered_at

    if age.total_seconds() < 0:
        print(
            f"[EXCHANGE] Future delivery timestamp "
            f"received for AWB {awb}: {delivered_at.isoformat()}"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "The courier returned a future delivery "
                "timestamp. Please contact customer support."
            )
        )

    if age > timedelta(days=7):
        print(
            f"[EXCHANGE] Exchange window expired. "
            f"Order={order.get('orderId')}, "
            f"Delivered={delivered_at.isoformat()}, "
            f"AgeDays={age.total_seconds() / 86400:.2f}"
        )

        raise HTTPException(
            status_code=400,
            detail=(
                "This order is outside the "
                "seven-day exchange window."
            )
        )

    print(
        f"[EXCHANGE] Order eligible. "
        f"Order={order.get('orderId')}, "
        f"DaysSinceDelivery={age.total_seconds() / 86400:.2f}"
    )

    # =========================================
    # 9. Save verified delivery timestamp
    # =========================================
    delivered_at_iso = delivered_at.isoformat()

    await db["orders"].update_one(
        {"_id": order["_id"]},
        {
            "$set": {
                "deliveryConfirmedAt": delivered_at_iso
            }
        }
    )

    # =========================================
    # 10. Prepare order items
    # =========================================
    cart_items = order.get("cartItems") or []

    if not isinstance(cart_items, list) or not cart_items:
        raise HTTPException(
            status_code=400,
            detail=(
                "No exchangeable items were found "
                "in this order."
            )
        )

    eligible_items = []

    for index, item in enumerate(cart_items):

        if not isinstance(item, dict):
            continue

        eligible_items.append({
            "item_index": index,
            "productId": item.get("productId"),
            "name": item.get("name"),
            "quantity": item.get("quantity", 1),
            "selectedSize": item.get("selectedSize"),
            "sleeveType": item.get("sleeveType"),
            "preferredHeight": item.get("preferredHeight"),
            "neckCustomization": item.get("neckCustomization"),
            "measurements": item.get("measurements"),
            "customizationNotes": item.get("customizationNotes")
        })

    if not eligible_items:
        raise HTTPException(
            status_code=400,
            detail=(
                "No exchangeable items were found "
                "in this order."
            )
        )

    # =========================================
    # 11. Return validation result
    # =========================================
    return {
        "eligible": True,
        "message": "Order is eligible for an exchange request.",
        "orderId": order.get("orderId"),
        "deliveryConfirmedAt": delivered_at_iso,
        "daysSinceDelivery": round(
            age.total_seconds() / 86400,
            2
        ),
        "items": eligible_items,
        "checkoutData": order.get("checkoutData") or {},
    }

@app.get("/exchange/product-by-name")
async def get_exchange_product_by_name(name: str):
    name = name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Product name is required."
        )

    # Case-insensitive exact match
    products = await db["products"].find(
        {
            "name": {
                "$regex": f"^{re.escape(name)}$",
                "$options": "i"
            }
        }
    ).to_list(length=2)

    if not products:
        raise HTTPException(
            status_code=404,
            detail="Product not found."
        )

    # Never guess if multiple products share the same name.
    if len(products) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "Multiple products match this name. "
                "Please contact customer support."
            )
        )

    product = fix_id(products[0])

    return {
        "id": product["id"],
        "name": product.get("name"),
        "sizes": product.get("sizes", []),
        "isSoldOut": product.get("isSoldOut", False)
    }

# ============================================================
# EXCHANGE: SUBMIT REQUEST
# ============================================================

EXCHANGE_EVIDENCE_MAX_BYTES = 25 * 1024 * 1024  # 25 MB per file

EXCHANGE_ALLOWED_EVIDENCE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/quicktime",
}

EXCHANGE_ACTIVE_STATUSES = [
    "Approved",
    "Pending Review",
    "Processing",
]


async def find_exchange_order(order_id: str):
    """
    Find an order using the same string/numeric order ID logic
    as the existing exchange validation endpoint.
    """
    order = await db["orders"].find_one({
        "orderId": order_id
    })

    if not order:
        try:
            numeric_id = int(order_id)
            order = await db["orders"].find_one({
                "orderId": numeric_id
            })
        except ValueError:
            pass

    return order


async def find_exchange_product(item: dict):
    """
    Resolve the product referenced by an order item.

    Supports newer orders with productId and legacy orders
    where productId may be missing or null.
    """
    product_id = item.get("productId")

    # Try product ID first.
    if product_id:
        try:
            from bson import ObjectId

            if ObjectId.is_valid(str(product_id)):
                product = await db["products"].find_one({
                    "_id": ObjectId(str(product_id))
                })

                if product:
                    return product

        except Exception as exc:
            print(f"Exchange product ID lookup failed: {exc}")

    # Legacy orders may not contain a product ID.
    product_name = str(item.get("name") or "").strip()

    if not product_name:
        return None

    # Exact case-insensitive name match.
    product = await db["products"].find_one({
        "name": {
            "$regex": "^" + re.escape(product_name) + "$",
            "$options": "i"
        }
    })

    return product




@app.post("/exchange/submit")
async def submit_exchange_request(request: Request):

    # ========================================================
    # 1. Read multipart form data
    # ========================================================

    form = await request.form()

    order_id = str(form.get("order_id") or "").strip()

    items_raw = form.get("items")

    if not order_id:
        raise HTTPException(
            status_code=400,
            detail="Please enter your Order ID."
        )

    if not items_raw:
        raise HTTPException(
            status_code=400,
            detail="Please select at least one item."
        )

    try:
        exchange_items = json.loads(str(items_raw))

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid exchange items data."
        )

    if not isinstance(exchange_items, list) or not exchange_items:
        raise HTTPException(
            status_code=400,
            detail="Please select at least one item."
        )

    if len(exchange_items) > 20:
        raise HTTPException(
            status_code=400,
            detail="Too many items selected."
        )

    # ========================================================
    # 2. Find order
    # ========================================================

    order = await find_exchange_order(order_id)

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Order not found. Please check your Order ID."
        )


        # ========================================================
    # ========================================================
    # EXCHANGE DELIVERY ADDRESS
    # ========================================================

    checkout_data = order.get("checkoutData") or {}
    if not isinstance(checkout_data, dict):
        checkout_data = {}

    # Read address option. Default to original address for older clients.
    same_as_original_raw = form.get("same_as_original_address")
    same_as_original_address = str(
        same_as_original_raw if same_as_original_raw is not None else "true"
    ).strip().lower() in ("true", "1", "yes")

    # Original address selected.
    if same_as_original_address:
        exchange_address = dict(checkout_data)

    # Different address selected.
    else:
        exchange_address_raw = form.get("exchange_address")
        if not exchange_address_raw:
            raise HTTPException(
                status_code=400,
                detail="Exchange delivery address is required."
            )

        try:
            exchange_address = json.loads(str(exchange_address_raw))
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="Invalid exchange delivery address."
            )

        if not isinstance(exchange_address, dict):
            raise HTTPException(
                status_code=400,
                detail="Exchange delivery address must be an object."
            )

    # Normalize both original and new address to the same schema.
    exchange_address = {
        "name": str(exchange_address.get("name") or "").strip(),
        "phone": str(exchange_address.get("phone") or "").strip(),
        "address": str(
            exchange_address.get("address")
            or exchange_address.get("addressLine1")
            or ""
        ).strip(),
        "city": str(exchange_address.get("city") or "").strip(),
        "state": str(exchange_address.get("state") or "").strip(),
        "pincode": str(exchange_address.get("pincode") or "").strip()
    }

    # Validate required address fields.
    required_address_fields = [
        "name", "phone", "address", "city", "state", "pincode"
    ]
    for field in required_address_fields:
        if not exchange_address.get(field):
            raise HTTPException(
                status_code=400,
                detail=f"Exchange delivery {field} is required."
            )

    # Validate pincode.
    if not re.fullmatch(r"\d{6}", exchange_address["pincode"]):
        raise HTTPException(
            status_code=400,
            detail="Exchange delivery pincode must contain 6 digits."
        )

    # Validate phone.
    if not re.fullmatch(r"\d{10}", exchange_address["phone"]):
        raise HTTPException(
            status_code=400,
            detail="Exchange delivery phone must contain 10 digits."
        )

    # 3. Validate delivery eligibility
    # ========================================================

    validation = await validate_exchange_order(
        ExchangeOrderValidationRequest(order_id=order_id)
    )

    if not validation or not validation.get("eligible"):
        raise HTTPException(
            status_code=400,
            detail="This order is not eligible for an exchange."
        )

    # ========================================================
    # 4. Get order items
    # ========================================================

    cart_items = order.get("cartItems") or []

    if not isinstance(cart_items, list):
        raise HTTPException(
            status_code=400,
            detail="Invalid order items."
        )

    order_items_by_index = {
        index: item
        for index, item in enumerate(cart_items)
    }

    # ========================================================
    # 5. Validate selected items
    # ========================================================

    processed_items = []

    selected_indices = set()

    has_size_exchange = False

    total_evidence_bytes = 0

    for position, exchange_item in enumerate(exchange_items):

        if not isinstance(exchange_item, dict):
            raise HTTPException(
                status_code=400,
                detail="Invalid exchange item data."
            )

        # ----------------------------------------------------
        # Item index
        # ----------------------------------------------------

        try:
            item_index = int(exchange_item.get("item_index"))

        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="Invalid order item."
            )

        if item_index < 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid order item."
            )

        if item_index in selected_indices:
            raise HTTPException(
                status_code=400,
                detail="The same item cannot be selected twice."
            )

        selected_indices.add(item_index)

        if item_index not in order_items_by_index:
            raise HTTPException(
                status_code=400,
                detail="The selected item was not found in this order."
            )

        item = order_items_by_index[item_index]

        if not isinstance(item, dict):
            raise HTTPException(
                status_code=400,
                detail="The selected order item is invalid."
            )

        # ----------------------------------------------------
        # Reason
        # ----------------------------------------------------

        reason = str(
            exchange_item.get("reason") or ""
        ).strip().lower()

        if reason not in {
            "size_issue",
            "defective_product"
        }:
            raise HTTPException(
                status_code=400,
                detail="Invalid exchange reason."
            )

        # ----------------------------------------------------
        # Prevent duplicate active exchange requests
        # ----------------------------------------------------

        existing_request = await db["exchange_requests"].find_one({
            "order_id": order.get("orderId"),
            "item_index": item_index,
            "status": {
                "$in": EXCHANGE_ACTIVE_STATUSES
            }
        })

        if existing_request:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"An active exchange request already exists "
                    f"for item {item_index + 1}."
                )
            )

        # ----------------------------------------------------
        # Item-specific values
        # ----------------------------------------------------

        selected_replacement_size = None

        evidence_urls = []

        item_status = None

        # ====================================================
        # 6. SIZE EXCHANGE
        # ====================================================

        if reason == "size_issue":

            replacement_size = str(
                exchange_item.get("replacement_size") or ""
            ).strip()

            if not replacement_size:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Please select a replacement size "
                        f"for item {item_index + 1}."
                    )
                )

            current_size = str(
                item.get("selectedSize") or ""
            ).strip()

            if replacement_size.lower() == current_size.lower():
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Please select a different size "
                        f"for item {item_index + 1}."
                    )
                )

            # ------------------------------------------------
            # Find original product
            # ------------------------------------------------

            product = await find_exchange_product(item)

            if not product:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Could not identify the product "
                        f"for item {item_index + 1}."
                    )
                )

            if product.get("isSoldOut") is True:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Product for item {item_index + 1} "
                        f"is currently sold out."
                    )
                )

            # ------------------------------------------------
            # Validate replacement size
            # ------------------------------------------------

            product_sizes = product.get("sizes") or []

            matching_size = None

            for size in product_sizes:

                if not isinstance(size, dict):
                    continue

                if (
                    str(size.get("label", "")).strip().lower()
                    == replacement_size.lower()
                ):
                    matching_size = size
                    break

            if not matching_size:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"The selected size is unavailable "
                        f"for item {item_index + 1}."
                    )
                )

            if matching_size.get("available") is not True:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"The selected size is currently unavailable "
                        f"for item {item_index + 1}."
                    )
                )

            selected_replacement_size = replacement_size

            item_status = "Payment Pending"

            has_size_exchange = True

        # ====================================================
        # 7. DEFECTIVE PRODUCT
        # ====================================================

        else:

            # Frontend sends evidence_0, evidence_1, etc.
            # Position corresponds to the item in the submitted
            # JSON array, NOT the original order item index.

            evidence_field_name = f"evidence_{position}"

            uploaded_file = form.get(evidence_field_name)

            uploaded_files = []

            if (
                uploaded_file is not None
                and hasattr(uploaded_file, "filename")
                and hasattr(uploaded_file, "read")
                and uploaded_file.filename
            ):
                uploaded_files.append(uploaded_file)

            if not uploaded_files:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Please upload evidence "
                        f"for item {item_index + 1}."
                    )
                )

            if len(uploaded_files) > 5:
                raise HTTPException(
                    status_code=400,
                    detail="Maximum 5 evidence files per item."
                )

            # ------------------------------------------------
            # Upload evidence
            # ------------------------------------------------

            for file in uploaded_files:

                content_type = (
                    file.content_type or ""
                ).lower()

                if content_type not in EXCHANGE_ALLOWED_EVIDENCE_TYPES:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Unsupported evidence format. "
                            "Use JPG, PNG, WEBP, MP4, or MOV."
                        )
                    )

                file_bytes = await file.read()

                if not file_bytes:
                    raise HTTPException(
                        status_code=400,
                        detail=f"The file {file.filename} is empty."
                    )

                if len(file_bytes) > EXCHANGE_EVIDENCE_MAX_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"{file.filename} exceeds "
                            "the 25 MB per-file limit."
                        )
                    )

                total_evidence_bytes += len(file_bytes)

                if total_evidence_bytes > 50 * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "Combined evidence cannot exceed 50 MB."
                        )
                    )

                extension_by_type = {
                    "image/jpeg": ".jpg",
                    "image/png": ".png",
                    "image/webp": ".webp",
                    "video/mp4": ".mp4",
                    "video/quicktime": ".mov",
                }

                extension = extension_by_type[content_type]

                evidence_key = (
                    f"exchange-evidence/"
                    f"{uuid.uuid4().hex}{extension}"
                )

                try:

                    upload_exchange_evidence_to_r2(
                        file_bytes,
                        evidence_key,
                        content_type
                    )

                except Exception as exc:

                    print(
                        f"Exchange evidence upload failed: {exc}"
                    )

                    raise HTTPException(
                        status_code=502,
                        detail=(
                            "Unable to upload evidence right now. "
                            "Please try again."
                        )
                    )

                if not R2_BASE:
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            "Evidence storage is not configured correctly."
                        )
                    )

                evidence_urls.append(
                    f"{R2_BASE.rstrip('/')}/{evidence_key}"
                )

            item_status = "Pending Review"

        # ====================================================
        # 8. Add item to grouped request
        # ====================================================

        processed_items.append({

            "item_index": item_index,

            "productId": item.get("productId"),

            "productName": item.get("name"),

            "quantity": item.get("quantity", 1),

            "originalSize": item.get("selectedSize"),

            "replacementSize": selected_replacement_size,

            "reason": reason,

            "status": item_status,

            "evidence": evidence_urls,

            "adminNotes": None,

            "resolution": None,

        })

    # ========================================================
    # 9. Determine grouped status
    # ========================================================

    if has_size_exchange:

        request_status = "Payment Pending"

        payment_status = "Pending"

        message = (
            "Your exchange request has been created. "
            "Please complete the exchange payment."
        )

    else:

        request_status = "Pending Review"

        payment_status = None

        message = (
            "Your exchange request has been submitted "
            "for admin review."
        )

    # ========================================================
    # 10. Create grouped request
    # ========================================================

    request_id = (
        f"EX-{uuid.uuid4().hex[:12].upper()}"
    )

    now = datetime.now(timezone.utc).isoformat()

    exchange_document = {

        "requestId": request_id,

        "order_id": order.get("orderId"),

        "order_mongo_id": str(order.get("_id")),

        "exchangeAddress": exchange_address,

# Address selection
        "sameAsOriginalAddress": same_as_original_address,

        # All selected dresses are stored together.
        "items": processed_items,

        # Group status.
        "status": request_status,

        # Payment fields.
        "paymentStatus": payment_status,

        "paymentAmount": None,

        "razorpayOrderId": None,

        "razorpayPaymentId": None,

        "razorpaySignature": None,

        "paymentVerifiedAt": None,

        "createdAt": now,

        "updatedAt": now,

        "deliveryConfirmedAt": validation.get(
            "deliveryConfirmedAt"
        ),

        "adminNotes": None,

        "resolution": None,

    }

    # ========================================================
    # 11. Insert grouped request
    # ========================================================

    await db["exchange_requests"].insert_one(
        exchange_document
    )

    # ========================================================
    # 12. Return grouped response
    # ========================================================

    return {
        "success": True,
        "message": message,
        "requestId": request_id,
        "status": request_status,
        "items": processed_items,
    }





# ============================================================
# EXCHANGE: SUBMIT REQUEST
# Place below validate_exchange_order() in main.py
# ============================================================

EXCHANGE_ACTIVE_STATUSES = [
    "Approved",
    "Pending Review",
    "Processing",
]

EXCHANGE_MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB per file
EXCHANGE_MAX_TOTAL_SIZE = 50 * 1024 * 1024  # 50 MB total

EXCHANGE_ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}

# ============================================================
# EXCHANGE CONFIGURATION
# ============================================================

EXCHANGE_ADMIN_STATUSES = {
    "Pending Review",
    "Approved",
    "Processing",
    "Completed",
    "Rejected"
}


# @app.post("/exchange/submit")
# async def submit_exchange_request(
#     order_id: str = Form(...),
#     item_index: int = Form(...),
#     reason: str = Form(...),
#     replacement_size: Optional[str] = Form(None),
#     evidence: Optional[List[UploadFile]] = File(None),
# ):
#     order_id = order_id.strip()
#     reason = reason.strip().lower()

#     if not order_id:
#         raise HTTPException(400, "Please enter your Order ID.")

#     if reason not in {"size_issue", "defective_product"}:
#         raise HTTPException(400, "Invalid exchange reason.")

#     if item_index < 0:
#         raise HTTPException(400, "Invalid order item.")

#     # 1. Find the order using the same ID logic as validation.
#     order = await db["orders"].find_one({"orderId": order_id})

#     if not order:
#         try:
#             order = await db["orders"].find_one({
#                 "orderId": int(order_id)
#             })
#         except ValueError:
#             pass

#     if not order:
#         raise HTTPException(
#             status_code=404,
#             detail="Order not found. Please check your Order ID."
#         )

#     # 2. Recheck live Delhivery delivery and the 7-day window.
#     # This invokes your existing validation function.
#     validation = await validate_exchange_order(
#         ExchangeOrderValidationRequest(order_id=order_id)
#     )

#     if not validation.get("eligible"):
#         raise HTTPException(
#             status_code=400,
#             detail="This order is not eligible for an exchange."
#         )

#     # 3. Validate the selected item.
#     cart_items = order.get("cartItems") or []

#     if item_index >= len(cart_items):
#         raise HTTPException(
#             status_code=400,
#             detail="Selected item was not found in this order."
#         )

#     item = cart_items[item_index]

#     if not isinstance(item, dict):
#         raise HTTPException(400, "Invalid order item.")

#     # 4. Prevent duplicate active requests for this item.
#     existing = await db["exchange_requests"].find_one({
#         "order_id": order.get("orderId"),
#         "item_index": item_index,
#         "status": {"$in": EXCHANGE_ACTIVE_STATUSES},
#     })

#     if existing:
#         raise HTTPException(
#             status_code=409,
#             detail="An active exchange request already exists for this item."
#         )

#     replacement = None
#     evidence_keys = []

#     # 5. SIZE EXCHANGE
#     if reason == "size_issue":
#         replacement = (replacement_size or "").strip()

#         if not replacement:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Please select a replacement size."
#             )

#         current_size = str(item.get("selectedSize") or "").strip()

#         if replacement.casefold() == current_size.casefold():
#             raise HTTPException(
#                 status_code=400,
#                 detail="Choose a size different from your current size."
#             )

#         # Resolve product by ID first, then exact name for legacy orders.
#         product = None
#         product_id = item.get("productId")

#         if product_id:
#             try:
#                 from bson import ObjectId

#                 if ObjectId.is_valid(str(product_id)):
#                     product = await db["products"].find_one({
#                         "_id": ObjectId(str(product_id))
#                     })
#             except Exception as exc:
#                 print("[EXCHANGE] Product ID lookup error:", exc)

#         if not product:
#             product_name = str(item.get("name") or "").strip()

#             if product_name:
#                 product = await db["products"].find_one({
#                     "name": {
#                         "$regex": "^" + re.escape(product_name) + "$",
#                         "$options": "i",
#                     }
#                 })

#         if not product:
#             raise HTTPException(
#                 status_code=409,
#                 detail="Unable to identify the original product safely."
#             )

#         # Your actual Product model uses sizes: List[str].
#         available_sizes = product.get("sizes") or []

#         if not any(
#             isinstance(size, str)
#             and size.strip().casefold() == replacement.casefold()
#             for size in available_sizes
#         ):
#             raise HTTPException(
#                 status_code=400,
#                 detail="That size is not listed for this product."
#             )

#         if product.get("isSoldOut") is True:
#             raise HTTPException(
#                 status_code=400,
#                 detail="This product is currently sold out."
#             )

#         if product.get("stock") is not None:
#             try:
#                 if int(product["stock"]) <= 0:
#                     raise HTTPException(
#                         status_code=400,
#                         detail="This product is currently out of stock."
#                     )
#             except (ValueError, TypeError):
#                 raise HTTPException(
#                     status_code=409,
#                     detail="Product stock information is invalid."
#                 )

#         # NOTE: Your schema does not track stock per size.
#         # This confirms the size is listed and the product is not sold
#         # out, but cannot guarantee that this particular size is in stock.

#         status = "Payment Pending"

#     # 6. DEFECTIVE PRODUCT
#     else:
#         files = [
#             file for file in (evidence or [])
#             if file and file.filename
#         ]

#         if not files:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Upload at least one photo or video of the defect."
#             )

#         if len(files) > 5:
#             raise HTTPException(
#                 status_code=400,
#                 detail="You can upload a maximum of 5 evidence files."
#             )

#         # Read and validate all files before uploading any of them.
#         prepared_files = []
#         total_size = 0

#         for file in files:
#             content_type = (file.content_type or "").lower()

#             if content_type not in EXCHANGE_ALLOWED_TYPES:
#                 raise HTTPException(
#                     status_code=400,
#                     detail="Use JPG, PNG, WEBP, MP4, or MOV evidence files."
#                 )

#             data = await file.read()

#             if not data:
#                 raise HTTPException(
#                     status_code=400,
#                     detail=f"{file.filename} is empty."
#                 )

#             if len(data) > EXCHANGE_MAX_FILE_SIZE:
#                 raise HTTPException(
#                     status_code=413,
#                     detail=f"{file.filename} exceeds 25 MB."
#                 )

#             total_size += len(data)

#             prepared_files.append(
#                 (data, content_type, EXCHANGE_ALLOWED_TYPES[content_type])
#             )

#         if total_size > EXCHANGE_MAX_TOTAL_SIZE:
#             raise HTTPException(
#                 status_code=413,
#                 detail="Combined evidence cannot exceed 50 MB."
#             )

#         # Upload using your existing R2 helper.
#         # Store object keys because upload_to_r2() does not return URLs.
#         for data, content_type, extension in prepared_files:
#             object_key = (
#                 f"exchange-evidence/{uuid.uuid4().hex}{extension}"
#             )

#             try:
#                 upload_to_r2(data, object_key, content_type)
#                 evidence_keys.append(object_key)
#             except Exception as exc:
#                 print("[EXCHANGE] R2 upload failed:", exc)

#                 raise HTTPException(
#                     status_code=502,
#                     detail="Evidence upload failed. Please try again."
#                 )

#         status = "Pending Review"

#     # 7. Create a separate exchange record.
#     now = datetime.now(timezone.utc).isoformat()
#     request_id = f"EX-{uuid.uuid4().hex[:12].upper()}"

#     exchange_record = {
#         "requestId": request_id,
#         "order_id": order.get("orderId"),
#         "order_mongo_id": str(order["_id"]),
#         "item_index": item_index,
#         "productId": item.get("productId"),
#         "productName": item.get("name"),
#         "quantity": item.get("quantity", 1),
#         "originalSize": item.get("selectedSize"),
#         "replacementSize": replacement,
#         "reason": reason,
#         "status": status,

#         # Exchange payment details
#         "paymentStatus": (
#             "Pending" if reason == "size_issue" else "Not Required"
#         ),
#         "paymentAmount": 0,
#         "razorpayOrderId": None,
#         "razorpayPaymentId": None,
#         "paymentVerifiedAt": None,

#         "evidenceKeys": evidence_keys,
#         "deliveryConfirmedAt": validation.get("deliveryConfirmedAt"),
#         "createdAt": now,
#         "updatedAt": now,
#         "adminNotes": None,
#         "resolution": None,
#     }

#     await db["exchange_requests"].insert_one(exchange_record)

#     return {
#         "success": True,
#         "message": (
#             "Your size exchange request has been approved."
#             "Please complete the exchange shipping payment."
#             if reason == "size_issue"
#             else "Your defective-product request has been submitted for review."
#         ),
#         "requestId": request_id,
#         "status": status,
#     }


# ============================================================
# ADMIN: ACTIVE EXCHANGE COUNT
# ============================================================

@app.get("/admin/exchanges/count")
async def get_admin_exchange_count(
    authorization: str = Header(None)
):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    active_statuses = [
        "Pending Review",
        "Approved",
        "Processing"
    ]

    count = await db["exchange_requests"].count_documents({
        "status": {"$in": active_statuses}
    })

    return {"count": count}



# ============================================================
# ADMIN: GET EXCHANGE REQUESTS
# ============================================================


@app.get("/admin/exchanges")
async def get_admin_exchanges(
    authorization: str = Header(None)
):

    # ========================================================
    # ADMIN AUTHENTICATION
    # ========================================================

    if authorization != f"Bearer {ADMIN_TOKEN}":

        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    # ========================================================
    # HELPER: CONVERT MONGODB VALUES TO JSON-SAFE VALUES
    # ========================================================

    def serialize_mongodb_value(value):

        from bson import ObjectId

        if isinstance(value, ObjectId):

            return str(value)

        if isinstance(value, (datetime, date)):

            return value.isoformat()

        if isinstance(value, dict):

            return {
                str(key): serialize_mongodb_value(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple)):

            return [
                serialize_mongodb_value(item)
                for item in value
            ]

        return value

    # ========================================================
    # RETRIEVE EXCHANGE REQUESTS
    # ========================================================

    exchanges = await db["exchange_requests"].find(
        {}
    ).sort(
        "createdAt", -1
    ).to_list(
        length=100
    )

    result = []

    # ========================================================
    # PROCESS EACH EXCHANGE
    # ========================================================

    for exchange in exchanges:

        # Hide size-exchange requests until payment is verified.
# The request remains in MongoDB so the customer can retry payment.

        exchange_items = exchange.get("items") or []

        has_size_exchange = any(
            isinstance(item, dict)
            and item.get("reason") == "size_issue"
            for item in exchange_items
        )

        if (
            has_size_exchange
            and exchange.get("paymentStatus") != "Paid"
        ):
            continue

        # ====================================================
        # FIND ORIGINAL ORDER
        # ====================================================

        order = None

        order_mongo_id = exchange.get(
            "order_mongo_id"
        )

        # ----------------------------------------------------
        # FIND ORDER USING MONGODB OBJECT ID
        # ----------------------------------------------------

        if order_mongo_id:

            try:

                from bson import ObjectId

                if ObjectId.is_valid(
                    str(order_mongo_id)
                ):

                    order = await db["orders"].find_one({
                        "_id": ObjectId(
                            str(order_mongo_id)
                        )
                    })

            except Exception as exc:

                print(
                    "[EXCHANGE] Order MongoDB ID lookup error:",
                    exc
                )

        # ----------------------------------------------------
        # FALLBACK: FIND ORDER USING ORDER ID
        # ----------------------------------------------------

        if not order:

            order_id = exchange.get(
                "order_id"
            )

            if order_id:

                order = await db["orders"].find_one({
                    "orderId": order_id
                })

            # ------------------------------------------------
            # FALLBACK: ORDER ID STORED AS INTEGER
            # ------------------------------------------------

            if not order and order_id:

                try:

                    order = await db["orders"].find_one({
                        "orderId": int(order_id)
                    })

                except (ValueError, TypeError):

                    pass

        # ====================================================
        # CUSTOMER INFORMATION
        # ====================================================

        customer_name = None

        customer_email = None

        customer_phone = None

        customer_id = None

        shipping_address = None

        billing_address = None

        checkout_data = {}

        if order:

            # ------------------------------------------------
            # GET CHECKOUT DATA
            # ------------------------------------------------

            checkout_data = order.get(
                "checkoutData"
            ) or {}

            if not isinstance(checkout_data, dict):

                checkout_data = {}

            # ------------------------------------------------
            # CUSTOMER NAME
            # ------------------------------------------------

            customer_name = (
                checkout_data.get("name")
                or order.get("customerName")
                or order.get("name")
                or order.get("fullName")
            )

            # ------------------------------------------------
            # CUSTOMER EMAIL
            # ------------------------------------------------

            customer_email = (
                checkout_data.get("email")
                or order.get("email")
                or order.get("customerEmail")
            )

            # ------------------------------------------------
            # CUSTOMER PHONE
            # ------------------------------------------------

            customer_phone = (
                checkout_data.get("phone")
                or order.get("phone")
                or order.get("mobile")
                or order.get("customerPhone")
            )

            # ------------------------------------------------
            # CUSTOMER ID
            # ------------------------------------------------

            customer_id = order.get(
                "userId"
            )

            # ------------------------------------------------
            # SHIPPING ADDRESS
            # ------------------------------------------------

            shipping_address = (
                checkout_data.get("address")
                or order.get("shippingAddress")
                or order.get("address")
            )

            # ------------------------------------------------
            # BILLING ADDRESS
            # ------------------------------------------------

            billing_address = (
                order.get("billingAddress")
                or order.get("billing_address")
            )

            # ------------------------------------------------
            # BUILD ADDRESS FROM CHECKOUT DATA IF NEEDED
            # ------------------------------------------------

            if not shipping_address:

                address_parts = [

                    checkout_data.get("addressLine1"),

                    checkout_data.get("addressLine2"),

                    checkout_data.get("city"),

                    checkout_data.get("state"),

                    checkout_data.get("pincode")

                ]

                address_parts = [

                    str(part).strip()

                    for part in address_parts

                    if part and str(part).strip()

                ]

                if address_parts:

                    shipping_address = ", ".join(
                        address_parts
                    )

        # ====================================================
        # CUSTOMER DETAILS
        # ====================================================

        customer_details = {

            "id": customer_id,

            "customerId": customer_id,

            "name": customer_name,

            "email": customer_email,

            "phone": customer_phone,

            "shippingAddress": shipping_address,

            "billingAddress": billing_address

        }

        # ====================================================
        # ORIGINAL ORDER DETAILS
        # ====================================================

        order_details = None

        if order:

            order_details = serialize_mongodb_value(
                order
            )

        # ====================================================
# EXCHANGE ITEM DETAILS
# ====================================================

        exchange_items = exchange.get("items") or []

# Support older exchange records that stored one item at root level
        if not exchange_items:
            exchange_items = [{
                "item_index": exchange.get("item_index"),
                "productId": exchange.get("productId"),
            "productName": exchange.get("productName"),
            "quantity": exchange.get("quantity", 1),
            "originalSize": exchange.get("originalSize"),
            "replacementSize": exchange.get("replacementSize"),
            "reason": exchange.get("reason"),
            "status": exchange.get("status"),
            "evidence": exchange.get("evidence", [])
        }]

# Ensure items is always an array of actual item objects
        exchange_items = [
            item for item in exchange_items
            if isinstance(item, dict)
        ]

# First item for backward compatibility
        exchange_item = exchange_items[0] if exchange_items else {}
        # ====================================================
        # EXCHANGE RECORD
        # ====================================================

        exchange_result = {

            # ------------------------------------------------
            # EXCHANGE IDENTIFICATION
            # ------------------------------------------------

            "requestId": exchange.get(
                "requestId"
            ),

            "order_id": exchange.get(
                "order_id"
            ),

            "orderId": (

                order.get("orderId")

                if order

                else exchange.get("order_id")

            ),



            "order_mongo_id": exchange.get(
                "order_mongo_id"
            ),

            # ------------------------------------------------
            # EXCHANGE ITEM
            # ------------------------------------------------

            "item_index": exchange.get(
                "item_index"
            ),

            "productId": exchange.get(
                "productId"
            ),

            "productName": exchange.get(
                "productName"
            ),

            "quantity": exchange.get(
                "quantity",
                1
            ),

            "originalSize": exchange.get(
                "originalSize"
            ),

            "replacementSize": exchange.get(
                "replacementSize"
            ),

            "reason": exchange.get(
                "reason"
            ),

            "paymentStatus": exchange.get("paymentStatus"),
            "paymentAmount": exchange.get("paymentAmount"),
            "razorpayOrderId": exchange.get("razorpayOrderId"),
            "razorpayPaymentId": exchange.get("razorpayPaymentId"),

            # ====================================================
# EXCHANGE ADDRESS
# ====================================================

            "exchangeAddress": exchange.get("exchangeAddress"),

            "sameAsOriginalAddress": exchange.get(
                "sameAsOriginalAddress",
                True
            ),

            # ------------------------------------------------
            # EXCHANGE STATUS
            # ------------------------------------------------

            "status": exchange.get(
                "status"
            ),

            "adminNotes": exchange.get(
                "adminNotes"
            ),

            "resolution": exchange.get(
                "resolution"
            ),

            # ------------------------------------------------
            # EVIDENCE
            # ------------------------------------------------

            "evidenceKeys": exchange.get(
                "evidenceKeys",
                exchange.get("evidence", [])
            ),

            # ------------------------------------------------
            # DELIVERY
            # ------------------------------------------------

            "deliveryConfirmedAt": exchange.get(
                "deliveryConfirmedAt"
            ),

            # ------------------------------------------------
            # EXCHANGE TIMESTAMPS
            # ------------------------------------------------

            "createdAt": exchange.get(
                "createdAt"
            ),

            "updatedAt": exchange.get(
                "updatedAt"
            ),

            # ------------------------------------------------
            # CUSTOMER DETAILS
            # ------------------------------------------------

            "customer": customer_details,

            # ------------------------------------------------
            # CUSTOMER DETAILS - ANGULAR COMPATIBILITY
            # ------------------------------------------------

            "customerId": customer_id,

            "customerName": customer_name,

            "customerEmail": customer_email,

            "customerPhone": customer_phone,

            "shippingAddress": shipping_address,

            "billingAddress": billing_address,

            # ------------------------------------------------
            # ORIGINAL ORDER DETAILS
            # ------------------------------------------------

            "orderDetails": order_details,

            # ------------------------------------------------
            # EXCHANGE ITEM DETAILS
            # ------------------------------------------------

            "exchangeItem": exchange_item,

            "items": exchange_items,

            # Angular compatibility
            "exchangeItems": exchange_items

        }

        # ====================================================
        # SERIALIZE COMPLETE RESPONSE
        # ====================================================

        exchange_result = serialize_mongodb_value(
            exchange_result
        )

        # ====================================================
        # ADD EXCHANGE TO RESULT
        # ====================================================

        result.append(
            exchange_result
        )

    # ========================================================
    # RETURN ADMIN EXCHANGE RESPONSE
    # ========================================================

    return {

        "success": True,

        "count": len(result),

        "exchanges": result

    }


# ============================================================
# ADMIN: UPDATE staus of the order
# ============================================================

@app.patch("/admin/exchanges/{request_id}/complete")
async def complete_exchange(
    request_id: str,
    authorization: str = Header(None)
):
    # Admin authentication
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    # Find the exchange request
    exchange = await db["exchange_requests"].find_one({
        "requestId": request_id
    })

    if not exchange:
        raise HTTPException(
            status_code=404,
            detail="Exchange request not found"
        )

    current_status = str(
        exchange.get("status") or ""
    ).strip().lower()

    # Prevent duplicate completion
    if current_status == "completed":
        return {
            "success": True,
            "message": "Exchange is already completed"
        }

    # Update exchange status
    now = datetime.now(timezone.utc)

    result = await db["exchange_requests"].update_one(
        {
            "_id": exchange["_id"],
            "status": exchange.get("status")
        },
        {
            "$set": {
                "status": "Completed",
                "completedAt": now,
                "updatedAt": now
            }
        }
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Exchange status changed. Please refresh and try again."
        )

    return {
        "success": True,
        "message": "Exchange marked as completed",
        "requestId": request_id,
        "status": "Completed",
        "completedAt": now.isoformat()
    }

# ============================================================
# ADMIN: UPDATE EXCHANGE STATUS
# ============================================================

class ExchangeStatusUpdateRequest(BaseModel):
    status: str
    adminNotes: Optional[str] = None

@app.patch("/admin/exchanges/{request_id}/status")
async def update_exchange_status(
    request_id: str,
    request: ExchangeStatusUpdateRequest,
    authorization: str = Header(None)
):

    # Admin authentication
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    # Validate status
    new_status = request.status.strip()

    if new_status not in EXCHANGE_ADMIN_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Invalid exchange status."
        )

    # Find exchange request
    exchange = await db["exchange_requests"].find_one({
        "requestId": request_id
    })

    if not exchange:
        raise HTTPException(
            status_code=404,
            detail="Exchange request not found."
        )


    # ========================================================
# PREVENT APPROVAL / FULFILLMENT BEFORE REQUIRED PAYMENT
# ========================================================

    items = exchange.get("items") or []

    has_size_exchange = any(
        isinstance(item, dict)
        and item.get("reason") == "size_issue"
        for item in items
    )

# Size exchanges must be paid before admin approval.
    if has_size_exchange:

        if new_status in {
            "Approved",
            "Processing",
            "Packed",
            "Shipped",
            "Delivered",
            "Completed"
        } and exchange.get("paymentStatus") != "Paid":

            raise HTTPException(
                status_code=409,
                detail=(
                    "This size exchange cannot be approved or processed "
                    "until its payment has been verified."
                )
            )


    # Preserve existing notes when no new notes are supplied
    existing_notes = exchange.get("adminNotes")

    if request.adminNotes is None:
        admin_notes = existing_notes
    else:
        admin_notes = request.adminNotes.strip() or None

    # Update exchange request only
    now = datetime.now(timezone.utc).isoformat()

    update_result = await db["exchange_requests"].update_one(
        {
            "_id": exchange["_id"]
        },
        {
            "$set": {
                "status": new_status,
                "adminNotes": admin_notes,
                "updatedAt": now
            }
        }
    )

    if update_result.matched_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Exchange request not found."
        )

    # Retrieve updated record
    updated_exchange = await db["exchange_requests"].find_one({
        "_id": exchange["_id"]
    })

    return {

        "success": True,

        "message": "Exchange status updated successfully.",

        "requestId": updated_exchange.get("requestId"),

        "status": updated_exchange.get("status"),

        "adminNotes": updated_exchange.get("adminNotes"),

        "updatedAt": updated_exchange.get("updatedAt")

    }



async def fetch_exchange_shipping_charge(
    origin_pincode: str,
    destination_pincode: str,
    weight: int = 500,
    pt: str = "Pre-paid"
):
    """Fetch Delhivery shipping charge specifically for exchange shipping."""

    origin_pincode = str(origin_pincode).strip()
    destination_pincode = str(destination_pincode).strip()

    # Validate pincodes
    if not origin_pincode.isdigit() or len(origin_pincode) != 6:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid origin pincode: {origin_pincode}"
        )

    if not destination_pincode.isdigit() or len(destination_pincode) != 6:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid destination pincode: {destination_pincode}"
        )

    if weight <= 0:
        raise HTTPException(
            status_code=400,
            detail="Shipment weight must be greater than zero."
        )

    params = {
        "md": "E",
        "ss": "Delivered",
        "d_pin": destination_pincode,
        "o_pin": origin_pincode,
        "cgm": weight,
        "pt": pt
    }

    headers = {
        "Authorization": f"Token {DELHIVERY_API_TOKEN}",
        "Content-Type": "application/json"
    }

    url = f"{DELHIVERY_BASE_URL.rstrip('/')}/api/kinko/v1/invoice/charges/.json"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:

            response = await client.get(
                url,
                params=params,
                headers=headers
            )

        # Log the actual Delhivery response for debugging
        print("========== DELHIVERY EXCHANGE SHIPPING ==========")
        print("Origin:", origin_pincode)
        print("Destination:", destination_pincode)
        print("Weight:", weight)
        print("Status Code:", response.status_code)
        print("Response:", response.text)
        print("================================================")

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Delhivery shipping charge API failed",
                    "status_code": response.status_code,
                    "response": response.text[:1000]
                }
            )

        try:
            data = response.json()
        except ValueError:
            raise HTTPException(
                status_code=502,
                detail="Delhivery returned an invalid JSON response."
            )

        # Delhivery may return a list of charge records
        if isinstance(data, list):

            if not data:
                raise HTTPException(
                    status_code=502,
                    detail="Delhivery returned an empty shipping charge response."
                )

            charge_data = data[0]

        # Or a dictionary
        elif isinstance(data, dict):

            charge_data = data

        else:
            raise HTTPException(
                status_code=502,
                detail="Unexpected Delhivery shipping charge response."
            )

        total_amount = charge_data.get("total_amount")

        if total_amount is None:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Delhivery response does not contain total_amount",
                    "response": data
                }
            )

        try:
            total_amount = float(total_amount)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=502,
                detail="Invalid shipping charge returned by Delhivery."
            )

        if total_amount < 0:
            raise HTTPException(
                status_code=502,
                detail="Delhivery returned a negative shipping charge."
            )

        return total_amount

    except HTTPException:
        raise

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Delhivery shipping charge request timed out."
        )

    except httpx.RequestError as e:
        print("Delhivery request error:", str(e))

        raise HTTPException(
            status_code=502,
            detail="Unable to connect to Delhivery shipping charge API."
        )

    except Exception as e:
        print("Unexpected Delhivery shipping error:", str(e))

        raise HTTPException(
            status_code=500,
            detail="Unexpected error while calculating exchange shipping."
        )





async def calculate_exchange_shipping(
    customer_pincode: str,
    weight: int = 500
):
    # Use the SAME normal shipping function
    shipping_charge = await fetch_shipping_charge(
        destination_pincode=customer_pincode,
        weight=weight
    )

    # Simply double the normal delivery charge
    total_shipping = round(float(shipping_charge) * 2, 2)

    return {
        "returnShipping": float(shipping_charge),
        "replacementShipping": float(shipping_charge),
        "totalShipping": total_shipping
    }


# ============================================================
# EXCHANGE: CREATE RAZORPAY PAYMENT
# ============================================================


@app.post("/exchange/create-payment")
async def create_exchange_payment(request: Request):

    try:

        # ========================================================
        # 1. READ REQUEST
        # ========================================================

        data = await request.json()

        request_id = str(
            data.get("requestId") or ""
        ).strip()

        if not request_id:

            raise HTTPException(
                status_code=400,
                detail="Exchange request ID is required."
            )

        # ========================================================
        # 2. FIND EXCHANGE REQUEST
        # ========================================================

        exchange = await db["exchange_requests"].find_one({
            "requestId": request_id
        })

        if not exchange:

            raise HTTPException(
                status_code=404,
                detail="Exchange request not found."
            )

        items = exchange.get("items") or []

        if not isinstance(items, list) or not items:

            raise HTTPException(
                status_code=400,
                detail="No exchange items found."
            )

        # ========================================================
        # 3. IDENTIFY SIZE EXCHANGE ITEMS
        # ========================================================

        size_items = [
            item
            for item in items
            if isinstance(item, dict)
            and item.get("reason") == "size_issue"
        ]

        if not size_items:

            raise HTTPException(
                status_code=400,
                detail="Payment is required only for size exchanges."
            )

        size_exchange_count = len(size_items)

        # ========================================================
        # 4. VALIDATE EXCHANGE STATUS
        # ========================================================

        if exchange.get("status") != "Payment Pending":

            raise HTTPException(
                status_code=409,
                detail="This exchange is not awaiting payment."
            )

        if exchange.get("paymentStatus") == "Paid":

            raise HTTPException(
                status_code=409,
                detail="Payment has already been completed."
            )

        # ========================================================
        # 5. FIND ORIGINAL ORDER
        # ========================================================

        order_id = exchange.get("order_id")

        if not order_id:

            raise HTTPException(
                status_code=400,
                detail="Original order ID is missing."
            )

        order = await db["orders"].find_one({
            "orderId": order_id
        })

        if not order:

            raise HTTPException(
                status_code=404,
                detail="Original order not found."
            )

        # ========================================================
        # 6. GET ORIGINAL ORDER ADDRESS
        # ========================================================

        checkout_data = order.get("checkoutData") or {}

        if not isinstance(checkout_data, dict):

            checkout_data = {}

        # ========================================================
        # 7. GET EXCHANGE DELIVERY ADDRESS
        #
        # New exchange requests:
        #     Use exchangeAddress.
        #
        # Older exchange requests:
        #     Fall back to original checkoutData.
        # ========================================================

        exchange_address = exchange.get(
            "exchangeAddress"
        ) or {}

        if not isinstance(exchange_address, dict):

            exchange_address = {}

        # ========================================================
        # 8. DETERMINE DELIVERY PINCODE
        #
        # Priority:
        #     1. Exchange delivery address
        #     2. Original order delivery address
        # ========================================================

        customer_pincode = str(
            exchange_address.get("pincode")
            or checkout_data.get("pincode")
            or ""
        ).strip()

        if not customer_pincode:

            raise HTTPException(
                status_code=400,
                detail="Exchange delivery pincode is missing."
            )

        # ========================================================
        # 9. GET NORMAL DELHIVERY SHIPPING CHARGE
        # ========================================================

        print("[EXCHANGE PAYMENT] Calling Delhivery shipping API")

        shipping_response = await get_shipping_charge(
            d_pin=customer_pincode,
            weight=500,
            pt="Pre-paid"
        )

        print("[EXCHANGE PAYMENT] Delhivery response:", shipping_response)

        if not isinstance(shipping_response, dict):

            raise HTTPException(
                status_code=400,
                detail="Invalid shipping calculation response."
            )

        try:

            normal_shipping = float(
                shipping_response.get("total_amount", 0)
            )

        except (TypeError, ValueError):

            normal_shipping = 0

        if normal_shipping <= 0:

            raise HTTPException(
                status_code=400,
                detail="Unable to calculate normal shipping."
            )

        print(
    "[EXCHANGE SHIPPING DEBUG]",
    {
        "size_exchange_count": size_exchange_count,
        "normal_shipping": normal_shipping,
        "items": items
    }
)

        # ========================================================
        # 10. APPLY EXCHANGE SHIPPING CALCULATION
        #
        # 1 size exchange:
        #     Normal shipping x 2
        #
        # 2 or more size exchanges:
        #     Normal shipping x 3
        #
        # Defective-only exchanges:
        #     No payment required.
        # ========================================================

        if size_exchange_count == 1:

            shipping_multiplier = 2

        elif size_exchange_count >= 2:

            shipping_multiplier = 3

        else:

    # No size exchange — defective-only exchange
            raise HTTPException(
                status_code=400,
                detail="No shipping payment required for defective-only exchange."
            )

        base_shipping = normal_shipping * shipping_multiplier

# Additional ₹40 per size-exchange product
        exchange_charge = size_exchange_count * 40 

        total_shipping = round(
             base_shipping + exchange_charge,
            2
        )

        amount_paise = int(
            round(total_shipping * 100)
        )

        if amount_paise <= 0:

            raise HTTPException(
                status_code=400,
                detail="Invalid exchange payment amount."
            )

        # ========================================================
        # 11. LOG PAYMENT CALCULATION
        # ========================================================

        print(
            "[EXCHANGE PAYMENT]",
            {
                "requestId": request_id,
                "originalOrderId": order_id,
                "customerPincode": customer_pincode,
                "sizeExchangeCount": size_exchange_count,
                "normalShipping": normal_shipping,
                "shippingMultiplier": shipping_multiplier,
                "totalShipping": total_shipping,
                "amountPaise": amount_paise
            }
        )

        # ========================================================
        # 12. CREATE RAZORPAY ORDER
        # ========================================================

        print("[EXCHANGE PAYMENT] Calling Razorpay order API")

        razorpay_order = razorpay_client.order.create({

            "amount": amount_paise,

            "currency": "INR",

            "receipt": request_id,

            "notes": {

                "exchangeRequestId": request_id,

                "originalOrderId": str(order_id),

                "paymentType": "Grouped Size Exchange Shipping",

                "sizeExchangeCount": str(
                    size_exchange_count
                )

            },

            "payment_capture": 1

        })

        print("[EXCHANGE PAYMENT] Razorpay order created:", razorpay_order.get("id"))

        razorpay_order_id = razorpay_order.get("id")

        if not razorpay_order_id:

            raise HTTPException(
                status_code=502,
                detail="Razorpay order creation failed."
            )

        # ========================================================
        # 13. SAVE PAYMENT DETAILS
        # ========================================================

        now = datetime.now(
            timezone.utc
        ).isoformat()

        update_result = await db[
            "exchange_requests"
        ].update_one(

            {
                "requestId": request_id,

                "status": "Payment Pending",

                "paymentStatus": "Pending"

            },

            {
                "$set": {

                    "paymentAmount": total_shipping,

                    "normalShipping": normal_shipping,

                    "shippingMultiplier": shipping_multiplier,

                    "sizeExchangeCount": size_exchange_count,

                    "razorpayOrderId": razorpay_order_id,

                    "paymentStatus": "Pending",

                    "updatedAt": now

                }
            }
        )

        if update_result.modified_count != 1:

            raise HTTPException(
                status_code=409,
                detail=(
                    "Exchange payment details could not be saved. "
                    "Please refresh and try again."
                )
            )

        # ========================================================
        # 14. RETURN PAYMENT DETAILS TO FRONTEND
        # ========================================================

        return {

            "success": True,

            "requestId": request_id,

            "razorpayOrderId": razorpay_order_id,

            "razorpayKey": RAZORPAY_KEY_ID,

            "amount": amount_paise,

            "currency": "INR",

            "shipping": {

                "normalShipping": normal_shipping,

                "shippingMultiplier": shipping_multiplier,

                "sizeExchangeCount": size_exchange_count,

                "totalShipping": total_shipping

            }

        }

    except HTTPException:

        raise

    except Exception as e:

        import traceback

        print(
            "[EXCHANGE PAYMENT] Create payment error:",
            repr(e)
        )

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail="Unable to create exchange payment."
        )

# ============================================================
# EXCHANGE: VERIFY RAZORPAY PAYMENT
# ============================================================

@app.post("/exchange/verify-payment")
async def verify_exchange_payment(request: Request):

    try:

        data = await request.json()

        request_id = str(
            data.get("requestId") or ""
        ).strip()

        razorpay_order_id = str(
            data.get("razorpay_order_id") or ""
        ).strip()

        razorpay_payment_id = str(
            data.get("razorpay_payment_id") or ""
        ).strip()

        razorpay_signature = str(
            data.get("razorpay_signature") or ""
        ).strip()

        # ----------------------------------------------------
        # 1. Validate input
        # ----------------------------------------------------

        if not all([
            request_id,
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature
        ]):

            raise HTTPException(
                status_code=400,
                detail="Missing Razorpay payment details."
            )

        # ----------------------------------------------------
        # 2. Find grouped exchange
        # ----------------------------------------------------

        exchange = await db["exchange_requests"].find_one({
            "requestId": request_id
        })

        if not exchange:

            raise HTTPException(
                status_code=404,
                detail="Exchange request not found."
            )

        # ----------------------------------------------------
        # 3. Validate grouped request
        # ----------------------------------------------------

        items = exchange.get("items") or []

        size_items = [
            item for item in items
            if isinstance(item, dict)
            and item.get("reason") == "size_issue"
        ]

        if not size_items:

            raise HTTPException(
                status_code=400,
                detail="Payment verification is only for size exchanges."
            )

        if exchange.get("razorpayOrderId") != razorpay_order_id:

            raise HTTPException(
                status_code=400,
                detail="Razorpay order does not match this exchange."
            )

        # ----------------------------------------------------
        # 4. Verify Razorpay signature
        # ----------------------------------------------------

        try:

            razorpay_client.utility.verify_payment_signature({

                "razorpay_order_id": razorpay_order_id,

                "razorpay_payment_id": razorpay_payment_id,

                "razorpay_signature": razorpay_signature

            })

        except Exception:

            raise HTTPException(
                status_code=400,
                detail="Razorpay payment signature verification failed."
            )

        # ----------------------------------------------------
        # 5. Fetch payment
        # ----------------------------------------------------

        payment = razorpay_client.payment.fetch(
            razorpay_payment_id
        )

        if payment.get("order_id") != razorpay_order_id:

            raise HTTPException(
                status_code=400,
                detail="Payment belongs to a different Razorpay order."
            )

        # ----------------------------------------------------
        # 6. Verify exact amount
        # ----------------------------------------------------

        expected_amount = int(
            round(
                float(exchange.get("paymentAmount", 0)) * 100
            )
        )

        if int(payment.get("amount", 0)) != expected_amount:

            raise HTTPException(
                status_code=400,
                detail="Payment amount does not match exchange shipping."
            )

        if payment.get("currency") != "INR":

            raise HTTPException(
                status_code=400,
                detail="Invalid payment currency."
            )

        if payment.get("status") != "captured":

            raise HTTPException(
                status_code=400,
                detail="Payment has not been captured yet."
            )

        # ----------------------------------------------------
        # 7. Idempotency
        # ----------------------------------------------------

        if exchange.get("paymentStatus") == "Paid":

            if exchange.get(
                "razorpayPaymentId"
            ) == razorpay_payment_id:

                return {

                    "success": True,

                    "message": "Exchange payment was already verified.",

                    "requestId": request_id,

                    "status": exchange.get("status"),

                    "paymentStatus": "Paid"

                }

            raise HTTPException(
                status_code=409,
                detail="A different payment has already been recorded."
            )

        # ----------------------------------------------------
        # 8. Approve grouped size exchange
        #
        # Defective items remain Pending Review.
        # ----------------------------------------------------

        if exchange.get("status") != "Payment Pending":

            raise HTTPException(
                status_code=409,
                detail="Exchange is not awaiting payment."
            )

        now = datetime.now(timezone.utc).isoformat()

        # Update only size-exchange item statuses.
        updated_items = []

        for item in items:

            updated_item = dict(item)

            if updated_item.get("reason") == "size_issue":

                updated_item["status"] = "Approved"

            updated_items.append(updated_item)

        result = await db["exchange_requests"].update_one(

            {
                "requestId": request_id,
                "status": "Payment Pending",
                "paymentStatus": "Pending",
                "razorpayOrderId": razorpay_order_id
            },

            {
                "$set": {

                    "items": updated_items,

                    "status": "Approved",

                    "paymentStatus": "Paid",

                    "razorpayPaymentId": razorpay_payment_id,

                    "razorpaySignature": razorpay_signature,

                    "paymentVerifiedAt": now,

                    "updatedAt": now

                }
            }
        )

        # ----------------------------------------------------
        # 9. Handle concurrent verification
        # ----------------------------------------------------

        if result.modified_count != 1:

            latest = await db["exchange_requests"].find_one({
                "requestId": request_id
            })

            if (
                latest
                and latest.get("paymentStatus") == "Paid"
                and latest.get("razorpayPaymentId")
                == razorpay_payment_id
            ):

                return {

                    "success": True,

                    "message": "Exchange payment was already verified.",

                    "requestId": request_id,

                    "status": latest.get("status"),

                    "paymentStatus": "Paid"

                }

            raise HTTPException(
                status_code=409,
                detail="Exchange status changed. Please refresh."
            )

        # ----------------------------------------------------
        # 10. Return verified result
        # ----------------------------------------------------


        original_order_id = str(
            exchange.get("originalOrderId")
            or exchange.get("orderId")
            or ""
        ).strip()

        return {

            "success": True,

            "message": "Payment verified. Size exchange approved.",

            "requestId": request_id,

            "originalOrderId": original_order_id,

            "status": "Approved",

            "paymentStatus": "Paid"

        }

    except HTTPException:
        raise

    except Exception as e:

        import traceback

        print(
            "[EXCHANGE PAYMENT] Verification error:",
            repr(e)
        )

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail="Unable to verify exchange payment."
        )

