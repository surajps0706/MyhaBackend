from pydantic import BaseModel
from typing import List,Optional

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

# uvicorn main:app --reload
# .\env\Scripts\activate
# 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