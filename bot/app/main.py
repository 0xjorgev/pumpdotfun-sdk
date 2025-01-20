from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from api.handlers.exceptions import entity_not_found_exception_handler, EntityNotFoundException
from api.routes.outer.associated_token_accounts import router as associated_token_accounts_route
from api.routes.outer.count_associated_token_accounts import router as count_associated_token_accounts_route
from api.routes.outer.request_transaction import router as request_ata_transaction_route
from api.routes.outer.request_instructions import router as request_ata_instructions_route

# Create the FastAPI app
app = FastAPI(
    debug=False,
    title="Ghost Funds Solana's API",
    version="0.1"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)

# Including routes
app.include_router(router=associated_token_accounts_route, prefix="/api", tags=["Associated Token Accounts"])
app.include_router(
    router=count_associated_token_accounts_route,
    prefix="/api",
    tags=["Count Associated Token Accounts"]
)
app.include_router(
    router=request_ata_transaction_route,
    prefix="/api",
    tags=["Request Associated Token Account Transaction"]
)
app.include_router(
    router=request_ata_instructions_route,
    prefix="/api",
    tags=["Request Associated Token Account Instructions"]
)

# Register the exception handler without decorator
app.add_exception_handler(EntityNotFoundException, entity_not_found_exception_handler)

handler = Mangum(app)
