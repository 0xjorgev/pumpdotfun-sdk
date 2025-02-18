from fastapi import APIRouter, Depends, Query
from typing import List
from pydantic import PositiveInt

from api.models.outer_models import AccountAddressType, AssociatedTokenAccount, AssociatedTokenAccounts
from api.libs.utils import detect_dust_token_accounts
from api.config import appconfig
from solders.pubkey import Pubkey
# Create a router for the associated_token_accounts routes
router = APIRouter()


# Dependency for pre-validation
def validate_account_address(account_address: AccountAddressType) -> str:
    return account_address


@router.get(
    path="/associated_token_accounts",
    response_model=AssociatedTokenAccounts,
    summary="Get account statistics for a Solana associated token account",
    description="Retrieve statistics for a given Solana associated token account address."
)
async def fetch_associated_token_accounts(
    account_address: str = Depends(validate_account_address),
    page: PositiveInt = Query(
        default=appconfig.DEFAULT_PAGE,
        description="The current page to retrieve (must be greater than 0)."
    ),
    items: PositiveInt = Query(
        default=appconfig.DEFAULT_ITEMS_PER_PAGE,
        description="The number of items per page (must be greater than 0)."
    ),
):
    wallet_pubkey = Pubkey.from_string(account_address)
    page = page if page >= appconfig.DEFAULT_PAGE else appconfig.DEFAULT_PAGE
    items = items if items > 1 else appconfig.DEFAULT_ITEMS_PER_PAGE

    ata_list, page, total_items = await detect_dust_token_accounts(
        wallet_pubkey=wallet_pubkey,
        page=page,
        items_per_page=items
    )

    # Calculate pagination details
    if total_items == 0:
        # If the list is empty, return a response with metadata and an empty accounts list
        return AssociatedTokenAccounts(
            page=page,
            items=items,
            total_items=0,
            accounts=[]
        )

    accounts: List[AssociatedTokenAccount] = [
        AssociatedTokenAccount(
            token_mint=ata["token_mint"],
            associated_token_account=ata["associated_token_account"],
            owner=ata["owner"],
            token_amount_lamports=ata["token_amount_lamports"],
            token_amount=ata["token_amount"],
            token_price=ata["token_price"],
            token_value=ata["token_value"],
            decimals=ata["decimals"],
            sol_balance=ata["sol_balance"],
            sol_balance_usd=ata["sol_balance_usd"],
            is_dust=ata["is_dust"],
            uri=ata["uri"],
            cdn_uri=ata["cdn_uri"],
            mime=ata["mime"],
            description=ata["description"],
            name=ata["name"],
            symbol=ata["symbol"],
            authority=ata["authority"],
            supply=ata["supply"],
            token_program=ata["token_program"],
            insufficient_data=ata["insufficient_data"]
        )
        for ata in ata_list
    ]

    ata_accounts = AssociatedTokenAccounts(
        page=page,
        items=items,
        total_items=total_items,
        accounts=accounts
    )
    return ata_accounts
