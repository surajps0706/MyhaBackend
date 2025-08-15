from fastapi import FastAPI, HTTPException, Request
from models import Product
from database import db
from bson import ObjectId
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import razorpay
import os
import smtplib
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load env vars
load_dotenv()

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
# Email Sending Function
# =============================
def send_order_email(to_email, order_data):
    try:
        subject = f"Myha Couture - Order Confirmation #{order_data.get('tempOrderId')}"
        
        # HTML body
        items_html = ""
        for item in order_data.get("items", []):
            items_html += f"""
            <li>
                {item['name']} - ₹{item['price']} 
                (Qty: {item.get('quantity', 1)})
            </li>
            """

        html = f"""
        <h2>Thank you for your order, {order_data['checkoutData']['name']}!</h2>
        <p>We’ve received your order and will start processing it soon.</p>
        <h3>Order Details:</h3>
        <ul>
            {items_html}
        </ul>
        <p><strong>Total Price:</strong> ₹{order_data['totalAmount']}</p>

        <h3>Shipping Address:</h3>
        <p>
            {order_data['checkoutData']['addressLine1']}<br>
            {order_data['checkoutData']['addressLine2']}<br>
            {order_data['checkoutData']['city']}, {order_data['checkoutData']['state']} - {order_data['checkoutData']['pincode']}<br>
            Phone: {order_data['checkoutData']['phone']}<br>
            Email: {order_data['checkoutData']['email']}
        </p>

        <p>For any queries, contact us at <strong>myha.support@example.com</strong>.</p>
        <p>~ Team Myha Couture</p>
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
        print("❌ ERROR:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/product/{product_id}")
async def get_product(product_id: str):
    try:
        product = await db["products"].find_one({"_id": ObjectId(product_id)})
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return fix_id(product)
    except Exception as e:
        print("❌ ERROR:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/add-product")
async def add_product(product: Product):
    try:
        result = await db["products"].insert_one(product.dict())
        return {"message": "Product added", "id": str(result.inserted_id)}
    except Exception as e:
        print("❌ ERROR:", e)
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
            "amount": amount * 100,  # convert rupees to paise
            "currency": currency,
            "receipt": receipt,
            "notes": notes
        })
        return razorpay_order
    except Exception as e:
        print("❌ Razorpay order creation error:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})

# =============================
# Save Order & Send Email
# =============================
@app.post("/save-order")
async def save_order(request: Request):
    data = await request.json()
    try:
        result = await db["orders"].insert_one(data)

        # Send email to customer
        customer_email = data.get("checkoutData", {}).get("email")
        if customer_email:
            send_order_email(customer_email, data)

        return {"message": "Order saved", "id": str(result.inserted_id)}
    except Exception as e:
        print("❌ ERROR saving order:", e)
        raise HTTPException(status_code=500, detail=str(e))
