import asyncio
import base58
import base64
import json
import struct
import time
import websockets

from datetime import datetime

from construct import Struct, Int64ul, Flag
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from solders.compute_budget import (
    set_compute_unit_limit,
    set_compute_unit_price
)
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction, VersionedTransaction
from solders.system_program import transfer, TransferParams
from solders.signature import Signature
from spl.token.instructions import get_associated_token_address
import spl.token.instructions as spl_token

from bot.config import appconfig
from bot.libs.utils import get_account_information

from bot.domain.jito_rpc import JitoJsonRpcSDK

EXPECTED_DISCRIMINATOR = struct.pack("<Q", 6966180631402821399)


class BondingCurveState:
    _STRUCT = Struct(
        "virtual_token_reserves" / Int64ul,
        "virtual_sol_reserves" / Int64ul,
        "real_token_reserves" / Int64ul,
        "real_sol_reserves" / Int64ul,
        "token_total_supply" / Int64ul,
        "complete" / Flag
    )

    def __init__(self, data: bytes) -> None:
        parsed = self._STRUCT.parse(data[8:])
        self.__dict__.update(parsed)


def get_pump_curve_state(curve_address: Pubkey) -> BondingCurveState:
    response = get_account_information(curve_address)
    if not response.value or not response.value.data:
        raise ValueError("Invalid curve state: No data")

    data = response.value.data
    if data[:8] != EXPECTED_DISCRIMINATOR:
        raise ValueError("Invalid curve state discriminator")

    return BondingCurveState(data)


def calculate_pump_curve_price(curve_state: BondingCurveState) -> float:
    if curve_state.virtual_token_reserves <= 0 or curve_state.virtual_sol_reserves <= 0:
        raise ValueError("Invalid reserve state")
    sols = (curve_state.virtual_sol_reserves / appconfig.LAMPORTS_PER_SOL)
    tokens = (curve_state.virtual_token_reserves / 10 ** appconfig.TOKEN_DECIMALS)
    return sols / tokens


def calculate_pump_curve_price_local(token_data: dict) -> float:
    buyers = token_data.get("buyers")
    sols_traded = sum(buyer.get("sol_traded") for buyer in buyers)
    tokens_bought = sum(buyer.get("tokens_bought") for buyer in buyers)

    # Initial virtual reserves
    initial_sol_reserves = 30  # Initial SOL in the virtual pool
    initial_token_reserves = 1_073_000_191  # Initial tokens in the virtual pool
    token_price = initial_token_reserves - 32_290_005_730 / (initial_sol_reserves + sols_traded)
    # #######

    # Current reserves after trades
    current_sol_reserves = initial_sol_reserves + sols_traded
    current_token_reserves = initial_token_reserves - tokens_bought

    # Calculate the token price per token
    token_price_per_token = current_sol_reserves / current_token_reserves

    # Calculate the price per 10 million tokens
    token_price = token_price_per_token

    return token_price


def calculate_compute_units():
    # Units consumed by each instruction
    create_ata_and_swap = 80000
    # Add a buffer for safety
    buffer_units = 1000
    return create_ata_and_swap + buffer_units


