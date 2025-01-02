import random
import requests
import struct
import time

from datetime import datetime
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from solana.rpc.commitment import Confirmed

from solders.pubkey import Pubkey
from spl.token.instructions import close_account, CloseAccountParams
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.compute_budget import set_compute_unit_price
from solders.transaction import Transaction
from spl.token.instructions import (
    burn_checked,
    BurnCheckedParams,
)
from api.config import appconfig


async def get_solana_balance(public_key: Pubkey) -> float:
    """
    Fetches the SOL balance of a given Solana wallet address.

    :param wallet_address: The public address of the Solana wallet.
    :return: Balance in SOL as a float.
    """
    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
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

def get_solana_price() -> float:
    """
    Retrieves the current Solana price in USD using a public API.

    Returns:
        float: Current Solana price in USD.
    """
    retries = appconfig.RETRIES
    price = 0
    counter = 0
    while True:
        try:
            if counter >= retries:
                break

            response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd")
            response.raise_for_status()
            price_data = response.json()
            price = price_data["solana"]["usd"]
            break
        except Exception as e:
            counter += 1
            print("get_solana_price Error: Failed to fetch Solana price. retriying {} of {}".format(
                counter,
                retries
            ))
            time.sleep(counter)
    
    return price

async def get_token_accounts_by_owner(wallet_address=str)->dict:
    response = {}
    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
        data = {
            "jsonrpc": "2.0",
            "id": "test",
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet_address,
                {
                    "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
                },
                {
                    "encoding": "jsonParsed"
                }
            ]
        }
        try:
            response = requests.post(
                    url=appconfig.RPC_URL_HELIUS,
                    json=data,
                    headers={"Content-Type": "application/json"}
                )
            if response.status_code != 200:
                print("get_token_accounts_by_owner: Bad status code '{}' recevied for token {}".format(
                        response.status_code,
                        wallet_address
                    )
                )
                return response

            content = response.json()
            response = content["result"]["value"]

            return response
        except Exception as e:
            print("get_token_accounts_by_owner-> Error: {}".format(e))
            return response

def get_token_metadata(token_address: str)->dict:
    metadata = {}

    data = {
        "jsonrpc": "2.0",
        "id": "test",
        "method": "getAsset",
        "params": {
            "id": token_address
        }
    }
    retries = appconfig.RETRIES
    counter = 0
    while True:
        if counter >= retries:
            break

        try:
            response = requests.post(
                    url=appconfig.RPC_URL_HELIUS,
                    json=data,
                    headers={"Content-Type": "application/json"}
                )
            if response.status_code != 200:
                counter += 1
                print("get_metadata: Bad status code '{}' recevied for token {}. Retries {} of {}".format(
                        response.status_code,
                        token_address,
                        counter,
                        retries
                    )
                )
                time.sleep(counter)
                continue

            content = response.json()
            metadata.update(content["result"]["content"]["files"][0])
            metadata.update(content["result"]["content"]["metadata"])
            metadata["authority"] = content["result"]["authorities"][0]["address"]
            metadata["supply"] = content["result"]["token_info"]["supply"]
            metadata["decimals"] = content["result"]["token_info"]["decimals"]
            metadata["token_program"] = content["result"]["token_info"]["token_program"]
            metadata["insufficient_data"] = False

            if "price_info" in content["result"]["token_info"]:
                metadata["price_info"] = content["result"]["token_info"]["price_info"]
            else:
                # It might happen that the token comes with no price info. IF so, we'll mark the token
                metadata["price_info"] = {"price_per_token": 0}

                metadata["insufficient_data"] = True
            break

        except Exception as e:
            counter += 1
            print("get_metadata: Error retrieving metadata for token {}. Retries {} of {}".format(
                    token_address,
                    counter,
                    retries
                )
            )
            time.sleep(counter)

    return metadata

