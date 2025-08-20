from fastapi import FastAPI, HTTPException, Request, Header
from models import Product
from database import db
from bson import ObjectId
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import razorpay
import os
import smtplib
import io
import pandas as pd
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import random

# Load env vars
load_dotenv()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "myha-secret")

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],  # Angular dev server
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
# Email Sending Function
# =============================
def send_order_email(to_email, order_data):
    try:
        subject = f"Myha Couture - Order Confirmation #{order_data.get('orderId')}"

        html = f"""
        <div style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto; border:1px solid #eee; border-radius:8px; overflow:hidden;">
          <div style="background:#000; padding:20px; text-align:center;">
            <img src="https://res.cloudinary.com/dw35epojg/image/upload/v1754020493/logo_v5px6x.jpg" alt="Myha Logo" style="max-height:50px;" />
          </div>
          <div style="padding:20px;">
            <h2 style="color:#000;">Thank you for shopping with <span style="color:#d63384;">Myha Couture</span>, {order_data['checkoutData']['name']}!</h2>
            <p>Your order <b>#{order_data.get('orderId')}</b> has been placed successfully. We’ll notify you once it is shipped.</p>
          </div>
        </div>
        """

        msg = MIMEMultipart()
        msg["From"] = EMAIL_USER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, to_email, msg.as_string())

        print(f"✅ Order email sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


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
        product_data["createdAt"] = datetime.utcnow()
        result = await db["products"].insert_one(product_data)
        return {"message": "Product added", "id": str(result.inserted_id)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


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
        # ✅ Generate MYHA-style Order ID
        myha_order_id = f"MYHA{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
        data["orderId"] = myha_order_id   # ✅ use this everywhere
        data["razorpayOrderId"] = data.get("orderId")  # store Razorpay orderId separately
        data["status"] = "Pending Delivery"
        data["createdAt"] = datetime.utcnow()

        # Save to Mongo
        result = await db["orders"].insert_one(data)

        # Send email with MYHA ID
        customer_email = data.get("checkoutData", {}).get("email")
        if customer_email:
            send_order_email(customer_email, data)

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
        orders.append(fix_id(order))
    return orders


# =============================
# Admin: Update Status
# =============================
@app.put("/orders/{order_id}/status")
async def update_order_status(order_id: str, request: Request, authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()
    new_status = data.get("status")

    if new_status not in ["Pending Delivery", "Processing", "Shipped", "Delivered"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    result = await db["orders"].update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"status": new_status}}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")

    return {"message": "Status updated successfully"}


# =============================
# Admin: Export Orders to Excel
# =============================
@app.get("/orders/export")
async def export_orders(authorization: str = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    orders_cursor = db["orders"].find().sort("createdAt", -1)
    orders = []
    async for order in orders_cursor:
        created_at = order.get("createdAt")

        if hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()
        elif created_at is None:
            created_at = ""
        else:
            created_at = str(created_at)

        orders.append({
            "Order ID": order.get("orderId"),
            "Customer": order.get("checkoutData", {}).get("name"),
            "Email": order.get("checkoutData", {}).get("email"),
            "Phone": order.get("checkoutData", {}).get("phone"),
            "Total Amount": order.get("totalAmount"),
            "Status": order.get("status"),
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
        order = await db["orders"].find_one({"_id": ObjectId(order_id)})
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return fix_id(order)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================
# Track Order (Customer Facing)
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
            "orderId": order_id,   # ✅ match MYHA Order ID
            "checkoutData.email": email
        })
        if not order:
            raise HTTPException(status_code=404, detail="No order found with provided details")
        return fix_id(order)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


