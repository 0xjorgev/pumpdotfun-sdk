import asyncio
from datetime import datetime
from solana.rpc.async_api import AsyncClient
from solders.signature import Signature

from bot.config import appconfig


async def get_block_by_signature(signature_str: str):
    async with AsyncClient(appconfig.RPC_URL_QUICKNODE) as client:
        try:
            signature = Signature.from_string(signature_str)
            # Fetch the transaction details
            await asyncio.sleep(0.5)  # Wait 2 seconds for the redis connection to start

            tx_resp = await client.get_transaction(
                signature,
                encoding="json",
                max_supported_transaction_version=0  # Adjust based on your needs
            )

            if not tx_resp.value:
                print("Transaction not found.")
                return None

            # Extract the slot number from the transaction
            slot = tx_resp.value.slot
            start_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
            print(f"{start_time} - Checking slot: {slot}")

            # Fetch the block details using the slot number
            block_resp = await client.get_block(
                slot=slot,
                encoding="jsonParsed",
                max_supported_transaction_version=0
            )
            if not block_resp.value:
                print("Block not found.")
                return None

            return block_resp
        except Exception as e:
            print("Exception when getting block: {}".format(e))
            return None
