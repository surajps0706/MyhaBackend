from fastapi import FastAPI, HTTPException, Request, Header, UploadFile, File, Form,APIRouter
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from models import ProductCreate
from pymongo.errors import OperationFailure
from models import ForgotPasswordRequest, ResetPasswordRequest
import asyncio


import boto3
from botocore.client import Config

from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import timedelta
from models import UserCreate, UserLogin
from database import users_collection
import random

from models import Product
from database import db, get_next_order_id
from bson import ObjectId

import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

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
    url = f"{DELHIVERY_BASE_URL}/api/v1/packages/json/?waybill={awb}"
    headers = {
        "Authorization": f"Token {DELHIVERY_API_TOKEN}",
        "Accept": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        print(f"❌ Delhivery API error: {e}")
        return []

    timeline = []
    try:
        shipment_data = data.get("ShipmentData", [])
        if shipment_data and "Shipment" in shipment_data[0]:
            scans = shipment_data[0]["Shipment"].get("Scans", [])
            for scan in scans:
                detail = scan.get("ScanDetail", {})
                status = detail.get("Scan", "")
                scan_time = detail.get("ScanDateTime")
                location = detail.get("ScannedLocation")

                # ✅ Track only major statuses
                if status in ["Picked Up", "In Transit", "Out for Delivery", "Delivered"]:
                    timeline.append({
                        "status": status,
                        "time": scan_time,
                        "source": "Delhivery",
                        "location": location
                    })
    except Exception as e:
        print(f"❌ Error parsing Delhivery response: {e}")

    return timeline


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
        product = await db["products"].find_one({"_id": ObjectId(product_id)})
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        product = fix_id(product)
        product["images"] = build_product_image_urls(
            product["id"],
            product.get("image_count", 0)
        )
        return product

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


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
    """Creates a new Razorpay order and assigns a sequential Myha order ID — without inserting in DB yet."""
    try:
        data = await request.json()
        amount = data.get("amount")
        currency = data.get("currency", "INR")
        notes = data.get("notes", {})
        destination_pincode = data.get("destination_pincode")

        if not amount:
            return JSONResponse(status_code=400, content={"error": "Amount is required"})

        # ✅ Step 1: Generate next sequential order ID
        order_id = await get_next_order_id()

        # ✅ Step 2: (Optional) Fetch shipping charge from Delhivery
        shipping_charge = 0
        if destination_pincode:
            try:
                shipping_charge = await fetch_shipping_charge(destination_pincode)
            except Exception as e:
                print(f"⚠️ Failed to fetch shipping charge: {e}")
                shipping_charge = 0

        # ✅ Step 3: Create Razorpay order (use order_id in receipt for traceability)
        razorpay_order = razorpay_client.order.create({
            "amount": int(float(amount) * 100),  # Razorpay expects amount in paise
            "currency": currency,
            "receipt": f"MYHA{order_id}",
            "notes": notes,
            "payment_capture": 1
        })

        # ⚠️ Removed DB insert here — we only save after payment success via /save-order

        # ✅ Step 4: Return response to frontend
        return {
            "success": True,
            "message": "Order created successfully",
            "orderId": order_id,
            "razorpay_order": razorpay_order,
            "shippingCharge": shipping_charge
        }

    except Exception as e:
        print(f"❌ Error creating order: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

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
async def update_product(product_id: str, request: Request, authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    data = await request.json()
    result = await db["products"].update_one(
        {"_id": ObjectId(product_id)},
        {"$set": data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product updated"}


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


