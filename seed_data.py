import motor.motor_asyncio
import asyncio

MONGO_URI = "mongodb+srv://snmsss2002:LdakIzkuVR1TIFSK@myha-cluster.2biasoh.mongodb.net/?retryWrites=true&w=majority&appName=Myha-Cluster"

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client["myha-db"]
collection = db["products"]

sample_products = [
    {
        "id": 1,
        "name": "Brindha Dress",
        "price": "₹2,499",
        "images": [
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg",
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg",
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg"
        ]
    },
    {
        "id": 2,
        "name": "Sita Anarkali",
        "price": "₹2,199",
        "images": [
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg",
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg",
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg"
        ]
    },
    {
        "id": 3,
        "name": "Divya Gown",
        "price": "₹2,799",
        "images": [
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg",
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg",
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg"
        ]
    },
    {
        "id": 4,
        "name": "Mira Set",
        "price": "₹2,599",
        "images": [
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg",
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg",
            "https://res.cloudinary.com/dw35epojg/image/upload/v1753624789/temp-image_m0qua0.jpg"
        ]
    }
]

async def insert_data():
    await collection.delete_many({})  # Clear old data
    await collection.insert_many(sample_products)
    print("✅ Sample products inserted!")

if __name__ == "__main__":
    asyncio.run(insert_data())
