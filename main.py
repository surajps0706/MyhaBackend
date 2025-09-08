from fastapi import FastAPI, HTTPException, Request, Header, UploadFile, File, Form
from models import Product
from database import db
from bson import ObjectId
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import FastAPI, UploadFile, File, Form
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
from typing import List
import cloudinary
import cloudinary.uploader
import httpx   # ⭐ Delhivery API calls
import json    # ⭐ for payload formatting

# =============================
# Load env vars
# =============================
load_dotenv()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "myha-secret")

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
DELHIVERY_BASE_URL = os.getenv("DELHIVERY_BASE_URL", "https://staging-express.delhivery.com")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Welcome to Myha Backend 🚀"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "https://taupe-cannoli-010c45.netlify.app",
        "https://myhacouture.com",
        "https://www.myhacouture.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def fix_id(doc):
    doc["id"] = str(doc["_id"])
    doc.pop("_id", None)
    return doc


# =============================
# Utility: Generate Professional Order ID
# =============================
def generate_order_id():
    now = datetime.utcnow()
    return f"MYHA{now.strftime('%Y%m%d%H%M%S')}{random.randint(100,999)}"

# =============================
# Send Email (Order Confirmation with Shipping + Product Images)
# =============================
def send_order_email(to_email, order_data, is_admin=False):
    try:
        # Subject line
        if is_admin:
            subject = f"📦 New Order Received – Myha Couture #{order_data.get('orderId')}"
        else:
            subject = f"Myha Couture - Order Confirmation #{order_data.get('orderId')}"

        checkout = order_data.get("checkoutData", {})
        cart_items = order_data.get("cartItems", [])
        items_html = ""

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
                price = float(price)

                qty = int(item.get("quantity", 1))
                total = price * qty
                image = item.get("images", [""])[0]

                # extra details
                size = item.get("selectedSize", "")
                sleeve = item.get("sleeveType", "")
                sleeve_price = item.get("sleevePrice", 0)
                height = item.get("preferredHeight", "")
                height_price = item.get("extraHeightPrice", 0)

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

        total_amount = order_data.get("totalAmount", 0)
        if isinstance(total_amount, str):
            total_amount = total_amount.replace("₹", "").replace(",", "").strip()
        total_amount = float(total_amount)

        # Greeting / Intro
        if is_admin:
            greeting = f"<h2 style='color:#000;'>🚨 New Order Alert</h2>"
            intro = f"<p>A new order <b>#{order_data.get('orderId')}</b> has been placed by <b>{checkout.get('name')}</b>.</p>"
        else:
            greeting = f"<h2 style='color:#000;'>Thank you for shopping with <span style='color:#d63384;'>Myha Couture</span>, {checkout.get('name')}!</h2>"
            intro = f"<p>Your order <b>#{order_data.get('orderId')}</b> has been placed successfully. We’ll notify you once it is shipped.</p>"

        # Shipping details block
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

        msg = MIMEMultipart()
        msg["From"] = f"Myha Couture <{EMAIL_FROM}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_FROM, to_email, msg.as_string())

        print(f"✅ Order email sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

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
        products_cursor = db["products"].find()
        products = []
        async for product in products_cursor:
            products.append(fix_id(product))
        return products
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# @app.post("/products")
# async def products_alias(
#     name: str = Form(...),
#     price: float = Form(...),
#     description: str = Form(""),
#     category: str = Form(...),
#     sizes: List[str] = Form(default=["Free Size"]),
#     colors: List[str] = Form(default=["Default"]),
#     images: List[UploadFile] = File(None),
#     authorization: str = Header(None)
# ):
#     return await upload_product(
#         name, price, description, category, sizes, colors, images, authorization
#     )


@app.get("/product/{product_id}")
async def get_product(product_id: str):
    try:
        product = await db["products"].find_one({"_id": ObjectId(product_id)})
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return fix_id(product)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/add-product")
async def add_product(product: Product):
    try:
        product_data = product.dict()
        product_data["createdAt"] = datetime.now().strftime("%Y-%m-%d")
        result = await db["products"].insert_one(product_data)
        return {"message": "Product added", "id": str(result.inserted_id)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

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
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        image_urls = []
        if images:
            for img in images:
                upload_result = cloudinary.uploader.upload(img.file)
                image_urls.append(upload_result["secure_url"])

        product_data = {
            "name": name,
            "price": price,
            "description": description,
            "category": category,
            "sizes": sizes,
            "colors": colors,
            "images": image_urls,
            "createdAt": datetime.now().strftime("%Y-%m-%d")
        }

        result = await db["products"].insert_one(product_data)
        return {"message": "✅ Product uploaded", "id": str(result.inserted_id), "product": product_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================
# Razorpay Order Creation
# =============================
@app.post("/create-order")
async def create_order(request: Request):
    data = await request.json()
    amount = data.get("amount")
    currency = data.get("currency", "INR")
    receipt = data.get("receipt", "receipt_order_123")
    notes = data.get("notes", {})

    if not amount:
        return JSONResponse(status_code=400, content={"error": "Amount is required"})

    try:
        razorpay_order = razorpay_client.order.create({
            "amount": amount * 100,
            "currency": currency,
            "receipt": receipt,
            "notes": notes
        })
        return razorpay_order
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# =============================
# Save Order & Send Email
# =============================
@app.post("/save-order")
async def save_order(request: Request):
    data = await request.json()
    try:
        myha_order_id = f"MYHA{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        data["orderId"] = myha_order_id
        data["razorpayOrderId"] = data.get("orderId")
        data["status"] = "Preparing"  # ✅ Default standardized
        data["createdAt"] = datetime.now().strftime("%Y-%m-%d")
        data["statusTimeline"] = {
             "Preparing": datetime.now().strftime("%Y-%m-%d")
        }

        result = await db["orders"].insert_one(data)

        customer_email = data.get("checkoutData", {}).get("email")
        if customer_email:
            send_order_email(customer_email, data, is_admin=False)

        if ADMIN_EMAIL:
            send_order_email(ADMIN_EMAIL,data,is_admin=True)

        return {"message": "Order saved", "id": str(result.inserted_id), "orderId": myha_order_id}
    except Exception as e:
        print("❌ ERROR saving order:", e)
        raise HTTPException(status_code=500, detail=str(e))


# =============================
# Admin: View Orders
# =============================
@app.get("/orders")
async def get_orders(authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    orders_cursor = db["orders"].find().sort("createdAt", -1)
    orders = []
    async for order in orders_cursor:
        order = fix_id(order)
        order["orderId"] = order.get("orderId")
        orders.append(order)
    return orders


# =============================
# Admin: Update Status (with AWB)
# =============================
@app.put("/orders/{order_id}/status")
async def update_order_status(order_id: str, request: Request, authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()
    new_status = data.get("status")

    valid_statuses = [ "Preparing", "Packed", "Shipped", "Delivered"]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")

    order = await db["orders"].find_one({"orderId": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    status_timeline = order.get("statusTimeline", {})
    status_timeline[new_status] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    update_data = {"status": new_status, "statusTimeline": status_timeline}

    # ⭐ Shipment creation when Packed
    if new_status == "Packed" and not order.get("awb"):
        shipment_payload = {
            "shipments": [
                {
                    "name": order["checkoutData"].get("name", "Unknown"),
                    "add": order["checkoutData"].get("address", "Not Provided"),
                    "pin": order["checkoutData"].get("pincode", ""),
                    "city": order["checkoutData"].get("city", "Chennai"),
                    "state": order["checkoutData"].get("state", "Tamil Nadu"),
                    "country": "India",
                    "phone": order["checkoutData"]["phone"],
                    "order": order["orderId"],
                    "payment_mode": "Prepaid" if order.get("paymentType") == "Prepaid" else "COD",
                    "cod_amount": float(order.get("totalAmount", 0)) if order.get("paymentType") == "COD" else 0,
                    "total_amount": float(order.get("totalAmount", 0)),
                    "products_desc": ", ".join([p["name"] for p in order.get("cartItems", [])]),
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

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{DELHIVERY_BASE_URL}/api/cmu/create.json",
                    headers=headers,
                    data={"format": "json", "data": json.dumps(shipment_payload)}
                )
            data = resp.json()
            print("📦 Delhivery Response:", data)

            if "packages" in data and data["packages"]:
                awb = data["packages"][0]["waybill"]
                update_data["awb"] = awb
            else:
                dummy_awb = f"DUMMY{random.randint(100000,999999)}"
                update_data["awb"] = dummy_awb
        except Exception as e:
            print(f"❌ Delhivery Shipment creation error: {e}")
            dummy_awb = f"DUMMY{random.randint(100000,999999)}"
            update_data["awb"] = dummy_awb

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
    order = await db["orders"].find_one({"orderId": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    admin_timeline = []
    for status, time in order.get("statusTimeline", {}).items():
        admin_timeline.append({
            "status": status,
            "time": time,
            "source": "Admin"
        })

    courier_timeline = []
    if order.get("awb"):
        courier_timeline = await fetch_delhivery_tracking(order["awb"])

    full_timeline = admin_timeline + courier_timeline
    full_timeline.sort(key=lambda x: x["time"])

    return {
        "orderId": order_id,
        "awb": order.get("awb"),
        "timeline": full_timeline
    }


# =============================
# Admin: Export Orders
# =============================
@app.get("/orders/export")
async def export_orders(authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    orders_cursor = db["orders"].find().sort("createdAt", -1)
    orders = []
    async for order in orders_cursor:
        created_at = str(order.get("createdAt", ""))
        orders.append({
            "Order ID": order.get("orderId"),
            "Customer": order.get("checkoutData", {}).get("name"),
            "Email": order.get("checkoutData", {}).get("email"),
            "Phone": order.get("checkoutData", {}).get("phone"),
            "Total Amount": order.get("totalAmount"),
            "Status": order.get("status"),
            "AWB": order.get("awb") or "—",
            "Created At": created_at
        })

    df = pd.DataFrame(orders)
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
# Admin Login
# =============================
@app.post("/admin/login")
async def admin_login(request: Request):
    data = await request.json()
    username = data.get("username")
    password = data.get("password")

    if username == os.getenv("ADMIN_USER", "admin") and password == os.getenv("ADMIN_PASSWORD", "super-secret"):
        return {"token": os.getenv("ADMIN_TOKEN", "myha-secret")}
    
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
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product updated"}


# =============================
# Get Single Order by ID (Admin)
# =============================
@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    try:
        order = await db["orders"].find_one({"orderId": order_id})
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return fix_id(order)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================
# Track Order (Customer)
# =============================
@app.post("/track-order")
async def track_order(request: Request):
    data = await request.json()
    order_id = data.get("orderId")
    email = data.get("email")

    if not order_id or not email:
        raise HTTPException(status_code=400, detail="Order ID and email required")

    try:
        order = await db["orders"].find_one({
            "orderId": order_id,
            "checkoutData.email": email
        })
        if not order:
            raise HTTPException(status_code=404, detail="No order found with provided details")
        return fix_id(order)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/add-product-url")
async def add_product_url(request: Request, authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()
    try:
        product_data = {
            "name": data.get("name"),
            "price": data.get("price"),
            "description": data.get("description"),
            "category": data.get("category"),
            "sizes": data.get("sizes", ["Customizable"]),
            "colors": data.get("colors", ["Default"]),
            "selectedSize": data.get("selectedSize", "Free Size"),
            "selectedColor": data.get("selectedColor", ""),
            "images": data.get("images", []),
            "createdAt": datetime.now().strftime("%Y-%m-%d")
        }

        result = await db["products"].insert_one(product_data)
        saved_product = await db["products"].find_one({"_id": result.inserted_id})
        saved_product = fix_id(saved_product)

        return {
            "message": "✅ Product added",
            "id": str(result.inserted_id),
            "product": saved_product
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================
# Reviews API
# =============================
@app.get("/products/{product_id}/reviews")
async def get_reviews(product_id: str):
    try:
        reviews_cursor = db["reviews"].find({"productId": product_id}).sort("createdAt", -1)
        reviews = []
        async for review in reviews_cursor:
                reviews.append(fix_id(review))
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
            "createdAt": datetime.now().strftime("%Y-%m-%d")
        }

        result = await db["reviews"].insert_one(review_data)
        return {"message": "✅ Review added", "id": str(result.inserted_id), "review": review_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        {"$set": {"status": "Cancelled"}}
    )

    return {
        "message": "Order cancelled successfully",
        "orderId": order_id,
        "awb": awb,
        "delhiveryResponse": delhivery_response
    }
