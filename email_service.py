# import smtplib
# from email.mime.text import MIMEText
# from email.mime.multipart import MIMEMultipart
# from fastapi import FastAPI, Request
# from fastapi.middleware.cors import CORSMiddleware

# app = FastAPI()

# # CORS settings
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# SMTP_SERVER = "smtp.gmail.com"
# SMTP_PORT = 587
# SENDER_EMAIL = "your_email@gmail.com"
# SENDER_PASSWORD = "your_app_password"  # Use App Password for Gmail

# @app.post("/send-order-email")
# async def send_order_email(request: Request):
#     data = await request.json()

#     customer_name = data["customer"]["name"]
#     customer_email = data["customer"]["email"]
#     customer_phone = data["customer"]["phone"]
#     customer_address = f"{data['customer']['addressLine1']}, {data['customer']['addressLine2']}, {data['customer']['city']}, {data['customer']['state']} - {data['customer']['pincode']}"

#     order_items = ""
#     for item in data["items"]:
#         order_items += f"- {item['name']} (Qty: {item['quantity']}, Price: ₹{item['price']})<br>"

#     total_price = data["total"]

#     # Email content
#     subject = f"Myha Order Confirmation - Thank you for shopping with us!"
#     body = f"""
#     <h2>Hi {customer_name},</h2>
#     <p>Thank you for your order with <b>Myha</b>. Here are your order details:</p>
#     <h3>Customer Details:</h3>
#     Name: {customer_name}<br>
#     Email: {customer_email}<br>
#     Phone: {customer_phone}<br>
#     Address: {customer_address}<br>

#     <h3>Order Details:</h3>
#     {order_items}
#     <p><b>Total Price:</b> ₹{total_price}</p>

#     <p>We will notify you once your order is shipped.</p>

#     <br>
#     <p>Best regards,<br>
#     <b>Myha Couture</b><br>
#     📞 +91-9876543210<br>
#     📧 contact@myha.com</p>
#     """

#     msg = MIMEMultipart()
#     msg["From"] = SENDER_EMAIL
#     msg["To"] = customer_email
#     msg["Subject"] = subject
#     msg.attach(MIMEText(body, "html"))

#     with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
#         server.starttls()
#         server.login(SENDER_EMAIL, SENDER_PASSWORD)
#         server.sendmail(SENDER_EMAIL, customer_email, msg.as_string())

#     return {"message": "Email sent successfully"}
