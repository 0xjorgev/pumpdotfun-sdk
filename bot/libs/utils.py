import base58
import base64
import json
import struct

from datetime import datetime
from enum import Enum
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solders.message import Message, MessageV0
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

async def get_own_token_balance(wallet_pubkey: Pubkey, token_mint_addres: str) -> float:
    """
    Fetches the balance of a specific token in a given Solana wallet.

    :param wallet_pubkey: The public address of the Solana wallet.
    :param token_mint_pubkey: The mint address of the token to query.
    :return: Token balance as a float.
    """
    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
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
