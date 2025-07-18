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
from solana.rpc.types import TxOpts
from solana.rpc.commitment import Confirmed

from solders.message import Message, MessageV0
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.compute_budget import set_compute_unit_price
from solders.transaction import Transaction
from solders.account import Account
from solders.rpc.responses import RpcResponseContext, GetAccountInfoResp

from spl.token._layouts import MINT_LAYOUT
from spl.token.instructions import (
    burn_checked,
    close_account,
    CloseAccountParams,
    get_associated_token_address,
    BurnCheckedParams,
)

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
    client = Client(appconfig.JITO_RPC_URL)  # Assuming RpcClient is already imported and available
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
        except Exception:
            counter += 1
            print("get_solana_price Error: Failed to fetch Solana price. retriying {} of {}".format(
                counter,
                retries
            ))
            time.sleep(counter)

    return price


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

    mint_data = MINT_LAYOUT.parse(response.value.data)
    decimals = mint_data.decimals

    return decimals


async def get_token_accounts_by_owner(wallet_address=str) -> dict:
    response = {}
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
            ))
            return response

        content = response.json()
        response = content["result"]["value"]

        return response
    except Exception as e:
        print("get_token_accounts_by_owner-> Error: {}".format(e))
        return response


def get_token_metadata(token_address: str) -> dict:
    metadata = {}

    data = {
        "jsonrpc": "2.0",
        "id": "test",
        "method": "getAsset",
        "params": {
            "id": token_address
        }
    }
    retries = 5
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
                ))
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

        except Exception:
            counter += 1
            print("get_metadata: Error retrieving metadata for token {}. Retries {} of {}".format(
                token_address,
                counter,
                retries
            ))
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
    token_mint_address: str = None,
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
            counter += 1

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
        print(f"Error fetching token '{token_mint_address}' balance: {e}")
        return account_output


