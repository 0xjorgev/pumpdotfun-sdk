import base58

from enum import Enum
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solders.pubkey import Pubkey

from bot.config import appconfig


class Path:
    @staticmethod
    def rootPath():
        return "$"

class TxType(Enum):
    buy = "buy"
    sell = "sell"

class Trader(Enum):
    sniper = "sniper"
    volume_bot = "volume_bot"
    token_creator = "token_creator"

async def get_solana_balance(public_key: Pubkey) -> float:
    """
    Fetches the SOL balance of a given Solana wallet address.

    :param wallet_address: The public address of the Solana wallet.
    :return: Balance in SOL as a float.
    """
    async with AsyncClient(appconfig.RPC_URL) as client:
            try:
                # Fetch the balance (in lamports)
                balance_response = await client.get_balance(public_key)
                # Balance is returned in lamports (1 SOL = 10^9 lamports)
                lamports = balance_response.value
                sol_balance = lamports / 1e9
                return sol_balance
            except Exception as e:
                print(f"Error fetching balance: {e}")
                return 0.0

async def get_own_token_balance(wallet_pubkey: Pubkey, token_mint_addres: str) -> float:
    """
    Fetches the balance of a specific token in a given Solana wallet.

    :param wallet_pubkey: The public address of the Solana wallet.
    :param token_mint_pubkey: The mint address of the token to query.
    :return: Token balance as a float.
    """
    async with AsyncClient(appconfig.RPC_URL) as client:
        try:
            # Fetch token mint public key owned by the wallet
            token_mint_pubkey = decode_pump_fun_token(token=token_mint_addres)

            opts = TokenAccountOpts(
                mint=token_mint_pubkey,  # The mint address of the token
                program_id=None,             # (Optional) SPL token program ID
                encoding="base64"        # (Optional) Response encoding
            )
            response = await client.get_token_accounts_by_owner(
                owner=wallet_pubkey,
                opts=opts,
            )

            if len(response.value) == 0:
                raise Exception("No token accounts found for this mint address.")

            # Assume the first token account holds the balance (adjust for multisig if needed)
            token_pubkey = response.value[0].pubkey
            # Fetch the token balance
            balance_response = await client.get_token_account_balance(
                token_pubkey
            )
            balance_data = balance_response.value
            raw_balance = int(balance_data.amount)
            decimals = int(balance_data.decimals)

            # Convert to human-readable balance
            readable_balance = raw_balance / (10 ** decimals)
            return readable_balance

        except Exception as e:
            print(f"Error fetching token '{token_mint_addres}' balance: {e}")
            return 0.0

def decode_pump_fun_token(token: str) -> Pubkey:
    """
    Decodes a 44-character token from pump.fun to retrieve its mint address.
    
    :param token: 44-character token.
    :return: Token mint address (base58 encoded).
    """
    try:
        decoded_bytes = base58.b58decode(token)
        return Pubkey(decoded_bytes)
    except Exception as e:
        raise ValueError(f"Failed to decode token: {e}")
