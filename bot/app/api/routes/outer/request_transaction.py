from fastapi import APIRouter

from solders.pubkey import Pubkey

from api.handlers.exceptions import EntityNotFoundException
from api.models.outer_models import Quote, RequestTransaction
from api.libs.utils import close_ata_transaction
router = APIRouter()

@router.post(
    path="/associated_token_accounts/burn_and_close/transaction",
    response_model=Quote,
    summary="Retrieve a transaction with intructions to close an associated token account",
    description="Retrieve a transaction with both burn and close intructions for an associated token account"
)
async def request_close_ata_transaction(
    body: RequestTransaction,
):
    txn = None
    try:
        owner = body.owner
        token = body.token_mint
        decimals = body.decimals

        transaction = await close_ata_transaction(
            owner=Pubkey.from_string(owner),
            token_mint=Pubkey.from_string(token),
            decimals=decimals,
            encode_base64=True
        )

        quote = Quote(
            quote=transaction
        )
        return quote
    except EntityNotFoundException as e:
        raise EntityNotFoundException(
            detail=e.detail
        )
