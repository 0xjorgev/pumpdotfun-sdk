import base64
import json

from fastapi import APIRouter
from solders.pubkey import Pubkey

from api.handlers.exceptions import EntityNotFoundException
from api.models.outer_models import Instructions, RequestTransaction
from api.libs.utils import close_burn_ata_instructions
router = APIRouter()


@router.post(
    path="/associated_token_accounts/burn_and_close/instructions",
    response_model=Instructions,
    summary="Retrieve the intructions to close an associated token account",
    description="Retrieve both burn and close and fees intructions to close an associated token account"
)
async def request_close_ata_instructions(
    body: RequestTransaction,
):
    try:
        owner = body.owner
        token = body.token_mint
        decimals = body.decimals
        balance = body.balance
        fee = body.fee

        instructions = await close_burn_ata_instructions(
            owner=Pubkey.from_string(owner),
            token_mint=Pubkey.from_string(token),
            decimals=decimals,
            balance=balance,
            fee=fee
        )

        # Serialize JSON object to bytes
        instructions_json = json.dumps(instructions)
        instructions_bytes = instructions_json.encode("utf-8")

        # Encode the entire byte string as Base64
        instructions_base64 = base64.b64encode(instructions_bytes).decode("utf-8")

        instructions = Instructions(
            response=instructions_base64
        )
        return instructions
    except EntityNotFoundException as e:
        raise EntityNotFoundException(
            detail=e.detail
        )
