from fastapi import APIRouter

from api.models.outer_models import Quote, RequestTransaction

router = APIRouter()

@router.post(
    path="/associated_token_accounts/burn_and_close/transaction",
    response_model=Quote,
    summary="Retrieve a transaction with intructions to close an associated token account",
    description="Retrieve a transaction with both burn and close intructions for an associated token account"
)
async def request_close_ata_transaction(
    body: RequestTransaction
):
    txn = None
    ata = body.associated_token_account
    token = body.token_mint
    decimals = body.decimals


    quote = Quote(
        quote=txn
    )
    return quote
