import base64
import json
import math
import random
import requests
import struct
import time

from datetime import datetime
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from solana.rpc.commitment import Confirmed

from solders.compute_budget import (
    # request_heap_frame,
    set_compute_unit_limit,
    set_compute_unit_price
)
from solders.instruction import Instruction, AccountMeta
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction

from spl.token.instructions import (
    burn_checked,
    BurnCheckedParams,
    close_account,
    CloseAccountParams
)
from spl.token.constants import ASSOCIATED_TOKEN_PROGRAM_ID, TOKEN_PROGRAM_ID
from api.config import appconfig
from api.handlers.exceptions import EntityNotFoundException
# from bot.app.api.config import appconfig
# from bot.app.api.handlers.exceptions import EntityNotFoundException


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
    current_source = 0
    while True:
        try:
            if counter >= retries:
                break

            source = appconfig.SOL_USD_QUOTE[current_source]
            response = requests.get(source["url"])
            response.raise_for_status()
            price_data = response.json()
            price = 0
            match source["vendor"]:
                case "coingecko":
                    price = price_data["solana"]["usd"]
                case "jupiter":
                    price = round(float(price_data["swapUsdValue"]), 2)
            break
        except Exception:
            counter += 1
            current_source = 0 if current_source >= len(appconfig.SOL_USD_QUOTE) else current_source + 1
            print("get_solana_price Error: Failed to fetch Solana price. Retriying now with {}. Retrying {} of {} times".format(
                appconfig.SOL_USD_QUOTE[current_source]["vendor"],
                counter,
                retries
            ))
            time.sleep(counter)

    return price


async def get_token_accounts_by_owner(wallet_address=str) -> list[dict]:
    value = []
    data = {
        "jsonrpc": "2.0",
        "id": "test",
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_address,
            {
                "programId": str(TOKEN_PROGRAM_ID)
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
            print("get_token_accounts_by_owner: Bad status code '{}' received for token {}".format(
                response.status_code,
                wallet_address
            ))
            return value

        content = response.json()
        value = content["result"]["value"]

        return value
    except Exception as e:
        print("get_token_accounts_by_owner-> Error: {}".format(e))
        return value


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
                ))
                time.sleep(counter)
                continue

            content = response.json()
            file_dict = {'uri': None, 'cdn_uri': None, 'mime': None}
            files = content["result"]["content"]["files"]
            metadata.update(files[0] if files else file_dict)
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


def get_current_ghostfunds_fees(burnable_accounts: int) -> float:
    """
    Return GhostFunds fee based on how many ata can be burned.
    :param burnable_accounts [int]: how many atas
    :return [float]: fee percentage
    """
    fee = 0
    # Validate input
    if burnable_accounts <= 0:
        return fee

    # Iterate through the fee tiers to find the applicable fee
    for upper_limit, ghost_fee in sorted(appconfig.GHOSTFUNDS_FEES_PERCENTAGES.items()):
        if burnable_accounts > upper_limit:
            fee = ghost_fee
            continue
        return fee

    # If the burnable_accounts exceed the highest limit, return the lowest fee
    return appconfig.GHOSTFUNDS_FEES_PERCENTAGES[max(appconfig.GHOSTFUNDS_FEES_PERCENTAGES.keys())]


