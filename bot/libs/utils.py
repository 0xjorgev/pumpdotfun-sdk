import base58
import base64
import json
import random
import requests
import struct
import time

from datetime import datetime
from enum import Enum
from solana.rpc.api import Client
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solders.message import Message, MessageV0
from solders.pubkey import Pubkey
from solders.rpc.responses import GetTokenAccountsByOwnerResp

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
    analytics = "analytics"
    scanner = "scanner"

class Celebrimborg(Enum):
    exit = "exit"
    start = "start"

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


def get_token_mint_decimals(mint_address: str) -> int:
    """
    Fetches the decimals value for a given token mint.

    Parameters:
        mint_address (str): The mint address of the token.

    Returns:
        int: The number of decimals for the token.
    """
    client = Client(appconfig.RPC_URL_QUICKNODE)

    mint_pubkey = Pubkey.from_string(mint_address)

    # Fetch the mint account info
    response = client.get_account_info(mint_pubkey)
    if not response.value:
        raise ValueError(f"Mint account {mint_address} not found")
    
    from spl.token._layouts import MINT_LAYOUT, ACCOUNT_LAYOUT
    mint_data = MINT_LAYOUT.parse(response.value.data)
    decimals = mint_data.decimals

    return decimals


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
        "recoverable_balance": 0,
        "recoverable_balance_usd": 0
    }
    min_token_value = 1
    account_samples = 5
    retries = 5

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

        total["recoverable_balance"] = average_balance * len(accounts)
        total["recoverable_balance_usd"] = total["recoverable_balance"] * usd_sol_value

    accounts_for_manual_review = 0
    for account in accounts:
        mint = account["account"]["data"]["parsed"]["info"]["mint"]
        token_ammount = account["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]

        # # Get token value
        # counter = 0
        # metadata = {}
        # while True:
        #     metadata = get_token_metadata(token_address=mint)
        #     if metadata:
        #         retries = 0
        #         break
        #     counter += 1
        #     time.sleep(counter)
        
        # if not metadata:
        #     # Forcing out with what we have
        #     return total
        
        # if metadata["insufficient_data"]:
        #     accounts_for_manual_review += 1
        #     continue

        # token_value = metadata["price_info"]["price_per_token"]

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
    token_mint_addres: str = None
) -> list[dict]:
    """
    Fetches the balance of a specific token in a given Solana wallet.

    :param wallet_pubkey: The public address of the Solana wallet.
    :param token_mint_pubkey: The mint address of the token to query.
    :return: Token balance as a float.
    """
    min_token_balance = 1
    max_retries = 5
    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
        try:

            program_id = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
            opts = TokenAccountOpts(
                mint=None,
                program_id=program_id,         # (Optional) SPL token program ID
                encoding="base64"        # (Optional) Response encoding
            )

            response = await client.get_token_accounts_by_owner(
                owner=wallet_pubkey,
                opts=opts,
            )
            await asyncio.sleep(1)
            token_accounts_response = GetTokenAccountsByOwnerResp.from_json(response.to_json())

            if not token_accounts_response.value:
                return []
            
            # Fetch the current Solana price
            sol_price = get_solana_price()

            accounts = []
            counter = 0
            for account in token_accounts_response.value:
                counter +=1
    
                associated_token_account = str(account.pubkey)
                if token_mint_addres and token_mint_addres != associated_token_account:
                    continue

                data = account.account.data
                if len(data) != 165:
                    raise ValueError("Invalid data length for an SPL token account")
                
                # Unpack the data using the SPL token account layout
                (
                    mint,                     # 32 bytes
                    owner,                    # 32 bytes
                    amount_lamports,          # 8 bytes (token balance)
                    delegate_option,          # 4 bytes (delegate option: 0 or 1)
                    delegate,                 # 32 bytes (delegate public key)
                    state,                    # 1 byte (state of the account)
                    is_native_option,         # 4 bytes (is_native option: 0 or 1)
                    is_native,                # 8 bytes (amount of native SOL if is_native is set)
                    delegated_amount,         # 8 bytes (amount of tokens delegated)
                    close_authority_option,   # 4 bytes (close authority option: 0 or 1)
                    close_authority           # 32 bytes (close authority public key)
                ) = struct.unpack("<32s32sQ4s32sB4sQ8s4s32s", data)

                mint_address = str(Pubkey.from_bytes(mint))

                retries_counter = 0
                decimals = 0
                while True:
                    try:
                        if retries_counter >= max_retries:
                            print("detect_dust_token_accounts-> Max retries of {} reached when calling get_token_mint_decimals")
                            return accounts
                        decimals = get_token_mint_decimals(mint_address=mint_address)
                        break
                    except:
                        print("sleeping 1sec at counter {}...".format(counter))
                        await asyncio.sleep(1)
                        retries_counter += 1
                amount = amount_lamports / 10**decimals

                # Fetch SOL balance of the associated token account
                retries_counter = 0
                sol_balance_response = 0
                while True:
                    try:
                        if retries_counter >= max_retries:
                            print("detect_dust_token_accounts-> Max retries of {} reached when calling get_balance")
                            return accounts
                        sol_balance_response = await client.get_balance(Pubkey.from_string(associated_token_account))
                        break
                    except:
                        print("sleeping at counter {}...".format(counter))
                        await asyncio.sleep(1)
                        retries_counter += 1
                
                sol_balance = sol_balance_response.value / 1e9  # Convert lamports to SOL
                sol_balance_usd = sol_balance * sol_price  # Calculate SOL value in USD

                accounts.append(
                    {
                        "token_mint": str(Pubkey(mint)),
                        "associated_token_account": associated_token_account,
                        "owner": str(Pubkey(owner)),
                        "token_balance": amount,
                        "sol_balance": sol_balance,
                        "sol_balance_usd": sol_balance_usd,
                        "is_dust": amount < min_token_balance,
                        "delegate": str(Pubkey(delegate)) if delegate_option != b"\x00" else None,
                        "state": state,
                        "is_native": is_native == b"\x01",
                        "delegated_amount": delegated_amount,
                        "close_authority": str(Pubkey(close_authority)) if close_authority_option != b"\x00" else None,
                    }
                )

            return accounts

        except Exception as e:
            print(f"Error fetching token '{token_mint_addres}' balance: {e}")
            return []

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

