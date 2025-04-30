import base64
import json

from fastapi import APIRouter
from solders.pubkey import Pubkey

from api.config import appconfig
from api.handlers.exceptions import EntityNotFoundException, TooManyInstructionsException
from api.libs.utils import close_burn_ata_instructions
from api.models.outer_models import Instructions, RequestTransaction

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
        fee = body.fee
        tokens = body.tokens
        if not tokens:
            instructions = Instructions(
                response=None
            )
            return instructions

        if len(tokens) > appconfig.MAX_RETRIEVABLE_ACCOUNTS:
            raise TooManyInstructionsException(detail=appconfig.MAX_RETRIEVABLE_ACCOUNTS_MESSAGE)

        tokens = [token.model_dump() for token in tokens]

        last_fee = list(appconfig.GHOSTFUNDS_FEES_PERCENTAGES.values())[-1]
        if fee not in appconfig.GHOSTFUNDS_FEES_PERCENTAGES.values() or fee < last_fee:
            # Assigning unknown or lower fee
            print("Warning: unknown fee of {} received from account {}. Adjusting fee to be {}".format(
                fee,
                owner,
                appconfig.GHOSTFUNDS_FEES_PERCENTAGES[1]
            ))
            fee = appconfig.GHOSTFUNDS_FEES_PERCENTAGES[1]

        instructions = await close_burn_ata_instructions(
            owner=Pubkey.from_string(owner),
            tokens=tokens,
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
    except TooManyInstructionsException as te:
        raise TooManyInstructionsException(
            detail=te.detail
        )