async def buy_token(
    mint: Pubkey,
    bonding_curve: Pubkey,
    associated_bonding_curve: Pubkey,
    amount: float,
    crator_vault: Pubkey,
    slippage: float = 0.01,
    token_price_sol_local: float = 0
):
    """This code assumes that no ATA exist when buying a Pump.fun token

    Args:
        mint (Pubkey): _description_
        bonding_curve (Pubkey): _description_
        associated_bonding_curve (Pubkey): _description_
        amount (float): _description_
        slippage (float, optional): _description_. Defaults to 0.01.
        max_retries (int, optional): _description_. Defaults to 5.
    """
    private_key = base58.b58decode(appconfig.PRIVKEY)
    payer = Keypair.from_bytes(private_key)

    print("Buy-> mint is {}".format(str(mint)))

    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
        associated_token_account = get_associated_token_address(
            owner=payer.pubkey(),
            mint=mint
        )
        amount_lamports = int(amount * appconfig.LAMPORTS_PER_SOL)

        if token_price_sol_local > 0:
            # Manually calculating token price
            token_amount = amount / token_price_sol_local
            print("Buy-> Token amount local: {}".format(token_amount))
        else:
            # Fetch the token price
            curve_state = get_pump_curve_state(bonding_curve)
            token_price_sol = calculate_pump_curve_price(curve_state)
            token_amount = amount / token_price_sol
            print("Buy-> Token amount: {}".format(token_amount))

        # Calculate maximum SOL to spend with slippage
        max_amount_lamports = int(amount_lamports * (1 + slippage))

        # ### Instructions
        compute_unit_price_ix = set_compute_unit_price(20_000)

        compute_units = calculate_compute_units()
        compute_unit_limit_ix = set_compute_unit_limit(units=compute_units)

        create_ata_ix = spl_token.create_associated_token_account(
            payer=payer.pubkey(),
            owner=payer.pubkey(),
            mint=mint
        )

        BUY_ACCOUNTS = [
            AccountMeta(pubkey=appconfig.PUMP_GLOBAL, is_signer=False, is_writable=False),
            AccountMeta(pubkey=appconfig.PUMP_FEE, is_signer=False, is_writable=True),
            AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
            AccountMeta(pubkey=bonding_curve, is_signer=False, is_writable=True),
            AccountMeta(pubkey=associated_bonding_curve, is_signer=False, is_writable=True),
            AccountMeta(pubkey=associated_token_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=payer.pubkey(), is_signer=True, is_writable=True),
            AccountMeta(pubkey=appconfig.SYSTEM_PROGRAM, is_signer=False, is_writable=False),
            AccountMeta(pubkey=appconfig.SYSTEM_TOKEN_PROGRAM, is_signer=False, is_writable=False),
            AccountMeta(pubkey=crator_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=appconfig.PUMP_EVENT_AUTHORITY, is_signer=False, is_writable=False),
            AccountMeta(pubkey=appconfig.PUMP_PROGRAM, is_signer=False, is_writable=False),
            # AccountMeta(pubkey=appconfig.SYSTEM_RENT, is_signer=False, is_writable=False),
        ]
        discriminator = struct.pack("<Q", 16927863322537952870)
        data = discriminator + struct.pack("<Q", int(token_amount * 10**6)) + struct.pack("<Q", max_amount_lamports)
        buy_ix = Instruction(appconfig.PUMP_PROGRAM, data, BUY_ACCOUNTS)

        # JITO TIP INSTRUCTION
        jito_client = JitoJsonRpcSDK(url="https://amsterdam.mainnet.block-engine.jito.wtf/api/v1")
        jito_tip_accounts = jito_client.get_tip_accounts()
        jito_tip_account = Pubkey.from_string(jito_tip_accounts["data"]["result"][0])
        jito_tip = int(0.00001 * 1_000_000_000)
        jito_transfer = TransferParams(
            from_pubkey=payer.pubkey(),
            to_pubkey=jito_tip_account,
            lamports=jito_tip
        )
        jito_ix = transfer(params=jito_transfer)

        instructions = [compute_unit_price_ix, compute_unit_limit_ix, create_ata_ix, buy_ix, jito_ix]

        # Last block hash
        blockhash = await client.get_latest_blockhash()
        recent_blockhash = blockhash.value.blockhash
        last_valid_block_height = blockhash.value.last_valid_block_height

        msg = Message(
            instructions=instructions,
            payer=payer.pubkey()
        )
        try:
            transaction = Transaction.new_unsigned(message=msg)
            # Sign the transaction
            transaction.sign([payer], recent_blockhash)
            serialized_transaction = base64.b64encode(bytes(transaction)).decode('ascii')

            result = jito_client.send_txn(serialized_transaction)
            # print('Raw API response:', json.dumps(result, indent=2))

            if result['success']:
                tx_buy = result['data']['result']
                print(f"Buy-> Transaction sent: https://solscan.io/tx/{tx_buy}")

                confirmation = await client.confirm_transaction(
                    Signature.from_string(tx_buy),
                    commitment="confirmed",
                    last_valid_block_height=last_valid_block_height
                )
                if confirmation.value:
                    print(f"Buy-> Transaction confirmed: https://solscan.io/tx/{tx_buy}")
                    from datetime import datetime
                    confirmation_stamp = datetime.now().timestamp()
                    return tx_buy, confirmation_stamp, token_amount
                else:
                    print("Buy-> Transaction not confirmed.")
            else:
                print(f"Buy-> Failed to send bundle: {result.get('error', 'Unknown error')}")

            # tx_buy = await client.send_transaction(
            #     Transaction([payer], msg, recent_blockhash),
            #     opts=TxOpts(preflight_commitment=Confirmed)
            # )
        except Exception as e:
            print("Buy-> ERROR. Failed to buy. Exception: {}".format(e))
        return None, None, None