def initial_buy_calculator(sol_in_bonding_curve: float):
    pump_dont_fun_initial_fund = appconfig.SCANNER_PUMPDONTFUN_INITIAL_FUND
    sols = round(sol_in_bonding_curve - pump_dont_fun_initial_fund, 3)
    return sols

def flatten_data(data):
    if isinstance(data, list):
        return b"".join(flatten_data(item) for item in data)
    elif isinstance(data, int):
        return data.to_bytes(1, 'little')  # Convert integer to a single byte
    return b""

def decode_instruction(raw_data):
    if len(raw_data) >= 5:  # Ensure at least enough data for a float
        # Assume the first byte is the Field ID
        field_id = raw_data[0]
        # Interpret the next 4 bytes as a float (little-endian)
        try:
            price_impact = struct.unpack('<f', raw_data[1:5])[0]
        except struct.error:
            price_impact = None
        return field_id, price_impact
    else:
        return None, None

def get_instructions_from_message(msg: Message):
    """
    This function parse the Message from Quote and gets all intructions
    UNDER DEVELOPMENT: need to tell which instruction is the priceImpactPct
    """
    message_json = msg.to_json()
    message_dict = json.loads(message_json)
    parsed_instructions = []
    # Check for priceImpactPct in the instructions
    instructions = message_dict.get("instructions", [])
    for idx, instruction in enumerate(instructions):
        if isinstance(instruction, dict):
            data = instruction.get("data", "")
            #raw_data = flatten_data(data)
            raw_data = instruction.get('data', [])
            flat_data = flatten_data(raw_data)  # Use your flattening logic
            field_id, price_impact = decode_instruction(flat_data)
            print(f"Instruction {idx}: Field ID: {field_id}, Price Impact: {price_impact}")
            parsed_instructions.append(
                {"field_id": idx, "possible_price_impact": price_impact}
            )
                                                
            # Decode the instruction data if necessary (e.g., Base64 decoding)
            try:
                decoded_data = base64.b64decode(data).decode("utf-8")
            except Exception:
                decoded_data = data  # Keep raw if decoding fails

            # Check if priceImpactPct is in the decoded data
            if "priceImpactPct" in decoded_data:
                print(f"Instruction {idx} contains priceImpactPct: {decoded_data}")
    
    return parsed_instructions

