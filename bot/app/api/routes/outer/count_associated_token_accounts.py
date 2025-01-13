from fastapi import APIRouter, Depends

from api.models.outer_models import AccountAddressType, CountAssociatedTokenAccounts
from api.libs.utils import count_associated_token_accounts
from solders.pubkey import Pubkey
# Create a router for the associated_token_accounts routes
router = APIRouter()


# Dependency for pre-validation
def validate_account_address(account_address: AccountAddressType) -> str:
    return account_address


@router.get(
    path="/associated_token_accounts/count",
    response_model=CountAssociatedTokenAccounts,
    summary="Get account statistics for a Solana associated token account",
    description="Retrieve statistics for a given Solana associated token account address."
)
async def associated_token_accounts_count(
    account_address: str = Depends(validate_account_address)
):
    wallet_pubkey = Pubkey.from_string(account_address)
    data = await count_associated_token_accounts(wallet_pubkey=wallet_pubkey)
    response = CountAssociatedTokenAccounts(
        total_accounts=data["total_accounts"],
        burnable_accounts=data["burnable_accounts"],
        accounts_for_manual_review=data["accounts_for_manual_review"],
        rent_balance=data["rent_balance"],
        rent_balance_usd=data["rent_balance_usd"],
        fee=data["fee"]
    )
    return response
