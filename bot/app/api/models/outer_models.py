from __future__ import annotations
from typing import Annotated, List, Optional
from pydantic import AnyUrl, BaseModel, Field, constr


AccountAddressType = Annotated[
    str,
    Field(
        pattern=r"^[1-9A-HJ-NP-Za-km-z]{44}$",
        description=(
            "The Solana associated token account address. Must be a valid address with 44 characters, "
            "excluding the letters `l`, `I`, and `O` to avoid ambiguity."
        )
    )
]


class CountAssociatedTokenAccounts(BaseModel):
    total_accounts: int = Field(
        0, description='Total number of associated accounts.'
    )
    burnable_accounts: int = Field(
        0, description='Number of accounts eligible for burn.'
    )
    accounts_for_manual_review: int = Field(
        0, description='Number of accounts requiring manual review.'
    )
    rent_balance: float = Field(
        0, description='Total rent balance for the accounts.'
    )
    rent_balance_usd: float = Field(
        0, description='Total rent balance converted to USD.'
    )
    fee: float = Field(
        0, description='GhostFunds fee.'
    )


class AssociatedTokenAccount(BaseModel):
    token_mint: Optional[str] = Field(
        None, description='The mint address of the token.'
    )
    associated_token_account: Optional[str] = Field(
        None, description='The associated token account address.'
    )
    owner: Optional[str] = Field(
        None, description='The owner of the associated token account.'
    )
    token_amount: Optional[float] = Field(
        None, description='The amount of tokens held.'
    )
    token_price: Optional[float] = Field(None, description='The price of the token.')
    token_value: Optional[float] = Field(
        None, description='The total value of the tokens held.'
    )
    decimals: Optional[int] = Field(
        None, description='The number of decimals for the token.'
    )
    sol_balance: Optional[float] = Field(
        None, description='The balance of SOL in the associated account.'
    )
    sol_balance_usd: Optional[float] = Field(
        None, description='The balance of SOL converted to USD.'
    )
    is_dust: Optional[bool] = Field(
        None, description='Whether the token is considered "dust."'
    )
    uri: Optional[AnyUrl] = Field(
        None, description="URI pointing to the token's metadata."
    )
    cdn_uri: Optional[AnyUrl] = Field(
        None, description='CDN URI pointing to cached metadata.'
    )
    mime: Optional[str] = Field(
        None, description="The MIME type of the token's metadata file."
    )
    description: Optional[str] = Field(None, description='A description of the token.')
    name: Optional[str] = Field(None, description='The name of the token.')
    symbol: Optional[str] = Field(None, description='The symbol of the token.')
    authority: Optional[str] = Field(None, description='The token authority address.')
    supply: Optional[int] = Field(None, description='The total supply of the token.')
    token_program: Optional[str] = Field(
        None, description='The Solana token program ID.'
    )
    insufficient_data: Optional[bool] = Field(
        None, description='Whether there is insufficient data for this token.'
    )


class AssociatedTokenAccounts(BaseModel):
    page: int = Field(
        ..., gt=0, description='The current page being retrieved (must be greater or equal than 0).'
    )
    items: int = Field(
        ..., gt=0, description='The number of items per page (must be greater or equal than 0).'
    )
    total_items: int = Field(
        ..., gt=-1, description='The total number of retrievable items (must be non-negative).'
    )
    accounts: List[AssociatedTokenAccount] = Field(
        description="The list of associated token accounts.",
        default=[]
    )

    # @model_validator(mode="before")
    # def validate_pagination(cls, values):
    #     page = values.get("page")
    #     items = values.get("items")
    #     if page <= 0 or items <= 0:
    #         raise ValidationError("Both 'page' and 'items' must be greater than 0.")
    #     return values


class RequestTransaction(BaseModel):
    owner: constr(pattern=r'^[1-9A-HJ-NP-Za-km-z]{44}$') = (
        Field(
            ...,
            description='Owner account address.',
            example='7dLn2WU6vX6Yk1BeMoAAumx7grc79TdcUgrpqvA9CvFi',
        )
    )
    token_mint: constr(pattern=r'^[1-9A-HJ-NP-Za-km-z]{32,50}$') = Field(
        ...,
        description='The mint address of the token. Supports standard Solana mint format and extended formats.',
        example='bpMAcs5cEDu33kbCgTcBu7HtuZwsoNwsMH839jupump',
    )
    decimals: int = Field(
        ..., description='The number of decimals for the token.', example=6
    )
    balance: float = Field(
        ..., description='ATA SOls balance'
    )
    fee: float = Field(
        ..., description='GhostFunds fee.'
    )


class Quote(BaseModel):
    quote: Optional[str] = Field(
        None, description='A base64-encoded string representing the quote.'
    )


class Instructions(BaseModel):
    response: Optional[str] = Field(
        None, description='A base64-encoded string representing the list of instructions in hex format.'
    )