async def count_associated_token_accounts(
    wallet_pubkey: Pubkey
) -> dict:
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
        "rent_balance_usd": 0,
        "fee": 0,
        "msg": None
    }
    min_token_value = appconfig.MIN_TOKEN_VALUE
    account_samples = 5

    # TODO: implement token's black list (like USDC, etc)
    token_blacklist = []

    original_accounts = []
    counter = 0
    while True:
        if counter >= appconfig.RETRIES:
            break
        original_accounts = await get_token_accounts_by_owner(wallet_address=str(wallet_pubkey))
        if original_accounts:
            break
        counter += 1

    usd_sol_value = 0

    accounts = [
        account for account in original_accounts
        if account["account"]["data"]["parsed"]["info"]["mint"] not in token_blacklist
    ]

    # Safety trimming: big accounts can crash the api server
    total["total_accounts"] = len(accounts)
    if len(accounts) >= appconfig.MAX_RETRIEVABLE_ACCOUNTS:
        accounts = accounts[0: appconfig.MAX_RETRIEVABLE_ACCOUNTS]
        total["msg"] = appconfig.MAX_RETRIEVABLE_ACCOUNTS_MESSAGE

    if accounts:
        usd_sol_value = get_solana_price()
        if usd_sol_value == 0:
            return total
        # Calculating accounts balance as AN APROXIMATION to speed up this process
        account_sample_list = list(range(len(accounts)))
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
        # mint = account["account"]["data"]["parsed"]["info"]["mint"]
        token_ammount = account["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]

        token_value = 1
        if token_ammount * token_value < min_token_value:
            total["burnable_accounts"] += 1
        # else:
        #     print("token {} has significan value".format(mint))

    total["accounts_for_manual_review"] = accounts_for_manual_review

    if total["burnable_accounts"] > 0:
        total["fee"] = get_current_ghostfunds_fees(burnable_accounts=total["burnable_accounts"])

    return total


async def detect_dust_token_accounts(
    wallet_pubkey: Pubkey,
    do_balance_aproximation: bool = True,
    page: int = appconfig.DEFAULT_PAGE,
    items_per_page: int = appconfig.DEFAULT_ITEMS_PER_PAGE
) -> tuple[list[dict], int, int]:
    """
    Fetches the balance of a specific token in a given Solana wallet.

    :param wallet_pubkey: The public address of the Solana wallet.
    :return: Token balance as a float.
    """
    min_token_value = appconfig.MIN_TOKEN_VALUE
    account_samples = 5
    working_balance = 0
    account_output = []
    # Refactor this: remove this line of code and test as client is not being used
    try:
        total_items = 0
        # TODO: implement token's black list (like USDC, etc)
        token_blacklist = []
        original_accounts = await get_token_accounts_by_owner(wallet_address=str(wallet_pubkey))
        accounts = [
            account for account in original_accounts
            if account["account"]["data"]["parsed"]["info"]["mint"] not in token_blacklist
        ]

        if not accounts:
            return [], page, total_items

        if len(accounts) >= appconfig.MAX_RETRIEVABLE_ACCOUNTS:
            print("Warning: Big account detected {} holding {} atas".format(
                str(wallet_pubkey),
                len(accounts)
            ))
            accounts = accounts[0: appconfig.MAX_RETRIEVABLE_ACCOUNTS]

        # Fetch the current Solana price
        sol_price = get_solana_price()
        if sol_price == 0:
            return [], page, total_items

        account_sample_list = list(range(len(accounts)))
        if do_balance_aproximation:
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

        # Sort ATAs by mint address (this will help with the pagination)
        sorted_accounts = sorted(
            accounts,
            key=lambda x: x["account"]["data"]["parsed"]["info"]["mint"]
        )

        # Pagination
        total_items = len(sorted_accounts)
        # We can't expect to have more items in a page than what we have.
        # Ex: can't have 50 page items on 10 items in total
        total_pages = math.ceil(total_items / items_per_page) if items_per_page < total_items else total_items
        # can't work with pages greater than the total pages we're dealing with
        page = total_pages if page > total_pages else page

        start_index = (page - 1) * items_per_page
        end_index = start_index + items_per_page if start_index + items_per_page < total_items else total_items

        # Paginate the list
        sorted_accounts = sorted_accounts[start_index:end_index]

        counter = 0
        for account in sorted_accounts:
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
            supply = metadata["supply"]
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

        return account_output, page, total_items

    except Exception as e:
        print(f"Error fetching associated token accounts for account '{str(wallet_pubkey)}' balance: {e}")
        return account_output, page, total_items


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
                raise txn_signature

            # BURN
            data = account_info.data
            if len(data) != 165:
                print("burn_associated_token_account-> Error: Invalid data length for ATA {} for token {}".format(
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
            ) = struct.unpack("<32s32sQ4s32sB4sQ8s4s32s", data)
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


def get_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """Derives the associated token address for the given wallet address and token mint.

    Returns:
        The public key of the derived associated token address.
    """
    key, _ = Pubkey.find_program_address(
        seeds=[bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
        program_id=ASSOCIATED_TOKEN_PROGRAM_ID,
    )
    return key


async def close_ata_transaction(
    owner: Pubkey,
    tokens: list[dict],
    fee: float,
    encode_base64: bool = True
) -> str:
    """
    Burs all tokens from the associated token account
    :param associated_token_account[Pubkey]: associated token account
    :param token_mint[Pubkey]: tokens to get burned
    :param decimals[int]: The token's decimals (default 9 for SOL).
    :return: [str] base64 transaction object by default.
    """
    txn = None
    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
        try:
            # Will set both burn and close intructions for every ATA
            burn_close_instructions = []
            for token in tokens:
                associated_token_account = get_associated_token_address(
                    owner=owner,
                    mint=Pubkey.from_string(token.token_mint)
                )
                response = await client.get_account_info(associated_token_account)
                account_info = response.value
                if not account_info:
                    print("Associated token account {} does not exist.".format(
                        associated_token_account
                    ))
                    raise EntityNotFoundException(
                        detail="Associated token account {} nor found.".format(
                            str(associated_token_account)
                        )
                    )

                # BURN
                data = account_info.data
                if len(data) != 165:
                    print("close_burn_ata_instructions-> Error: Invalid data length for ATA {} for token {}".format(
                        str(associated_token_account),
                        token.token_mint
                    ))
                (
                    mint,
                    owner_data,
                    amount_lamports,
                    delegate_option,
                    delegate,
                    state,
                    is_native_option,
                    is_native,
                    delegated_amount,
                    close_authority_option,
                    close_authority
                ) = struct.unpack("<32s32sQ4s32sB4sQ8s4s32s", data)

                amount = amount_lamports
                mint = token.token_mint
                decimals = token.decimals

                # Construct the burn instruction
                params = BurnCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    mint=Pubkey.from_string(mint),
                    account=associated_token_account,
                    owner=owner,
                    amount=amount,
                    decimals=decimals,
                    signers=[owner]
                )
                burn_ix = burn_checked(params=params)
                # burn_ix_bytes = bytes(burn_ix)

                # CLOSE
                # Create the close account instruction
                close_ix = close_account(
                    CloseAccountParams(
                        program_id=TOKEN_PROGRAM_ID,
                        account=associated_token_account,
                        dest=owner,
                        owner=owner
                    )
                )
                # close_ix_bytes = bytes(close_ix)

                burn_close_instructions.append(burn_ix)
                burn_close_instructions.append(close_ix)

            # Required instructions to set compute unit limit and price
            compute_unit_price_ix = set_compute_unit_price(5_000)
            # compute_unit_price_ix_bytes = bytes(compute_unit_price_ix)

            compute_units = calculate_compute_units(atas=len(tokens))
            compute_unit_limit_ix = set_compute_unit_limit(units=compute_units)
            # compute_unit_limit_ix_bytes = bytes(compute_unit_limit_ix)

            # Variable fee
            # Summing all ATAs balances to calculate variable fee
            fee_ix_list = get_fee_instructions(
                fee=fee,
                balance=sum(token.balance for token in tokens),
                owner=owner,
                atas=len(tokens)
            )
            # fee_ix_list_bytes = [bytes(fee_ix) for fee_ix in fee_ix_list]

            # Package all instructions as hex values from bytes into a single list
            instructions = [
                compute_unit_price_ix,  # Convert to hex for compatibility
                compute_unit_limit_ix,
            ]
            instructions.extend(burn_close_instructions)
            instructions.extend(fee_ix_list)

            blockhash = await client.get_latest_blockhash()
            recent_blockhash = blockhash.value.blockhash
            msg = Message.new_with_blockhash(
                instructions=instructions,
                payer=owner,
                blockhash=recent_blockhash
            )

            tx = Transaction.new_unsigned(message=msg)
            txn = bytes(tx)
            if encode_base64:
                txn = base64.b64encode(txn).decode('ascii')

            # from solders.message import MessageV0
            # from solders.transaction import VersionedTransaction

            # tx = VersionedTransaction.populate(message=msg, signatures=[])
            # # tx = VersionedTransaction(message=msg, keypairs=[])
            # txn = bytes(tx)
            # if encode_base64:
            #     txn = base64.b64encode(txn).decode('ascii')

        except EntityNotFoundException as enfe:
            raise enfe
        except Exception as e:
            print("request_close_ata_instruction Error: {}".format(e))

    return txn


def get_fee_instructions(
    fee: float,
    balance: float,
    owner: Pubkey,
    atas: int
) -> list[Instruction]:
    # Fix fee: we're charing a base fix fee for every ATA we're burning and closing.
    lamports_to_charge = int(appconfig.GHOSTFUNDS_FIX_FEES * atas * 10**9)  # Convert SOL to lamports
    fix_fees_params = TransferParams(
        from_pubkey=owner,
        to_pubkey=Pubkey.from_string(appconfig.GHOSTFUNDS_FIX_FEES_RECEIVER),
        lamports=lamports_to_charge
    )
    fix_fees_ix = transfer(params=fix_fees_params)
    # Variable fee
    lamports_to_charge = int(balance * fee * 10**9)                  # Convert SOL to lamports
    variable_fees_params = TransferParams(
        from_pubkey=owner,
        to_pubkey=Pubkey.from_string(appconfig.GHOSTFUNDS_VARIABLE_FEES_RECEIVER),
        lamports=lamports_to_charge
    )
    variable_fees_ix = transfer(params=variable_fees_params)
    return [fix_fees_ix, variable_fees_ix]


def calculate_compute_units(atas: int):
    # Units consumed by each instruction
    burn_checked_units = 4742
    close_account_units = 2916
    other_instruction_units = 1000  # Adjust based on your use case

    # Total units required
    total_units = atas * (burn_checked_units + close_account_units) + other_instruction_units

    # Add a buffer for safety
    buffer_units = 1000
    return total_units + buffer_units


async def close_burn_ata_instructions(
    owner: Pubkey,
    tokens: list[dict],
    fee: float,
) -> list[hex]:
    """
    Burs all tokens from the associated token account
    :param owner[Pubkey]: ATA account owner
    :param tokens[list[dict]]: List of dicts that will hold the following information:
           token_mint[Pubkey]: tokens to get burned
           decimals[int]: The token's decimals (default 9 for SOL).
           balance[float]: The ATA Sol balance (for fee calculation)
    :param fee[float]: GhostFunds fee to be charge to user.
    :return: [str] base64 list with all the instructions in hex format.
    """
    instructions = None

    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
        try:
            # Will set both burn and close intructions for every ATA
            burn_close_instructions_hex = []
            for token in tokens:
                associated_token_account = get_associated_token_address(
                    owner=owner,
                    mint=Pubkey.from_string(token["token_mint"])
                )
                response = await client.get_account_info(associated_token_account)
                account_info = response.value
                if not account_info:
                    print("Associated token account {} does not exist.".format(
                        associated_token_account
                    ))
                    raise EntityNotFoundException(
                        detail="Associated token account {} nor found.".format(
                            str(associated_token_account)
                        )
                    )

                # BURN
                data = account_info.data
                if len(data) != 165:
                    print("close_burn_ata_instructions-> Error: Invalid data length for ATA {} for token {}".format(
                        str(associated_token_account),
                        token["token_mint"]
                    ))
                (
                    mint,
                    owner_data,
                    amount_lamports,
                    delegate_option,
                    delegate,
                    state,
                    is_native_option,
                    is_native,
                    delegated_amount,
                    close_authority_option,
                    close_authority
                ) = struct.unpack("<32s32sQ4s32sB4sQ8s4s32s", data)

                amount = amount_lamports

                # Construct the burn instruction
                params = BurnCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    mint=Pubkey.from_string(token["token_mint"]),
                    account=associated_token_account,
                    owner=owner,
                    amount=amount,
                    decimals=token["decimals"],
                    signers=[owner]
                )
                burn_ix = burn_checked(params=params)
                burn_ix_bytes = bytes(burn_ix)

                # CLOSE
                # Create the close account instruction
                close_ix = close_account(
                    CloseAccountParams(
                        program_id=TOKEN_PROGRAM_ID,
                        account=associated_token_account,
                        dest=owner,
                        owner=owner
                    )
                )
                close_ix_bytes = bytes(close_ix)

                burn_close_instructions_hex.append(burn_ix_bytes.hex())
                burn_close_instructions_hex.append(close_ix_bytes.hex())

            # Required instructions to set compute unit limit and price
            compute_unit_price_ix = set_compute_unit_price(5_000)
            compute_unit_price_ix_bytes = bytes(compute_unit_price_ix)

            compute_units = calculate_compute_units(atas=len(tokens))
            compute_unit_limit_ix = set_compute_unit_limit(units=compute_units)
            compute_unit_limit_ix_bytes = bytes(compute_unit_limit_ix)

            # Although this is redundant, we're keeping it.
            # heap_memory_size = 64 * 1024
            # request_heap_frame_ix = request_heap_frame(bytes_=heap_memory_size)
            # request_heap_frame_ix_bytes = bytes(request_heap_frame_ix)

            # Variable fee
            # Summing all ATAs balances to calculate variable fee
            fee_ix_list = get_fee_instructions(
                fee=fee,
                balance=sum(token.get("balance", 0) for token in tokens),
                owner=owner,
                atas=len(tokens)
            )
            fee_ix_list_bytes = [bytes(fee_ix) for fee_ix in fee_ix_list]
            fee_ix_list_hex = [fee_ix_bytes.hex() for fee_ix_bytes in fee_ix_list_bytes]

            # Package all instructions as hex values from bytes into a single list
            instructions = [
                compute_unit_price_ix_bytes.hex(),  # Convert to hex for compatibility
                compute_unit_limit_ix_bytes.hex(),
                # request_heap_frame_ix_bytes.hex(),
            ]
            instructions.extend(burn_close_instructions_hex)
            instructions.extend(fee_ix_list_hex)

        except EntityNotFoundException as enfe:
            raise enfe
        except Exception as e:
            print("request_close_ata_instruction Error: {}".format(e))

    return instructions


async def recover_rent_client_from_transaction(go_local: bool = True):
    from bot.config import appconfig
    keypair = Keypair.from_base58_string(appconfig.PRIVKEY)

    body = {
        "owner": "4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
        "fee": 0.045,
        "tokens": [
            {
                "token_mint": "56B2cJQBdwQvambDvfZZuFp7PPBYMDw71UkgbH1Ppump",
                "decimals": 6,
                "balance": 0.002039
            }
        ],
    }
    try:
        if not go_local:
            response = requests.post(
                url="http://localhost:443/api/associated_token_accounts/burn_and_close/transaction",
                json=body,
                headers={"Content-Type": "application/json"}
            )
            if response.status_code != 200:
                print("recover_rent_client: Bad status code '{}' recevied".format(
                    response.status_code
                ))
                return response

            content = response.json()
            txn_base64 = content["quote"]
        else:
            txn_base64 = await close_ata_transaction(
                owner=Pubkey.from_string(body["owner"]),
                tokens=body["tokens"],
                fee=body["fee"]
            )

        # Decode the Base64 string to bytes
        txn_bytes = base64.b64decode(txn_base64)

        # # Get the message from the transaction
        # msg = vst.message

        # instructions = [
        #     Instruction(
        #         program_id=msg.account_keys[ci.program_id_index],
        #         accounts=[
        #             AccountMeta(pubkey=msg.account_keys[idx], is_signer=idx == 0, is_writable=True)
        #             for idx in ci.accounts
        #         ],
        #         data=ci.data
        #     )
        #     for ci in msg.instructions
        # ]

        # Send the signed transaction (example assumes using a Solana RPC client)
        async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
            blockhash = await client.get_latest_blockhash()
            recent_blockhash = blockhash.value.blockhash

            # Recreate the Transaction object from bytes
            signed_tx = Transaction.from_bytes(txn_bytes)
            signed_tx.sign(keypairs=[keypair], recent_blockhash=recent_blockhash)

            # signed_tx = Transaction.new_signed_with_payer(
            #     instructions=instructions,
            #     payer=keypair.pubkey(),
            #     signing_keypairs=[keypair],
            #     recent_blockhash=recent_blockhash
            # )

            tx_signature = await client.send_transaction(
                txn=signed_tx,
                opts=TxOpts(preflight_commitment=Confirmed)
            )
            print(f"Transaction sent successfully: {tx_signature}")

            current_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
            print("Test->{} Transaction: https://solscan.io/tx/{} at {}".format(
                "Transfer",
                tx_signature.value,
                current_time
            ))
            await client.confirm_transaction(tx_signature.value, commitment="confirmed")
            print("Transaction confirmed")

        return
    except Exception as e:
        print("recover_rent_client_from_transaction-> Error: {}".format(e))
        return


async def recover_rent_client_from_instructions(go_local: bool = True):
    from bot.config import appconfig
    keypair = Keypair.from_base58_string(appconfig.PRIVKEY)

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
    try:
        instructions = []
        if not go_local:
            response = requests.post(
                url="http://3.255.102.199:443/api/associated_token_accounts/burn_and_close/instructions",
                json=body,
                headers={"Content-Type": "application/json"}
            )
            if response.status_code != 200:
                print("recover_rent_client: Bad status code '{}' recevied".format(
                    response.status_code
                ))
                return response

            content = response.json()
            txn_base64 = content["response"]

            # Decode the Base64 string to bytes
            decoded_bytes = base64.b64decode(txn_base64)

            # Step 2: Deserialize JSON to get the list of instructions
            instructions_data = json.loads(decoded_bytes.decode("utf-8"))

        else:
            instructions_data = await close_burn_ata_instructions(
                owner=Pubkey.from_string(body["owner"]),
                tokens=body["tokens"],
                fee=body["fee"]
            )
        print("*** Recovering funds from {} ATAs ***".format(len(instructions_data)))
        # Step 3: Convert each hex string back to bytes
        instructions_bytes = [bytes.fromhex(instruction) for instruction in instructions_data]

        instructions = [Instruction.from_bytes(ix_bytes) for ix_bytes in instructions_bytes]

        # Send the signed transaction (example assumes using a Solana RPC client)
        async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
            blockhash = await client.get_latest_blockhash()
            recent_blockhash = blockhash.value.blockhash

            signed_tx = Transaction.new_signed_with_payer(
                instructions=instructions,
                payer=keypair.pubkey(),
                signing_keypairs=[keypair],
                recent_blockhash=recent_blockhash
            )

            # Simulating the transaction
            simulation_result = await client.simulate_transaction(signed_tx)
            if simulation_result.value.err:
                print("Simulation error:", simulation_result.value.err)

            send_result = None
            tx_signature = await client.send_transaction(
                txn=signed_tx,
                opts=TxOpts(preflight_commitment=Confirmed)
            )
            print(f"Transaction sent successfully: {tx_signature}")

            current_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
            print("Test->{} Transaction: https://solscan.io/tx/{} at {}".format(
                "Transfer",
                tx_signature.value,
                current_time
            ))
            await client.confirm_transaction(tx_signature.value, commitment="confirmed")
            print("Transaction confirmed")

        return send_result
    except Exception as e:
        print("recover_rent_client_from_instructions-> Error: {}".format(e))


# import asyncio
# asyncio.run(recover_rent_client_from_transaction(go_local=False))
