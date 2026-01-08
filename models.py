from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime

class Product(BaseModel):
    name: str
    price: str
    description: str
    sizes: List[str]
    colors: List[str]
    selectedSize: str
    selectedColor: str
    images: List[str]
    category: Optional[str] = "kurta"
    isSoldOut: Optional[bool] = False   # 🆕 Added line
    displayOrder: Optional[int] = 0
    image_count: int



class ProductCreate(BaseModel):
    name: str
    price: float
    description: str
    category: str
    sizes: List[str]
    colors: List[str]
    image_count: int
    enableFabricPrice: Optional[bool] = False
    fabricBasePrice: Optional[int] = None
    stock: Optional[int] = 0


# ----------------- NEW CODE -----------------
class TimelineEntry(BaseModel):
    status: str                 # e.g., "Preparing", "Packed", "Picked Up"
    time: datetime              # when this status was updated
    source: str                 # "Admin" or "Delhivery"

class Customer(BaseModel):
    name: str
    phone: str
    address: str
    pincode: str

class Order(BaseModel):
    orderId: str                           # internal order ID (MYHA001 etc.)
    customer: Customer                     # customer details
    products: List[Product]                # list of products in the order
    paymentType: str                       # "COD" or "Prepaid"
    awb: Optional[str] = None              # AWB number from Delhivery
    timeline: List[TimelineEntry] = []     # order timeline


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    newPassword: str

# ----------------- NEW CODE END -----------------

# uvicorn main:app --reload
# .\env\Scripts\activate