async def count_associated_token_accounts(
    wallet_pubkey: Pubkey
) -> int:
    """
    Fetch the amount of associated token accounts an address holds
    :param wallet_pubkey: The public address of the Solana wallet.
    :return: amount of associated token accounts
    """
    total = {
        "total_accounts": 0,
        "burnable_accounts": 0,
        "accounts_for_manual_review": 0,
        "rent_balance": 0,
        "rent_balance_usd": 0
    }
    min_token_value = 1
    account_samples = 5

    # TODO: implement token's black list (like USDC, etc)
    token_blacklist = []
    original_accounts = await get_token_accounts_by_owner(wallet_address=str(wallet_pubkey))
    usd_sol_value = 0

    accounts = [
        account for account in original_accounts 
        if account["account"]["data"]["parsed"]["info"]["mint"] not in token_blacklist
    ]

    if accounts:
        usd_sol_value = get_solana_price()
        if usd_sol_value == 0:
            return total
        # Calculating accounts balance as AN APROXIMATION to speed up this process
        account_sample_list = accounts
        if len(accounts) > account_samples:
            my_list = list(range(len(accounts)))
            # Generate X random positions
            random_positions = random.sample(range(len(my_list)), account_samples)
            # Get the 5 random values from the list
            account_sample_list = [my_list[pos] for pos in random_positions]

        sum_balance = 0
        for index in account_sample_list:
            associated_tokan_account = accounts[index]["pubkey"]
            sum_balance += await get_solana_balance(public_key=Pubkey.from_string(associated_tokan_account))

        average_balance = sum_balance / len(account_sample_list)

        total["rent_balance"] = average_balance * len(accounts)
        total["rent_balance_usd"] = total["rent_balance"] * usd_sol_value

    accounts_for_manual_review = 0
    for account in accounts:
        mint = account["account"]["data"]["parsed"]["info"]["mint"]
        token_ammount = account["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]

        token_value = 1
        total["total_accounts"] += 1
        if token_ammount * token_value < min_token_value:
            total["burnable_accounts"] += 1
        else:
            print("token {} has significan value".format(mint))

    total["accounts_for_manual_review"] = accounts_for_manual_review

    return total

async def detect_dust_token_accounts(
    wallet_pubkey: Pubkey,
    do_balance_aproximation: bool = True
) -> list[dict]:
    """
    Fetches the balance of a specific token in a given Solana wallet.

    :param wallet_pubkey: The public address of the Solana wallet.
    :return: Token balance as a float.
    """
    min_token_value = 1
    account_samples = 5
    working_balance = 0
    # Refactor this: remove this line of code and test as client is not being used
    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
        try:
            # TODO: implement token's black list (like USDC, etc)
            token_blacklist = []
            original_accounts = await get_token_accounts_by_owner(wallet_address=str(wallet_pubkey))
            accounts = [
                account for account in original_accounts 
                if account["account"]["data"]["parsed"]["info"]["mint"] not in token_blacklist
            ]

            if not accounts:
                return []
            
            # Fetch the current Solana price
            sol_price = get_solana_price()
            if sol_price == 0:
                return []

            if do_balance_aproximation:
                account_sample_list = accounts
                if len(accounts) > account_samples:
                    my_list = list(range(len(accounts)))
                    # Generate X random positions
                    random_positions = random.sample(range(len(my_list)), account_samples)
                    # Get the 5 random values from the list
                    account_sample_list = [my_list[pos] for pos in random_positions]

                sum_balance = 0
                for index in account_sample_list:
                    associated_tokan_account = accounts[index]["pubkey"]
                    sum_balance += await get_solana_balance(public_key=Pubkey.from_string(associated_tokan_account))

                working_balance = sum_balance / len(account_sample_list)

            counter = 0
            account_output = []
            for account in accounts:
                counter +=1

                mint = account["account"]["data"]["parsed"]["info"]["mint"]
                owner = account["account"]["data"]["parsed"]["info"]["owner"]
                token_amount = account["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]
                decimals = account["account"]["data"]["parsed"]["info"]["tokenAmount"]["decimals"]
                associated_token_account = account["pubkey"]

                metadata = get_token_metadata(token_address=mint)

                token_price = metadata["price_info"]["price_per_token"]
                token_value = token_price * token_amount
                
                uri = metadata["uri"]
                cdn_uri = metadata["cdn_uri"]
                mime = metadata["mime"]
                description = metadata["description"] if "description" in metadata else ""
                name = metadata["name"].strip()
                symbol = metadata["symbol"].strip()
                authority = metadata["authority"]
                supply =  metadata["supply"]
                token_program = metadata["token_program"]
                insufficient_data = metadata["insufficient_data"]  # Non listed tokens returns a zero price

                account_output.append(
                    {
                        "token_mint": mint,
                        "associated_token_account": associated_token_account,
                        "owner": owner,
                        "token_amount": token_amount,
                        "token_price": token_price,
                        "token_value": token_value,
                        "decimals": decimals,
                        "sol_balance": working_balance,
                        "sol_balance_usd": working_balance * sol_price,
                        "is_dust": token_value < min_token_value,
                        "uri": uri,
                        "cdn_uri": cdn_uri,
                        "mime": mime,
                        "description": description,
                        "name": name,
                        "symbol": symbol,
                        "authority": authority,
                        "supply": supply,
                        "token_program": token_program,
                        "insufficient_data": insufficient_data,
                    }
                )

            return account_output

        except Exception as e:
            print(f"Error fetching associated token accounts for account '{str(wallet_pubkey)}' balance: {e}")
            return account_output

async def burn_and_close_associated_token_account(
    associated_token_account: Pubkey,
    token_mint: Pubkey,
    decimals: int,
    keypair: Keypair
) -> str:
    """
    Burs all tokens from the associated token account
    :param associated_token_account[Pubkey]: associated token account
    :param token_mint[Pubkey]: tokens to get burned
    :param keypair[Keypair]: signer and account owner
    :param decimals[int]: The token's decimals (default 9 for SOL).
    :return: [str] transaction signature.
    """
    txn_signature = None
    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
        try:
            response = await client.get_account_info(associated_token_account)
            account_info = response.value
            if not account_info:
                print("Associated token account {} does not exist.".format(
                    associated_token_account
                ))
                return txn_signature
            
            # Derive the associated token account address
            TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

            # BURN
            data = account_info.data
            if len(data) != 165:
                print("burn_associated_token_account-> Error: Invalid data length for SPL associated account {} for token {}".format(
                    str(associated_token_account),
                    str(token_mint)
                ))
            (
                mint,
                owner,
                amount_lamports,
                delegate_option,
                delegate,
                state,
                is_native_option,
                is_native,
                delegated_amount,
                close_authority_option,
                close_authority
            ) = struct.unpack("<32s32sQ4s32sB4sQ8s4s32s",data)
            owner = owner
            amount = amount_lamports 

            # Construct the burn instruction
            params = BurnCheckedParams(
                program_id=TOKEN_PROGRAM_ID,
                mint=token_mint,
                account=associated_token_account,
                owner=keypair.pubkey(),
                amount=amount,
                decimals=decimals,
                signers=[keypair.pubkey()]
            )
            burn_ix = burn_checked(params=params)

            # CLOSE
            # Create the close account instruction
            close_ix = close_account(
                CloseAccountParams(
                    program_id=TOKEN_PROGRAM_ID,
                    account=associated_token_account,
                    dest=keypair.pubkey(),
                    owner=keypair.pubkey()
                )
            )

            blockhash = await client.get_latest_blockhash()
            recent_blockhash = blockhash.value.blockhash
            tx = Transaction.new_signed_with_payer(
                instructions=[set_compute_unit_price(1_000), burn_ix, close_ix],
                payer=keypair.pubkey(),
                signing_keypairs=[keypair],
                recent_blockhash=recent_blockhash
            )
            tx_signature = await client.send_transaction(
                txn=tx,
                opts=TxOpts(preflight_commitment=Confirmed),
            )

            current_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
            print("Trade->{} Transaction: https://solscan.io/tx/{} at {}".format(
                "Transfer",
                tx_signature.value,
                current_time
            ))
            await client.confirm_transaction(tx_signature.value, commitment="confirmed")
            print("Transaction confirmed")

        except Exception as e:
            print("transfer_solanas Error: {}".format(e))

    return txn_signature
