from fastapi import FastAPI
from routes import get_quote

# Create the FastAPI app
app = FastAPI()

# Define routes
@app.post("/get_quote")
async def fetch_quote():
    return await get_quote()
