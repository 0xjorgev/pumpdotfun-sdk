import asyncio
import logging

from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient


logger = logging.getLogger()
logger.setLevel(logging.INFO)

RPC_URL_HELIUS = "https://mainnet.helius-rpc.com/?api-key=f32b640c-6877-43e7-924b-2035b448d17e"


async def get_solana_balance(public_key: Pubkey) -> float:
    """
    Fetches the SOL balance of a given Solana wallet address.

    :param wallet_address: The public address of the Solana wallet.
    :return: Balance in SOL as a float.
    """
    async with AsyncClient(RPC_URL_HELIUS) as client:
        try:
            # Fetch the balance (in lamports)
            balance_response = await client.get_balance(public_key)
            # Balance is returned in lamports (1 SOL = 10^9 lamports)
            lamports = balance_response.value
            sol_balance = lamports / 1e9
            return sol_balance
        except Exception as e:
            print(f"Error fetching balance: {e.error_msg}")
            return 0.0


def lambda_handler(event, context):
    body = {
        "owner": "4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
        "fee": 0.045,
        "tokens": [
            {
                "token_mint": "G1jFTkA5XCw8b9Sut9PW6cUzaoTfhmW58fRXqa78pump",
                "decimals": 6,
                "balance": 0.002039
            }
        ],
    }
    sol_balance = []

    try:
        logger.info("Running lambda function successfully!")

        public_key = Pubkey.from_string(body["owner"])

        # Run async function synchronously
        sol_balance = asyncio.run(get_solana_balance(public_key=public_key))

    except Exception as e:
        logger.error("Error starting instance: %s", e)
        raise e

    return {
        'statusCode': 200,
        'body': {"sol_balance": sol_balance}
    }
