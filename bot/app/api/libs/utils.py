import base64
import json
import logging
import math
import random
import requests
import struct
import time

from api.handlers.exceptions import ErrorProcessingData

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
            logging.error(f"get_solana_balance: Error fetching balance: {e.error_msg}")
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
            current_source = 0 if current_source >= len(appconfig.SOL_USD_QUOTE) - 1 else current_source + 1
            logging.warning("get_solana_price Error: Failed to fetch Solana price. Retriying now with {}. Retrying {} of {} times".format(
                appconfig.SOL_USD_QUOTE[current_source]["vendor"],
                counter,
                retries
            ))
            time.sleep(counter)

    return price


def get_token_accounts_by_owner(wallet_address=str) -> list[dict]:
    print_trace = True
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
        if print_trace:
            logging.info("Requesting getTokenAccountsByOwner for account {}".format(wallet_address))

        response = requests.post(
            url=appconfig.RPC_URL_HELIUS,
            json=data,
            headers={"Content-Type": "application/json"}
        )

        if response.status_code != 200:
            logging.error("get_token_accounts_by_owner: Bad status code '{}' received for wallet {}".format(
                response.status_code,
                wallet_address
            ))
            return value

        content = response.json()
        value = content["result"]["value"]

        if len(value) >= appconfig.MAX_RETRIEVABLE_ACCOUNTS:
            logging.warning("get_token_accounts_by_owner. Warning: Big account detected {} holding {} atas".format(
                str(wallet_address),
                len(value)
            ))
            value = value[0: appconfig.MAX_RETRIEVABLE_ACCOUNTS]

        if print_trace:
            logging.info("getTokenAccountsByOwner: all good, retrieving {} accounts".format(len(value)))

        return value
    except Exception as e:
        logging.error("get_token_accounts_by_owner-> Error: {}".format(e))
        raise ErrorProcessingData(detail=str(e))


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
            metadata = {}
            break

        try:
            response = requests.post(
                url=appconfig.RPC_URL_HELIUS,
                json=data,
                headers={"Content-Type": "application/json"}
            )
            if response.status_code != 200:
                counter += 1
                logging.warning("get_metadata: Bad status code '{}' recevied for token {}. Retries {} of {}".format(
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
            authority = content["result"]["authorities"][0]["address"] if content["result"]["authorities"] else ""
            metadata["authority"] = authority
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
            logging.error("get_metadata: Error retrieving metadata for token {}. Retries {} of {}. Exception: {}".format(
                token_address,
                counter,
                retries,
                e
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
    try:
        min_token_value = appconfig.MIN_TOKEN_VALUE
        account_samples = 3

        # TODO: implement token's black list (like USDC, etc)
        token_blacklist = []

        original_accounts = []
        counter = 0
        while True:
            if counter >= appconfig.RETRIES:
                break
            original_accounts = get_token_accounts_by_owner(wallet_address=str(wallet_pubkey))
            if original_accounts:
                break
            counter += 1

        usd_sol_value = 0

        logging.info("count_associated_token_accounts: Accounts recovered: {} after {} loops".format(
            len(original_accounts),
            counter
        ))

        accounts = [
            account for account in original_accounts
            if account["account"]["data"]["parsed"]["info"]["mint"] not in token_blacklist
        ]

        # Safety trimming: big accounts can crash the api server
        total["total_accounts"] = len(accounts)
        if len(accounts) >= appconfig.MAX_RETRIEVABLE_ACCOUNTS:
            accounts = accounts[0: appconfig.MAX_RETRIEVABLE_ACCOUNTS]
            total["msg"] = appconfig.MAX_RETRIEVABLE_ACCOUNTS_MESSAGE
            logging.info("count_associated_token_accounts: Whale detected: retrieving {} from {} accounts".format(
                len(accounts),
                total["total_accounts"]
            ))

        if accounts:
            logging.info("count_associated_token_accounts: retrieving solana price.")
            usd_sol_value = get_solana_price()
            logging.info("count_associated_token_accounts: solana price is {}.".format(usd_sol_value))
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

            logging.info("count_associated_token_accounts: Rent balance was calcualted to {}".format(
                total["rent_balance"])
            )

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

        logging.info("count_associated_token_accounts: Total: {}".format(total))
        return total
    except Exception as e:
        logging.info("count_associated_token_accounts-> Error: {}".format(str(e)))
        raise ErrorProcessingData(detail=str(e))


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
        original_accounts = get_token_accounts_by_owner(wallet_address=str(wallet_pubkey))
        accounts = [
            account for account in original_accounts
            if account["account"]["data"]["parsed"]["info"]["mint"] not in token_blacklist
        ]

        if not accounts:
            return [], page, total_items

        if len(accounts) >= appconfig.MAX_RETRIEVABLE_ACCOUNTS:
            logging.warning("detect_dust_token_accounts. Warning: Big account detected {} holding {} atas".format(
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
            amount = account["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]
            token_amount = account["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]
            decimals = account["account"]["data"]["parsed"]["info"]["tokenAmount"]["decimals"]
            associated_token_account = account["pubkey"]

            metadata = get_token_metadata(token_address=mint)
            if not metadata:
                continue

            if "name" not in metadata:
                continue

            token_price = metadata["price_info"]["price_per_token"]
            token_value = token_price * token_amount

            uri = metadata.get("uri", "")
            cdn_uri = metadata.get("cdn_uri")
            mime = metadata.get("mime")
            description = metadata.get("description", "")
            name = metadata.get("name", "").strip()
            symbol = metadata.get("symbol", "").strip()
            authority = metadata.get("authority", "")
            supply = metadata.get("supply", "")
            token_program = metadata.get("token_program", "")
            insufficient_data = metadata.get("insufficient_data", "")  # Non listed tokens returns a zero price

            account_output.append(
                {
                    "token_mint": mint,
                    "associated_token_account": associated_token_account,
                    "owner": owner,
                    "token_amount_lamports": int(amount),
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
        logging.error(f"detect_dust_token_accounts. Error fetching associated token accounts for account '{str(wallet_pubkey)}' balance: {e}")  # noqa: 501
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
                logging.warning("Associated token account {} does not exist.".format(
                    associated_token_account
                ))
                raise txn_signature

            # BURN
            data = account_info.data
            if len(data) != 165:
                logging.error("burn_associated_token_account-> Error: Invalid data length for ATA {} for token {}".format(  # noqa: 501
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
    referrals: list[dict],
    encode_base64: bool = True
) -> list[str]:
    """
    Closes an Associated Token Account (ATA) transaction for a given owner.

    Args:
        owner (Pubkey): The public key of the account owner.
        tokens (list of dict): A list of dictionaries, each containing details about a token involved
            in the transaction.
        fee (float): The transaction fee to be applied.
        referrals (list of dict): A list of dictionaries specifying commission for referrals.
        encode_base64 (bool, optional): Whether to encode the transaction in base64 format. Defaults
            to True.

    Returns:
        list of str: A list of transaction signatures as strings.

    Raises:
        ValueError: If any of the input parameters are invalid.
        TransactionError: If the transaction fails to process.
    """
    txn = None
    txns = []
    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
        try:
            # Will set both burn and close intructions for every ATA
            METRIC = {'ACCOUNTS': len(tokens), 'CLAIMED': sum(token.balance for token in tokens)}
            logging.info("close_ata_transaction-> METRIC: {}".format(METRIC))

            # Prepare chunks to deal with many instructions: max 24 instructions per transaction
            # Each chunk will become a transaction
            burn_close_instructions = []
            chunk = []
            max_ixs_per_transaction = appconfig.BACKEND_MAX_INSTRUCTIONS_PER_TRANSACTION
            ghost_ixs = 4
            partners_fee_ixs = len(referrals)
            max_ixs_per_chunk = max_ixs_per_transaction - ghost_ixs - partners_fee_ixs

            # Check if we're dealing with an Corporate referral if claimFunds is True
            fund_claimer = [referral["pubKey"] for referral in referrals if referral["claimFunds"]]
            if fund_claimer:
                # The Corporate referral will receive all funds
                fund_claimer = Pubkey.from_string(fund_claimer[0])
            else:
                fund_claimer = owner

            burn_ix_counter = 0
            close_ix_counter = 0
            token_balance_sum = 0
            for token in tokens:
                associated_token_account = get_associated_token_address(
                    owner=owner,
                    mint=Pubkey.from_string(token.token_mint)
                )

                amount = token.token_amount_lamports
                mint = token.token_mint
                decimals = token.decimals
                token_balance_sum += token.balance

                # Construct the burn instruction only if there're tokens to burn
                if amount > 0:
                    burn_ix_counter += 1
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

                    # Every Burn ix must be with the corresponding close ix in the same transaction
                    if chunk and len(chunk) + 1 >= max_ixs_per_chunk:
                        chunk_data = {
                            "ixs": [ix for ix in chunk],
                            "burned": burn_ix_counter,
                            "closed": close_ix_counter,
                            "balance": token_balance_sum
                        }
                        burn_close_instructions.append(chunk_data)
                        chunk = []
                        burn_ix_counter = 0
                        close_ix_counter = 0
                        token_balance_sum = 0

                    chunk.append(burn_ix)

                # CLOSE
                # Create the close account instruction
                close_ix_counter += 1
                close_ix = close_account(
                    CloseAccountParams(
                        program_id=TOKEN_PROGRAM_ID,
                        account=associated_token_account,
                        dest=fund_claimer,
                        owner=owner
                    )
                )
                chunk.append(close_ix)

                # Closing current chunk
                if len(chunk) >= max_ixs_per_chunk:
                    chunk_data = {
                        "ixs": [ix for ix in chunk],
                        "burned": burn_ix_counter,
                        "closed": close_ix_counter,
                        "balance": token_balance_sum
                    }
                    burn_close_instructions.append(chunk_data)
                    chunk = []
                    burn_ix_counter = 0
                    close_ix_counter = 0
                    token_balance_sum = 0

            if chunk:
                chunk_data = {
                    "ixs": [ix for ix in chunk],
                    "burned": burn_ix_counter,
                    "closed": close_ix_counter,
                    "balance": token_balance_sum
                }
                burn_close_instructions.append(chunk_data)
                chunk = []

            # Required instructions to set compute unit limit and price
            compute_unit_price_ix = set_compute_unit_price(5_000)

            blockhash = await client.get_latest_blockhash()
            recent_blockhash = blockhash.value.blockhash

            # Got chink by chunk to create transactions
            for chunk in burn_close_instructions:
                compute_units = calculate_compute_units(closed=chunk["closed"], burned=chunk["burned"])
                compute_unit_limit_ix = set_compute_unit_limit(units=compute_units)

                # Variable fee
                # Summing all ATAs balances to calculate variable fee

                fee_ix_list = get_fee_instructions(
                    fee=fee,
                    balance=chunk["balance"],
                    owner=owner,
                    atas=chunk["closed"],
                    referrals=referrals
                )
                # Package all instructions as hex values from bytes into a single list
                instructions = [
                    compute_unit_price_ix,  # Convert to hex for compatibility
                    compute_unit_limit_ix,
                ]
                instructions.extend(chunk["ixs"])
                instructions.extend(fee_ix_list)

                msg = Message.new_with_blockhash(
                    instructions=instructions,
                    payer=owner,
                    blockhash=recent_blockhash
                )

                tx = Transaction.new_unsigned(message=msg)
                txn = {
                    "tx": bytes(tx),
                    "balance": chunk["balance"],
                    "tokens": chunk["closed"]
                }

                if encode_base64:
                    txn["tx"] = base64.b64encode(txn["tx"]).decode('ascii')

                txns.append(txn)

        except EntityNotFoundException as enfe:
            raise enfe
        except Exception as e:
            logging.error("request_close_ata_instruction Error: {}".format(e))
            raise ErrorProcessingData(detail="Internal Server Error")

    return txns


def get_fee_instructions(
    fee: float,
    balance: float,
    owner: Pubkey,
    atas: int,
    referrals: list[dict]
) -> list[Instruction]:
    """_summary_

    Args:
        fee (float): _description_
        balance (float): _description_
        owner (Pubkey): _description_
        atas (int): _description_
        referrals (list[dict]): example
        [
            {
                "slug": "saul",
                "commission": 0.2,
                "pubKey": "ECcPyowqkvKPnYTH4fnpE1sULKScbRAbw6UsU3w5Xgx",
                "claimFunds": false
            }
        ]

    Returns:
        list[Instruction]: _description_
    """
    # Fix fee: we're charging a base fix fee for every ATA we're burning and closing.
    lamports_to_charge = int(appconfig.GHOSTFUNDS_FIX_FEES * atas * 10**9)  # Convert SOL to lamports
    fix_fees_params = TransferParams(
        from_pubkey=owner,
        to_pubkey=Pubkey.from_string(appconfig.GHOSTFUNDS_FIX_FEES_RECEIVER),
        lamports=lamports_to_charge
    )
    fix_fees_ix = transfer(params=fix_fees_params)
    # Getting possible commisions to referrals
    all_commissions = 0
    if referrals:
        # Summing all referral commisions
        all_commissions = sum(int(referral["commission"] * 10**9) for referral in referrals) / 10**9

    # Variable fee: discounting possible referral commissions
    lamports_to_charge = int(balance * fee * (1 - all_commissions) * 10**9)  # Convert SOL to lamports
    variable_fees_params = TransferParams(
        from_pubkey=owner,
        to_pubkey=Pubkey.from_string(appconfig.GHOSTFUNDS_VARIABLE_FEES_RECEIVER),
        lamports=lamports_to_charge
    )
    variable_fees_ix = transfer(params=variable_fees_params)
    fees = [fix_fees_ix, variable_fees_ix]

    # Adding transfer for referrals
    referrals_commissions = []
    if referrals:
        for referral in referrals:
            lamports = int(balance * fee * referral["commission"] * 10**9)
            # No transfer fee if commission is 0
            if lamports == 0:
                continue

            fees_params = TransferParams(
                from_pubkey=owner,
                to_pubkey=Pubkey.from_string(referral["pubKey"]),
                lamports=lamports
            )
            referrals_commissions.append(transfer(params=fees_params))

    fees.extend(referrals_commissions)
    return fees


def calculate_compute_units(closed: int, burned: int):
    # Units consumed by each instruction
    burn_checked_units = 4742
    close_account_units = 2916
    other_instruction_units = 2000  # Adjust based on your use case

    # Total units required
    total_units = burned * burn_checked_units + closed * close_account_units + other_instruction_units

    # Add a buffer for safety
    return total_units


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