def include_instruction(msg: MessageV0):
    """
    Under development
    """
    from solders.compute_budget import set_compute_unit_limit
    from solana.rpc.api import Client
    from solders.instruction import CompiledInstruction

    # Step 1: Add ComputeBudgetInstruction
    compute_budget_ix = set_compute_unit_limit(1_000_000)  # Set compute unit limit to 1M

    # Step 2: Get a fresh recent ∫blockhash
    client = Client(appconfig.RPC_URL)  # Assuming RpcClient is already imported and available
    recent_blockhash = client.get_latest_blockhash().value.blockhash

    accountKeys = list(msg.account_keys)  # Convert to mutable list
    program_id_index = len(accountKeys)  # Index for the newly added program ID
    accountKeys.append(compute_budget_ix.program_id)  # Append the program ID

    # Map the accounts in compute_budget_ix to their indices in accountKeys
    accounts_indices = [
        accountKeys.index(account) for account in compute_budget_ix.accounts
    ]

    new_instruction = CompiledInstruction(
        program_id_index=program_id_index,
        data=compute_budget_ix.data,
        accounts=bytes(accounts_indices)
    )

    # Ensure the new instruction is not already in the list of instructions
    if new_instruction not in msg.instructions:
        # Add the new instruction to the message
        updated_instructions = list(msg.instructions)  # Convert to mutable list
        updated_instructions.append(new_instruction)

        updated_msg = Message.new_with_compiled_instructions(
            num_required_signatures=msg.header.num_required_signatures,
            num_readonly_signed_accounts=msg.header.num_readonly_signed_accounts,
            num_readonly_unsigned_accounts=msg.header.num_readonly_unsigned_accounts,
            account_keys=accountKeys,
            recent_blockhash=recent_blockhash,
            instructions=updated_instructions
        )
        msg = updated_msg
    else:
        print("Duplicate instruction detected, skipping.")
    return msg

def stamp_time(time: datetime, time_stored: dict = None) -> dict:
    time_stored = {} if time_stored is None else time_stored
    tstamp = time.strftime("%Y%m%d%H%M%S")
    if tstamp not in time_stored:
        time_stored[tstamp] = 1
    else:
        time_stored[tstamp] += 1

    return time_stored

def get_solana_price() -> float:
    """
    Retrieves the current Solana price in USD using a public API.

    Returns:
        float: Current Solana price in USD.
    """
    retries = 5
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
    try:
        response = requests.post(
                url=appconfig.RPC_URL_HELIUS,
                json=data,
                headers={"Content-Type": "application/json"}
            )
        if response.status_code != 200:
            print("get_metadata: Bad status code '{}' recevied for token {}".format(
                    response.status_code,
                    token_address
                )
            )
            return metadata
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
            metadata["price_info"] = 0
            metadata["insufficient_data"] = True

    except Exception as e:
        print("get_metadata: Error retrieving metadata for token {}".format(token_address))
    return metadata




async def test():
    solana_address = "4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb"
    #solana_address = "onK5ruraCpbvjzWjqvJ3uBXgXapNX6ddB799qsNipeR"
    accounts = await get_token_accounts_by_owner(wallet_address=solana_address)

    token_address = "FFqR2bk3ULB1WuYECRbooxPpbYvvZBp3z9Uc94Pqpump"
    metadata = get_token_metadata(token_address=token_address)
    print(metadata)

    
    account = "DnJaA2C7Ak93HGvACoCQ9ULacYuq7BuiYMWtWePekzJH"
    account = None
    token_accounts = await count_associated_token_accounts(wallet_pubkey=Pubkey.from_string(solana_address))
    print("Accounts: {}".format(token_accounts))
    token_accounts_data = await detect_dust_token_accounts(
        wallet_pubkey=Pubkey.from_string(solana_address),
        token_mint_addres=account
    )
    print("USD being held: {}".format(
        sum(account["sol_balance_usd"] for account in token_accounts_data if account["is_dust"])
    ))
    print("Sols being held: {}".format(
        sum(account["sol_balance"] for account in token_accounts_data if account["is_dust"])
    ))

import asyncio
asyncio.run(test())