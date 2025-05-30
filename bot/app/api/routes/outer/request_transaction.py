from fastapi import APIRouter
import logging

from solders.pubkey import Pubkey

from api.adapters.strapi_adapter import Middleware
from api.config import appconfig
from api.handlers.exceptions import EntityNotFoundException, TooManyInstructionsException, ErrorProcessingData
from api.models.outer_models import Quote, RequestTransaction
from api.libs.utils import close_ata_transaction, get_atas_from_owner
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
        claim_all = body.claim_all

        if not tokens and not claim_all:
            instructions = Quote(
                quote=[]
            )
            return instructions

        if claim_all:
            # Fetching all related ATAs
            tokens = await get_atas_from_owner(owner=Pubkey.from_string(owner))

        if not tokens:
            instructions = Quote(
                quote=[]
            )
            return instructions

        if len(tokens) > appconfig.MAX_RETRIEVABLE_ACCOUNTS:
            raise TooManyInstructionsException(detail=appconfig.MAX_RETRIEVABLE_ACCOUNTS_MESSAGE)

        last_fee = list(appconfig.GHOSTFUNDS_FEES_PERCENTAGES.values())[-1]
        if fee not in appconfig.GHOSTFUNDS_FEES_PERCENTAGES.values() or fee < last_fee:
            # Assigning unknown or lower fee
            logging.warning("request_close_ata_transaction: unknown fee of {} received from account {}. Adjusting fee to be {}".format(
                fee,
                owner,
                appconfig.GHOSTFUNDS_FEES_PERCENTAGES[1]
            ))
            fee = appconfig.GHOSTFUNDS_FEES_PERCENTAGES[1]

        # Retrieving possible referrals from middleware
        middleware = Middleware()

        referrals = middleware.get_remote_commissions(pubkey=owner)

        transactions = await close_ata_transaction(
            owner=Pubkey.from_string(owner),
            tokens=tokens,
            fee=fee,
            referrals=referrals
        )

        quote = Quote(
            quote=transactions
        )
        return quote
    except EntityNotFoundException as e:
        raise EntityNotFoundException(
            detail=e.detail
        )
    except ErrorProcessingData as e:
        raise ErrorProcessingData(
            detail=e.detail
        )
