from fastapi import APIRouter
import logging

from solders.pubkey import Pubkey

from api.config import appconfig
from api.handlers.exceptions import EntityNotFoundException, TooManyInstructionsException
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
    try:
        owner = body.owner
        fee = body.fee
        tokens = body.tokens
        if not tokens:
            instructions = Quote(
                quote=None
            )
            return instructions

        if len(tokens) > appconfig.BACKEND_MAX_INSTRUCTIONS:
            raise TooManyInstructionsException(detail="Too many instructions")

        last_fee = list(appconfig.GHOSTFUNDS_FEES_PERCENTAGES.values())[-1]
        if fee not in appconfig.GHOSTFUNDS_FEES_PERCENTAGES.values() or fee < last_fee:
            # Assigning unknown or lower fee
            logging.warning("request_close_ata_transaction: unknown fee of {} received from account {}. Adjusting fee to be {}".format(
                fee,
                owner,
                appconfig.GHOSTFUNDS_FEES_PERCENTAGES[1]
            ))
            fee = appconfig.GHOSTFUNDS_FEES_PERCENTAGES[1]

        transaction = await close_ata_transaction(
            owner=Pubkey.from_string(owner),
            tokens=tokens,
            fee=fee
        )

        quote = Quote(
            quote=transaction
        )
        return quote
    except EntityNotFoundException as e:
        raise EntityNotFoundException(
            detail=e.detail
        )
