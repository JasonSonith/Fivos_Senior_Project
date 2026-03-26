from pymongo import MongoClient

USERNAME = "rct2122_db_user"
PASSWORD = "Fivos"

URI = f"mongodb+srv://{USERNAME}:{PASSWORD}@fivos.1bnjrns.mongodb.net/?appName=Fivos"

client = MongoClient(URI)

db = client["fivos-shared"]

devices_collection = db["devices"]
validation_collection = db["validationResults"]

def test_connection():
    try:
        client.admin.command("ping")
        print("Connected to MongoDB successfully!")
    except Exception as e:
        print("Connection failed:", e)

if __name__ == "__main__":
    test_connection()