async def burn_associated_token_account(
    token: Pubkey,
    keypair: Keypair,
    token_authority: Pubkey,
    decimals: int = 0,
    amount: float = None
) -> str:
    """
    Burs all tokens from the associated token account
    :param token[Pubkey]: associated token account
    :param keypair[Keypair]: signer and account owner
    :param token_authority[Pubkey]: token authority
    :param decimals: [int] The number of decimals for the token.
    :param amount[float] = None. Burn the exact amount 
    :return: [str] transaction signature.
    """
    txn = None
    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
        try:
            token_programm = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")  # SPL Token program ID
            # Get associated token account
            associated_token_account = get_associated_token_address(
                owner=keypair.pubkey(),
                mint=token
            )

            # Check if the associated token account exists
            response = await client.get_account_info(associated_token_account)
            account_info = response.value
            if not account_info:
                print("Associated token account {} does not exist.".format(
                    associated_token_account
                ))
                return txn

            data = account_info.data
            if len(data) != 165:
                print("burn_associated_token_account-> Error: Invalid data length for SPL associated account {} for token {}".format(
                    str(associated_token_account),
                    str(token)
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
            lamports = amount_lamports
            owner = owner
            # Convert amount to integer based on token decimals
            if amount is None:
                amount = lamports 
            else:
                amount = int(amount * (10 ** decimals))

            # Construct the burn instruction
            params = BurnCheckedParams(
                program_id=token_programm,
                mint=token,
                account=associated_token_account,
                owner=keypair.pubkey(),
                amount=amount,
                decimals=decimals,
                signers=[keypair.pubkey()]
            )
            burn_ix = burn_checked(params=params)

            # Create and sign transaction
            blockhash = await client.get_latest_blockhash()
            recent_blockhash = blockhash.value.blockhash

            msg = Message(
                instructions=[set_compute_unit_price(1_000), burn_ix],
                payer=keypair.pubkey()
            )
            tx_signature = await client.send_transaction(
                txn=Transaction([keypair], msg, recent_blockhash),
                opts=TxOpts(preflight_commitment=Confirmed),
            )
            current_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
            print("Trade->{} Transaction: https://solscan.io/tx/{} at {}".format(
                "Burn",
                tx_signature.value,
                current_time
            ))
            await client.confirm_transaction(tx_signature.value, commitment="confirmed")
            print("Transaction confirmed")

        except Exception as e:
            print("burn_associated_token_account Error: {}".format(e))

    return txn


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
            lamports = amount_lamports
            owner = owner
            amount = lamports 

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


def generate_vanity_wallet(prefix: str, key_sensitive: bool = False) -> Keypair:
    counter = 0
    start_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
    print("starting generate_vanity_wallet at {}".format(start_time))
    while True:
        counter += 1
        # Generate a new keypair
        keypair = Keypair()
        public_key = str(keypair.pubkey())

        # Check if the public key starts with the desired prefix
        validator = public_key.lower().startswith(prefix.lower()) if not key_sensitive else public_key.startswith(prefix)

        if validator:
            stop_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
            print("Pubkey: {}".format(public_key))
            pk = base58.b58encode(bytes(keypair)).decode()
            print("PK: {}".format(pk))
            print("finishing generate_vanity_wallet at {} after {} iterations".format(
                stop_time,
                counter
            ))
            return keypair


def get_account_information(account: Pubkey) -> GetAccountInfoResp:
    """
    Fetch account information from Solana RPC and return it as a GetAccountInfoResp object.

    Args:
        rpc_url (str): The Solana RPC URL.
        account (str): The account public key in string format.

    Returns:
        GetAccountInfoResp: The account information as a GetAccountInfoResp object.
    """
    # Prepare the JSON body for the POST request
    json_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [
            str(account),  # The account public key
            {"encoding": "base64"}  # Response encoding
        ]
    }

    json_response = []
    loop_counter = 0
    while loop_counter < appconfig.TRADING_RETRIES:
        try:
            # Send the POST request
            response = requests.post(
                appconfig.RPC_URL_HELIUS,
                headers={"Content-Type": "application/json"},
                json=json_body
            )
            response.raise_for_status()  # Raise HTTPStatusError for non-2xx responses

            # Parse the JSON response
            json_response = response.json()
            if "result" not in json_response:
                loop_counter += 1
                time.sleep(2)
                continue
            if "value" in json_response["result"] and not json_response["result"]["value"]:
                loop_counter += 1
                time.sleep(2)
                continue

            break
        except Exception as e:
            print("get_account_information-> Exception: {}".format(str(e)))
            loop_counter += 1

    # Validate the response structure
    if "result" not in json_response:
        raise ValueError("Invalid response: 'result' field not found")

    result = json_response["result"]
    if "value" not in result or "context" not in result:
        raise ValueError("Invalid response: 'value' or 'context' field not found")

    # Extract and process account information
    context = RpcResponseContext(slot=result["context"]["slot"])

    # Check if account data exists
    account_data = result["value"]
    if account_data is None:
        account_info = None
    else:
        # Decode the account information
        lamports = account_data["lamports"]
        owner = Pubkey.from_string(account_data["owner"])
        executable = account_data["executable"]
        rent_epoch = account_data["rentEpoch"]
        data = account_data["data"][0]  # Account data in base64 format
        encoding = account_data["data"][1]  # Should be "base64"

        if encoding != "base64":
            raise ValueError(f"Unexpected encoding: {encoding}")

        # Create AccountInfo object
        account_info = Account(
            lamports=lamports,
            owner=owner,
            executable=executable,
            rent_epoch=rent_epoch,
            data=base64.b64decode(data)
        )

    # Construct the GetAccountInfoResp object
    account_info_resp = GetAccountInfoResp(context=context, value=account_info)

    return account_info_resp


from solders.transaction import VersionedTransaction


def derive_creator_vault(mint: Pubkey, program_id: Pubkey) -> Pubkey:
    seeds = [
        b"creator-vault",
        bytes(mint),
    ]
    vault_pda, _ = Pubkey.find_program_address(seeds, program_id)
    return vault_pda


def load_idl(file_path):
    with open(file_path, 'r') as f:
        return json.load(f)


def decode_create_instruction(ix_data, ix_def, accounts):
    args = {}
    offset = 8  # Skip 8-byte discriminator
    try:
        for arg in ix_def['args']:
            if arg['type'] == 'string':
                length = struct.unpack_from('<I', ix_data, offset)[0]
                offset += 4
                value = ix_data[offset:offset + length].decode('utf-8')
                offset += length
            elif arg['type'] == 'publicKey':
                value = base64.b64encode(ix_data[offset:offset + 32]).decode('utf-8')
                offset += 32
            else:
                raise ValueError(f"Unsupported type: {arg['type']}")

            args[arg['name']] = value

        # Add accounts
        args['mint'] = str(accounts[0])
        args['bondingCurve'] = str(accounts[2])
        args['associatedBondingCurve'] = str(accounts[3])
        args['developer'] = str(accounts[7])
        args['rent'] = str(accounts[11])
    except Exception as e:
        print("decode_create_instruction-> Error: {}".format(e))

    return args


def decode_buy_instruction(ix_data, ix_def, accounts):
    args = {}
    offset = 8  # Skip 8-byte discriminator

    try:
        for arg in ix_def['args']:
            arg_type = arg['type']
            arg_name = arg['name']

            if arg_type == 'string':
                length = struct.unpack_from('<I', ix_data, offset)[0]
                offset += 4
                value = ix_data[offset:offset + length].decode('utf-8')
                offset += length
            elif arg_type == 'publicKey':
                value = base64.b64encode(ix_data[offset:offset + 32]).decode('utf-8')
                offset += 32
            elif arg_type == 'u64':
                value = struct.unpack_from('<Q', ix_data, offset)[0]
                offset += 8
            elif arg_type == 'bool':
                value = struct.unpack_from('<?', ix_data, offset)[0]
                offset += 1
            else:
                raise ValueError(f"Unsupported type: {arg_type}")

            args[arg_name] = value

        # Map accounts to argument names

        args['pump_fee_account'] = str(accounts[1])
        args['mint'] = str(accounts[2])
        args['pump_bunding_curve'] = str(accounts[3])
        args['token_vault'] = str(accounts[4])
        args['token_account'] = str(accounts[5])
        args['buyer'] = str(accounts[6])
        args['creator_vault'] = str(accounts[9])

    except Exception as e:
        print("decode_buy_instruction-> Error: {}".format(e))
    # args['token_account'] = str(accounts[2])

    return args


def get_token_data_from_block(block, threshold, min_scam_buyers) -> dict:
    token_data = {}
    decoded_args = {}
    idl = load_idl('bot/idl/pump_fun_idl.json')
    create_discriminator = 8576854823835016728
    buy_discriminator = 16927863322537952870
    tradable_tokens = []
    buyers = []

    for tx_with_meta in block.value.transactions:
        encoded_tx = tx_with_meta.transaction
        if encoded_tx.message:
            instructions = encoded_tx.message.instructions
            for ix in instructions:
                program_id = str(ix.program_id)
                if program_id == str(appconfig.PUMP_PROGRAM):
                    ix_data = base58.b58decode(ix.data)
                    discriminator = struct.unpack('<Q', ix_data[:8])[0]

                    account_keys = []
                    if discriminator == create_discriminator:
                        create_ix = next(
                            instr for instr in idl['instructions'] if instr['name'] == 'create'
                        )
                        try:
                            for index in ix.accounts:
                                for account_key in tx_with_meta.transaction.message.account_keys:
                                    if str(index) == str(account_key.pubkey):
                                        account_keys.append(str(account_key.pubkey))
                                        continue
                        except Exception:
                            print("Create Error: Mismatch between ix.accounts(${}) and account_keys".format(
                                len(ix.accounts)),
                                len(tx_with_meta.transaction.message.account_keys)
                            )
                            continue

                        decoded_args = decode_create_instruction(
                            ix_data,
                            create_ix,
                            account_keys
                        )
                        if not decoded_args:
                            break

                        if "mint" not in decoded_args:
                            break

                        decoded_args["block"] = block.value.parent_slot + 1
                        decoded_args["blockTime"] = block.value.block_time
                        decoded_args["buyers"] = []
                        decoded_args["seen_buyers"] = set()

                        token_data = {
                            decoded_args["mint"]: decoded_args.copy(),
                        }
                        continue

                    # We'll check on BUYs after having a new token created
                    if decoded_args and discriminator == buy_discriminator:
                        buy_ix = next(
                            instr for instr in idl['instructions'] if instr['name'] == 'buy'
                        )
                        try:
                            for index in ix.accounts:
                                for account_key in tx_with_meta.transaction.message.account_keys:
                                    if str(index) == str(account_key.pubkey):
                                        account_keys.append(str(account_key.pubkey))
                                        continue
                        except Exception:
                            print("Buy Error: Mismatch between ix.accounts(${}) and account_keys".format(
                                len(ix.accounts)),
                                len(tx_with_meta.transaction.message.account_keys)
                            )
                            continue

                        decoded_buy_args = decode_buy_instruction(
                            ix_data,
                            buy_ix,
                            account_keys
                        )

                        if decoded_buy_args.get('mint', '') in token_data:
                            buyer = decoded_buy_args.get('buyer')
                            tokens_bought = decoded_buy_args.get('amount')
                            sol_traded = decoded_buy_args.get('maxSolCost')
                            creator_vault = decoded_buy_args.get('creator_vault')

                            developer = decoded_args.get("developer")
                            trader = "developer" if developer == buyer else "sniper"
                            if buyer not in token_data[decoded_buy_args.get('mint')]["seen_buyers"]:  # noqa: E501
                                # Add the buyer to the set
                                token_data[decoded_buy_args.get('mint')]["seen_buyers"].add(buyer)  # noqa: E501
                                token_data[decoded_buy_args.get('mint')]["buyers"].append({
                                    'buyer': buyer,
                                    'trader': trader,
                                    'tokens_bought': tokens_bought / 10**6,
                                    'sol_traded': (sol_traded / 10**9) / 1.01,  # taking out Pump.fun fee  # noqa: E501
                                    'creator_vault': creator_vault
                                })

                        continue

    if token_data:
        if len(list(token_data.keys())) > 1:
            print("-> Tokens: {}".format(len(list(token_data.keys()))))

        for token, data in token_data.items():
            print("-> Checking on token {}".format(token))
            total_tokens_bought = sum(
                buyer["tokens_bought"] for buyer in data.get("buyers", [])
            )
            if total_tokens_bought >= threshold:
                start_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
                if (len(data.get("buyers", [])) > min_scam_buyers):
                    print("{} Scam 'BIG' token found. Tokens bought {}".format(
                        start_time,
                        total_tokens_bought
                    ))
                    tradable_tokens.append(data)
                elif (len(data.get("buyers", [])) == 1):
                    print("{} Whale found. Tokens bought {}".format(
                        start_time,
                        total_tokens_bought
                    ))
                    tradable_tokens.append(data)
                else:
                    print(" Mix found: developer plus some sniper bots. Discarting token...")
            # else:
            #     print("*** TESTING token...")
            #     tradable_tokens.append(data)

    return tradable_tokens


# 👇 Sample re-derivation (this is illustrative, your actual seeds may vary)
def get_associated_bonding_curve(bonding_curve: Pubkey, mint: Pubkey, program_id: Pubkey):
    seed1 = b"bonding"
    seed2 = bytes(bonding_curve)
    seed3 = bytes(mint)
    try:
        return Pubkey.find_program_address([seed1, seed2, seed3], program_id)[0]
    except Exception as e:
        print("get_associated_bonding_curve Exception: {}".format(e))
        return None


async def test():
    prefix = "Ghost"

    # Generate the vanity wallet
    print(f"Generating wallet with prefix '{prefix}'...")
    keypair = generate_vanity_wallet(prefix, key_sensitive=True)

    if keypair:
        return

    solana_address = "4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb"
    # solana_address = "onK5ruraCpbvjzWjqvJ3uBXgXapNX6ddB799qsNipeR"
    token_address = "FFqR2bk3ULB1WuYECRbooxPpbYvvZBp3z9Uc94Pqpump"
    token_address = "7AeGaYhyhvDRdPkH7Wg7vup8D1SjNRZc1fXLZNcYpump"

    # metadata = get_token_metadata(token_address=token_address)
    # print(metadata)
    # txn = await burn_associated_token_account(
    #     token=Pubkey.from_string("DCmtjvp36JDAmsURBRY4jz5A8PoEXsxaFEAgu7CBpump"),
    #     keypair=Keypair.from_base58_string(appconfig.PRIVKEY),
    #     token_authority=Pubkey.from_string("TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"),
    #     decimals=6,
    #     amount=None
    # )

    associated_token_account = "D4fHjGpq7yzVm7RSGVkfkMGfixR8HTErJgLbD3GV5k6J"
    token_address = "ErNXfdqTCXBE3H4MAHqULWdZsTbnrjsHcoCGPnkmpump"
    txn = await burn_and_close_associated_token_account(
        associated_token_account=Pubkey.from_string(associated_token_account),
        token_mint=Pubkey.from_string(token_address),
        keypair=Keypair.from_base58_string(appconfig.PRIVKEY),
        decimals=6
    )

    account = "DnJaA2C7Ak93HGvACoCQ9ULacYuq7BuiYMWtWePekzJH"
    account = None
    token_accounts = await count_associated_token_accounts(wallet_pubkey=Pubkey.from_string(solana_address))
    print("Accounts: {}".format(token_accounts))
    time.sleep(2)
    token_accounts_data = await detect_dust_token_accounts(
        wallet_pubkey=Pubkey.from_string(solana_address),
        token_mint_address=account
    )
    print("USD being held: {}".format(
        sum(account["sol_balance_usd"] for account in token_accounts_data if account["is_dust"])
    ))
    print("Sols being held: {}".format(
        sum(account["sol_balance"] for account in token_accounts_data if account["is_dust"])
    ))

# import asyncio
# asyncio.run(test())
