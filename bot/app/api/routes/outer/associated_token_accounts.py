from fastapi import APIRouter

# Create a router for the associated_token_accounts routes
router = APIRouter()

@router.get("/associated_token_accounts")
async def fetch_associated_token_accounts():
    response = {"detail": "Dummy response"}
    return response