async def get_token_balance(conn: AsyncClient, associated_token_account: Pubkey):
    counter = 0
    retries = 5
    while counter < retries:
        try:
            response = await conn.get_token_account_balance(associated_token_account)
            if response.value:
                return int(response.value.amount)
        except Exception:
            counter += 1
            time.sleep(1)
    return 0


async def sell_token(
    mint: Pubkey,
    token_balance: float,
    bonding_curve: Pubkey,
    associated_bonding_curve: Pubkey,
    crator_vault: Pubkey,
    slippage: float = 0.25,
    max_retries=5
):
    private_key = base58.b58decode(appconfig.PRIVKEY)
    payer = Keypair.from_bytes(private_key)

    async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
        associated_token_account = get_associated_token_address(
            owner=payer.pubkey(),
            mint=mint
        )

        # Get token balance
        # TODO: Partial selling: ISSUE-> get_token_balance return nothing and some retries must be implemented
        remote_token_balance = await get_token_balance(client, associated_token_account)
        if remote_token_balance > 0:
            token_balance = remote_token_balance
        else:
            token_balance = int(token_balance * 10 ** appconfig.TOKEN_DECIMALS)

        token_balance_decimal = token_balance / 10**appconfig.TOKEN_DECIMALS

        print(f"Sell-> Token balance decimals: {token_balance_decimal}")
        if token_balance == 0:
            print("No tokens to sell.")
            return

        # Fetch the token price
        curve_state = get_pump_curve_state(bonding_curve)
        token_price_sol = calculate_pump_curve_price(curve_state)
        print(f"Sell-> Price per Token: {token_price_sol:.20f} SOL")

        # Calculate minimum SOL output
        amount = token_balance
        min_sol_output = float(token_balance_decimal) * float(token_price_sol)
        slippage_factor = 1 - slippage
        min_sol_output = int((min_sol_output * slippage_factor) * appconfig.LAMPORTS_PER_SOL)

        print(f"Sell-> Selling {token_balance_decimal} tokens")
        print(f"Sell-> Minimum SOL output: {min_sol_output / appconfig.LAMPORTS_PER_SOL:.10f} SOL")

        for attempt in range(max_retries):
            try:
                accounts = [
                    AccountMeta(pubkey=appconfig.PUMP_GLOBAL, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=appconfig.PUMP_FEE, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=bonding_curve, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=associated_bonding_curve, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=associated_token_account, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=payer.pubkey(), is_signer=True, is_writable=True),
                    AccountMeta(pubkey=appconfig.SYSTEM_PROGRAM, is_signer=False, is_writable=False),
                    # AccountMeta(
                    #     pubkey=appconfig.SYSTEM_ASSOCIATED_TOKEN_ACCOUNT_PROGRAM,
                    #     is_signer=False,
                    #     is_writable=False
                    # ),
                    AccountMeta(pubkey=crator_vault, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=appconfig.SYSTEM_TOKEN_PROGRAM, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=appconfig.PUMP_EVENT_AUTHORITY, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=appconfig.PUMP_PROGRAM, is_signer=False, is_writable=False),
                ]

                discriminator = struct.pack("<Q", 12502976635542562355)
                data = discriminator + struct.pack("<Q", amount) + struct.pack("<Q", min_sol_output)
                sell_ix = Instruction(appconfig.PUMP_PROGRAM, data, accounts)

                compute_unit_price_ix = set_compute_unit_price(80_000)

                compute_units = calculate_compute_units()
                compute_unit_limit_ix = set_compute_unit_limit(units=compute_units)
                
                # JITO TIP INSTRUCTION
                jito_client = JitoJsonRpcSDK(url="https://amsterdam.mainnet.block-engine.jito.wtf/api/v1")
                jito_tip_accounts = jito_client.get_tip_accounts()
                jito_tip_account = Pubkey.from_string(jito_tip_accounts["data"]["result"][0])
                jito_tip = int(0.00001 * 1_000_000_000)
                jito_transfer = TransferParams(
                    from_pubkey=payer.pubkey(),
                    to_pubkey=jito_tip_account,
                    lamports=jito_tip
                )
                jito_ix = transfer(params=jito_transfer)

                instructions = [compute_unit_price_ix, compute_unit_limit_ix, sell_ix, jito_ix]

                # Last block hash
                blockhash = await client.get_latest_blockhash()
                recent_blockhash = blockhash.value.blockhash
                last_valid_block_height = blockhash.value.last_valid_block_height

                msg = Message(
                    instructions=instructions,
                    payer=payer.pubkey()
                )

                tx_sell = await client.send_transaction(
                    Transaction([payer], msg, recent_blockhash),
                    opts=TxOpts(preflight_commitment=Confirmed)
                )

                print(f"Sell-> Transaction sent: https://solscan.io/tx/{tx_sell.value}")

                confirmation = await client.confirm_transaction(
                    tx_sell.value,
                    commitment="confirmed",
                    last_valid_block_height=last_valid_block_height
                )
                if confirmation.value:
                    print("Sell-> Transaction confirmed")
                    return tx_sell.value
                else:
                    print("Sell-> Transaction fail. Retrying {} of {}".format(attempt + 1, max_retries))
                    attempt += 1

            except Exception as e:
                print(f"Sell-> Attempt {attempt + 1} failed: {str(e)}")
                if "AccountNotInitialized" in str(e):
                    print("Sell->  AccountNotInitialized. Nothing to sell...")
                    break
                elif attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    attempt += 1
                else:
                    print("Max retries reached. Unable to complete the transaction.")

            return None


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


async def listen_for_create_transaction(websocket):
    idl = load_idl('bot/idl/pump_fun_idl.json')
    create_discriminator = 8576854823835016728
    buy_discriminator = 16927863322537952870

    subscription_message = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "blockSubscribe",
        "params": [
            {"mentionsAccountOrProgram": str(appconfig.PUMP_PROGRAM)},
            {
                "commitment": "confirmed",
                "encoding": "base64",
                "showRewards": False,
                "transactionDetails": "full",
                "maxSupportedTransactionVersion": 0
            }
        ]
    })
    await websocket.send(subscription_message)
    print(f"Subscribed to blocks mentioning program: {appconfig.PUMP_PROGRAM}")

    ping_interval = 20
    last_ping_time = time.time()

    keep_loop = True
    token_data = {}
    decoded_args = {}
    buyers = []
    threshold = 400_000_000
    tradable_tokens = []

    while keep_loop:
        try:
            current_time = time.time()
            if current_time - last_ping_time > ping_interval:
                await websocket.ping()
                last_ping_time = current_time

            response = await asyncio.wait_for(websocket.recv(), timeout=10)
            data = json.loads(response)

            if 'method' in data and data['method'] == 'blockNotification':
                if 'params' in data and 'result' in data['params']:
                    block_data = data['params']['result']
                    if 'value' in block_data and 'block' in block_data['value']:
                        block = block_data['value']['block']
                        if 'transactions' in block:
                            for tx in block['transactions']:
                                if isinstance(tx, dict) and 'transaction' in tx:
                                    tx_data_decoded = base64.b64decode(tx['transaction'][0])
                                    transaction = VersionedTransaction.from_bytes(tx_data_decoded)

                                    for ix in transaction.message.instructions:
                                        program_id = str(transaction.message.account_keys[ix.program_id_index])
                                        if program_id == str(appconfig.PUMP_PROGRAM):
                                            ix_data = bytes(ix.data)
                                            discriminator = struct.unpack('<Q', ix_data[:8])[0]

                                            account_keys = []
                                            if discriminator == create_discriminator:
                                                create_ix = next(
                                                    instr for instr in idl['instructions'] if instr['name'] == 'create'
                                                )
                                                try:
                                                    account_keys = [
                                                        str(transaction.message.account_keys[index]) for index in ix.accounts  # noqa=501
                                                    ]
                                                except Exception:
                                                    print("Create Error: Mismatch between ix.accounts(${}) and account_keys".format(
                                                        len(ix.accounts)),
                                                        len(transaction.message.account_keys)
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

                                                decoded_args["block"] = block["parentSlot"] + 1
                                                decoded_args["blockTime"] = block["blockTime"]
                                                decoded_args["buyers"] = []
                                                decoded_args["seen_buyers"] = set()
                                                # return decoded_args
                                                token_data = {
                                                    decoded_args["mint"]: decoded_args.copy(),
                                                }

                                                # print("\n> New token: {} at block: {}".format(
                                                #     decoded_args["mint"],
                                                #     decoded_args["block"]
                                                # ))

                                                continue

                                            # We'll check on BUYs after having a new token created
                                            if decoded_args and discriminator == buy_discriminator:
                                                buy_ix = next(
                                                    instr for instr in idl['instructions'] if instr['name'] == 'buy'
                                                )
                                                try:
                                                    account_keys = [
                                                        str(transaction.message.account_keys[index]) for index in ix.accounts
                                                    ]
                                                except Exception:
                                                    print("Buy Error: Mismatch between ix.accounts(${}) and account_keys".format(
                                                        len(ix.accounts)),
                                                        len(transaction.message.account_keys)
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

                                                        # print("Buyer: {}, Tokens Bought: {}, SOL Traded: {}".format(
                                                        #     buyer,
                                                        #     tokens_bought / 10**6,
                                                        #     (sol_traded / 10**9) / 1.01
                                                        # ))
                                                continue
                                # End of transaction loop
                                # if token_data:
                                #     for token, data in token_data.items():
                                #         total_tokens_bought = sum(buyer["tokens_bought"] for buyer in data.get("buyers", []))  # noqa: E501
                                #         if total_tokens_bought > threshold:
                                #             print(f"Token {token} exceeds the threshold with {total_tokens_bought} tokens bought.")  # noqa: E501
                                #     break

                            # Ending block loop
                            if token_data:
                                if len(list(token_data.keys())) > 1:
                                    print("-> Tokens: {}".format(len(list(token_data.keys()))))
                                for token, data in token_data.items():
                                    print("-> Checking on token {}".format(token))
                                    total_tokens_bought = sum(
                                        buyer["tokens_bought"] for buyer in data.get("buyers", [])
                                    )
                                    if total_tokens_bought >= threshold:
                                        if (len(data.get("buyers", [])) > 5):
                                            start_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
                                            print("{} Scam 'BIG' token found. Tokens bought {}".format(
                                                start_time,
                                                total_tokens_bought
                                            ))
                                            tradable_tokens.append(data)
                                        elif (len(buyers) > 1):
                                            print(" Scam 'MID' token found. Discarting token...")
                                        else:
                                            print(" Whale scam found. Discarting token...")
                                    else:
                                        print("*** TESTING token...")
                                        tradable_tokens.append(data)

                                if tradable_tokens:
                                    keep_loop = False
                                    break  # Breaking transactions loop
                                decoded_args = {}
                                token_data = {}

        except asyncio.TimeoutError:
            print("No data received for 10 seconds, sending ping...")
            await websocket.ping()
            last_ping_time = time.time()
        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection closed. Reconnecting...")
            raise

    return tradable_tokens


async def trade(websocket: websockets, trades: int):

    token_data_list = await listen_for_create_transaction(websocket)
    token_data = token_data_list[0]  # Note: As we're trading only one token at the time

    mint = Pubkey.from_string(token_data['mint'])
    bonding_curve = Pubkey.from_string(token_data['bondingCurve'])
    associated_bonding_curve = Pubkey.from_string(token_data['associatedBondingCurve'])

    if not token_data['buyers']:
        return None

    crator_vault = Pubkey.from_string(token_data['buyers'][0]['creator_vault'])

    token_price_sol_local = calculate_pump_curve_price_local(token_data=token_data)
    print("** Token amount local: {}".format(token_price_sol_local))

    print("Buying {:.6f} SOL worth of the new token with {:.1f}% slippage tolerance...".format(
        appconfig.TRADING_DEFAULT_AMOUNT,
        appconfig.BUY_SLIPPAGE * 100
    ))
    buy_tx_hash, confirmation_stamp, token_amount = await buy_token(
        mint=mint,
        bonding_curve=bonding_curve,
        associated_bonding_curve=associated_bonding_curve,
        amount=appconfig.TRADING_DEFAULT_AMOUNT,
        crator_vault=crator_vault,
        slippage=appconfig.BUY_SLIPPAGE,
        token_price_sol_local=token_price_sol_local
    )
    if buy_tx_hash:
        print("Pump trade: https://pump.fun/coin/{}".format(mint))
    else:
        print("** Failed to buy {}. Looking for another new token".format(mint))
        return None

    # Check if we're in market by getting all ATAs and check if we're current ATA exists
    # private_key = base58.b58decode(appconfig.PRIVKEY)
    # owner = Keypair.from_bytes(private_key)
    # associated_token_account = get_associated_token_address(
    #     owner=owner.pubkey(),
    #     mint=mint
    # )
    # print("Check-> Validating if ATA {} exists".format(str(associated_token_account)))
    # async with AsyncClient(appconfig.RPC_URL_HELIUS) as client:
    #     # Get associated token account
    #     associated_token_account = get_associated_token_address(
    #         owner=owner.pubkey(),
    #         mint=mint
    #     )

    #     # Check if the associated token account exists
    #     response = await client.get_account_info(associated_token_account)
    #     account_info = response.value
    #     if not account_info:
    #         print("Associated token account {} does not exist.".format(
    #             associated_token_account
    #         ))
    #         continue

    # Calculate time delta: Get timestamp from buy block and timestamp from creation block
    time_delta = abs(confirmation_stamp - token_data["blockTime"])
    sleep_time = 0 if appconfig.TRADING_TIME - time_delta < 0 else appconfig.TRADING_TIME - time_delta
    sleep_time = 0
    data = {
        "sleep_time": sleep_time,
        "mint": mint,
        "token_balance": token_amount,
        "bonding_curve": bonding_curve,
        "associated_bonding_curve": associated_bonding_curve,
        "slippage": appconfig.BUY_SLIPPAGE,
        "max_retries": appconfig.TRADING_RETRIES,
        "crator_vault": crator_vault
    }
    return data


async def main(trades: int = 1):
    # import hashlib
    # hash_bytes = hashlib.sha256(b'global:buy').digest()
    # # Extract the first 8 bytes and unpack them as a little-endian unsigned long long integer
    # buy_discriminator = struct.unpack_from('<Q', hash_bytes[:8])[0]
    # print(buy_discriminator)

    trade_counter = 0
    if (trades == -1):
        print("Running Tax Collector Bot for {} trades".format(
            trades if trades != -1 else "'infinite'"
        ))

    while trade_counter < trades or trades == -1:
        print("Trade Nº {} of {} trades".format(trade_counter + 1, trades))
        data = {}
        # TODO: implement Helius WSS
        async with websockets.connect(appconfig.WSS_URL_QUICKNODE) as websocket:
            data = await trade(websocket, trades)

        if data:
            print("Sleeping for {} seconds".format(data["sleep_time"]))
            time.sleep(data["sleep_time"])

            # Sell
            print("Time to sell all")
            await sell_token(
                mint=data["mint"],
                token_balance=data["token_balance"],
                bonding_curve=data["bonding_curve"],
                associated_bonding_curve=data["associated_bonding_curve"],
                slippage=appconfig.BUY_SLIPPAGE,
                max_retries=appconfig.TRADING_RETRIES,
                crator_vault=data["crator_vault"]
            )

            trade_counter += 1
        else:
            print("Something went wrong... not adding trade counter.")

if __name__ == "__main__":
    asyncio.run(main(trades=1))
