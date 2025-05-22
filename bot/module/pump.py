import asyncio
import nest_asyncio
import json
import requests
import time
import websockets
import ssl
import certifi
import websockets.connection
import websockets.exceptions

from bot.libs.criterias import (
    trading_analytics,
    max_consecutive_buys,
    max_consecutive_sells,
    max_seconds_between_buys,
    max_sols_in_token_after_buying_in_percentage,
    trader_has_sold,
    seller_is_an_unknown_trader,
    market_inactivity,
    buys_in_the_same_second,
    discard_token_max_seconds_between_buys,
    max_seconds_in_market,
    discard_max_seconds_in_market
)
from bot.libs import criterias as criteria_functions
from bot.libs.utils import (
    get_solana_balance,
    Trader,
    TxType,
    Celebrimborg,
    initial_buy_calculator
)
from bot.config import appconfig, AppMode
from bot.domain.redis_db import RedisDB

from datetime import datetime, timedelta
from enum import Enum
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.keypair import Keypair
from solders.commitment_config import CommitmentLevel
from solders.rpc.requests import SendVersionedTransaction
from solders.rpc.config import RpcSendTransactionConfig

from typing import Dict, List


class Suscription(Enum):
    subscribeNewToken = "subscribeNewToken"
    subscribeAccountTrade = "subscribeAccountTrade"
    subscribeTokenTrade = "subscribeTokenTrade"
    unsubscribeTokenTrade = "unsubscribeTokenTrade"


class Redis(Enum):
    readToken = "readToken"
    selectToken = "selectToken"
    closeToken = "closeToken"
    readTraders = "readTraders"
    saveToken = "saveToken"
    cleanTokens = "cleanTokens"


class TradeRoadmap:
    test = [
        {"step": 0, "name": "test", "subscription": Suscription.subscribeNewToken},
        {"step": 1, "name": "test", "subscription": Suscription.subscribeTokenTrade},
    ]
    sniper_copytrade = [ # TODO: to be developed
        {"step": 0, "name": "WAIT_FOR_TRADERS", "redis": Redis.readTraders},
        {
            "step": 1,
            "name": "TRADER_SUBSCRIPTION",
            "subscription": Suscription.subscribeNewToken,
            "criteria": {
                "min_initial_buy": 1.00,
            }
        },
        {"step": 2, "name": "TRADE_TOKEN", "action": TxType.buy},
        {
            "step": 3,
            "name": "TOKEN_SUBSCRIPTION",
            "subscription": Suscription.subscribeTokenTrade,
            "criteria": {
                "copytrade_sell": True,
                "same_balance": True,
                "market_inactivity": 30
            }
        },
        {"step": 4, "name": "TRADE_TOKEN", "action": TxType.sell},
        {"step": 5, "name": "UNSUBSCRIBE_TO_TOKEN", "subscription": Suscription.unsubscribeTokenTrade},
        {"step": 6, "name": "MARK_TOKEN", "redis": Redis.closeToken},

    ]
    scanner = [
        {
            "step": 0,
            "name": "START_SCANNER",
            "system_action": Celebrimborg.start,
            "criteria": {
                "scanner_activity_time": -1,    # How much time the scanner will be working. -1 is always
                "max_trades": 1
            },
        },
        {
            "step": 1,
            "name": "CLEAN_UNTRADED_TOKENS_FROM_REDIS",
            "redis": Redis.cleanTokens,
            "criteria": {
                "delete_unchecked_tokens": True
            }
        },
        {
            "step": 2,
            "name": "SCANNER",
            "subscription": Suscription.subscribeNewToken,
            "criteria": {
                "min_initial_buy": 30.0,        # Filter: we'll trade tokens with this initial buying amount at least.
                "trading_amount": 0.001,        # Amount to be traded by snipers
                "trader": Trader.sniper.value,  # Who will trade the tokens
                "threshold": 500_000_000,       # Amount of tokens bough by developer and snipers
                "min_scam_buyers": 3            # Min scam buying bots for a token scam to be considered
            },
            "action": {
                "name": "SAVE_TOKEN_IN_REDIS",
                "redis": Redis.saveToken,
                "criteria": {
                    "capacity": 10   # How many tokens will be written to redis at the same time
                }
            }
        },
        {"step": 3, "name": "exit", "system_action": Celebrimborg.exit},
    ]
    sniper_1 = [
        {
            "step": 0,
            "name": "WAIT_FOR_TOKEN",
            "redis": Redis.readToken,
            "criteria": {
                "use_all_balance": True # If True, all balance will be used if balance < trading amount
            }
        },
        {
            "step": 1,
            "name": "TRADE_TOKEN_BUY",
            "action": TxType.buy,
            "on_error_go_to_step": 4
        },
        {
            "step": 2,
            "name": "TOKEN_SUBSCRIPTION",
            "subscription": Suscription.subscribeTokenTrade,
            # Exit criteria to move on to the next step
            "criteria": {
                "max_consecutive_buys": 4,
                "max_consecutive_sells": 2,
                "max_seconds_between_buys": 2.5,
                "trader_has_sold": True,
                "max_sols_in_token_after_buying_in_percentage": 500,
                "market_inactivity": 3,
                "validate_trade_timedelta_exceeded": True,
                "seller_is_an_unknown_trader": True
            }
        },
        {
            "step": 3,
            "name": "TRADE_TOKEN_SELL",
            "action": TxType.sell,
            "on_error_go_to_step": 4
        },
        {"step": 4, "name": "UNSUBSCRIBE_TO_TOKEN", "subscription": Suscription.unsubscribeTokenTrade},
        {"step": 5, "name": "CLOSE_TOKEN", "redis": Redis.closeToken},
    ]
    sniper_2_detect_artifical_pump = [
        {
            "step": 0,
            "name": "WAIT_FOR_TOKEN",
            "redis": Redis.readToken,
            "criteria": {
                "use_all_balance": True,    # If True, all balance will be used if balance < trading amount
                "age_tolerance ": 2,        # Acceptable seconds since token creation in redis
            }
        },
        {
            "step": 1,
            "name": "TOKEN_SUBSCRIPTION",
            "subscription": Suscription.subscribeTokenTrade,
            # Exit criteria to move on to the next step
            "criteria": {
                "buys_in_the_same_second": {
                    "min_buys_per_timestamp": 3,
                    "min_consecutive_timestamps": 3,
                    "seconds_since_token_genesis": 10,
                },
                "discard_token_max_seconds_between_buys": 3,
                "discard_max_seconds_in_market": 10,
                "discard_market_inactivity": 10,
            },
            "on_discard_token_go_to_step": 5
        },
        {
            "step": 2,
            "name": "TRADE_TOKEN_BUY",
            "action": TxType.buy,
            "on_error_go_to_step": 5
        },
        {
            "step": 3,
            "name": "TOKEN_SUBSCRIPTION",
            "subscription": Suscription.subscribeTokenTrade,
            # Exit criteria to move on to the next step
            "criteria": {
                "market_inactivity": 10,
                "max_sols_in_token_after_buying_in_percentage": 500,
                "max_seconds_in_market": 60,
            },
        },
        {
            "step": 4,
            "name": "TRADE_TOKEN_SELL",
            "action": TxType.sell,
            "on_error_go_to_step": 5
        },
        {"step": 5, "name": "UNSUBSCRIBE_TO_TOKEN", "subscription": Suscription.unsubscribeTokenTrade},
        {"step": 6, "name": "CLOSE_TOKEN", "redis": Redis.closeToken},
    ]
    sniper_3_sell_artifical_pump = [
        {
            "step": 0,
            "name": "WAIT_FOR_TOKEN",
            "redis": Redis.readToken,
            "criteria": {
                "use_all_balance": True,    # If True, all balance will be used if balance < trading amount
                "age_tolerance ": 2,        # Acceptable seconds since token creation in redis
            }
        },
        {
            "step": 1,
            "name": "WAIT",
            "WAITING_SECONDS": 15
        },
        {
            "step": 2,
            "name": "TRADE_TOKEN_SELL",
            "action": TxType.sell,
            "on_error_go_to_step": 2
        },
        {"step": 3, "name": "UNSUBSCRIBE_TO_TOKEN", "subscription": Suscription.unsubscribeTokenTrade},
        {"step": 4, "name": "CLOSE_TOKEN", "redis": Redis.closeToken},
    ]


# Patch the running event loop. Required to get wallet's balance
nest_asyncio.apply()


class Pump:
    sniping_token_list = []

    def __init__(
            self,
            executor_name: str,
            trader_type: Trader,
            amount: float = appconfig.TRADING_DEFAULT_AMOUNT,
            target: float = appconfig.TRADING_EXPECTED_GAIN_IN_PERCENTAGE
    ) -> None:
        self.uri_data = appconfig.PUMPFUN_WEBSOCKET
        self.accounts = []
        self.tokens = {}
        self.traders = []
        self.executor_name = executor_name
        self.trader_type = trader_type
        self.min_initial_buy = appconfig.SCANNER_MIN_TRADING_AMOUNT
        self.tokens_to_be_traded = appconfig.TRADING_TOKENS_AT_THE_SAME_TIME
        self.trading_amount = amount
        self.trading_sell_amount = amount * (1 + target)    # TODO: apply this when we have the Bounding Courve
        self.trade_counter = 0

        self.keypair = Keypair.from_base58_string(appconfig.PRIVKEY)
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.balance = self.get_balance(public_key=self.keypair.pubkey())

        self.scanner_start_time = None
        self.scanner_activity_time = appconfig.SCANNER_WORKING_TIME
        self.max_trades = appconfig.SCANNER_MAX_TARDES
        self.stop_app = False

        self.trade_fees = appconfig.FEES
        self.halt_trade = 0

    def start_scanner(self):
        self.scanner_start_time = datetime.now()

    def get_balance(self, public_key):
        balance = asyncio.run(get_solana_balance(public_key=public_key))
        return balance

    def get_tkn_balance(self, wallet_pubkey, token_account):
        token_balance = 0
        if appconfig.APPMODE not in [AppMode.dummy.value, AppMode.simulation.value]:
            # TODO: get balance from redis
            # BYPASS
            token_balance = 0
            # token_balance = asyncio.run(get_own_token_balance(
            #         wallet_pubkey=wallet_pubkey,
            #         token_mint_addres=token_account
            #     )
            # )
        return token_balance

    def increase_fees(self):
        print("### INCREASING FEES: from {} to {}".format(
            self.trade_fees,
            self.trade_fees + appconfig.FEES_INCREASMENT
        ))
        self.trade_fees += appconfig.FEES_INCREASMENT

    def decrease_fees(self):
        lower_fees = round(self.trade_fees - appconfig.FEES_INCREASMENT, 9)
        print("### DECREASING FEES: from {} to {}".format(
            self.trade_fees,
            lower_fees if lower_fees >= appconfig.FEES else appconfig.FEES
        ))
        self.trade_fees = lower_fees if lower_fees >= appconfig.FEES else appconfig.FEES

    def reset_fees(self):
        self.trade_fees = appconfig.FEES

    def add_account(self, account: str):
        self.accounts.append(account)

    def remove_account(self, account: str):
        if account in self.accounts:
            self.accounts.pop(self.accounts.index(account))

    # Tokens to pay attention to
    def add_update_token(self, token: Dict):
        """
        Updates the token in the dictionary based on the provided mint key.
        If the mint key does not exist, it will add a new token.

        Args:
            mint (str): The mint attribute of the token to be updated.
            updated_data (Dict): The data to update the token with.
        """
        if token["mint"] in self.tokens:
            # Update only the provided fields
            self.tokens[token["mint"]].update(token)
        else:
            # If the mint doesn't exist, treat it as a new token
            self.tokens[token["mint"]] = token

    def remove_token(self, token: Dict):
        del self.tokens[token["mint"]]

    def clear_tokens(self):
        self.tokens = {}

    def log_trade_token_timestamp(self, mint: str, txtype: TxType, trade_timestamp: int):
        token = self.tokens[mint]
        key = "{}_timestamp".format(txtype.value)
        token[key] = trade_timestamp
        self.add_update_token(token=token)

    # Traders to follow for starting and stoping pumps
    def add_trader(self, trader: str):
        self.traders.append(trader)

    def remove_trader(self, trader: str):
        if trader in self.traders:
            self.traders.pop(self.traders.index(trader))

    async def subscribe(self, steps: list):
        step_index = 0
        print("Subscribe is working in {} mode.".format(appconfig.APPMODE))

        redisdb = RedisDB()
        await asyncio.sleep(2)  # Wait 2 seconds for the redis connection to start

        # Keepalive main loop
        while not self.stop_app:
            try:
                # SSL context is required on Mac and not on windows
                async with websockets.connect(
                    self.uri_data,
                    ssl=self.ssl_context,
                    ping_interval=5
                ) as websocket:
                    # Handle WebSocket communication
                    while True:
                        # Starting again from step 0 and closing current websocket connection
                        if step_index >= len(steps):
                            step_index = 0
                            await websocket.close()
                            break

                        roadmap_name = steps[step_index]["name"]
                        if step_index == 0:
                            print("subscribe -> restarting roadmap '{}'\n".format(roadmap_name))

                        print("Step {}: {}".format(
                            step_index,
                            steps[step_index]["name"]
                        ))

                        step = steps[step_index]

                        if "system_action" in step:
                            if step["system_action"] == Celebrimborg.start:
                                # Applying starting criterias
                                if "scanner_activity_time" in step["criteria"]:
                                    self.scanner_activity_time = step["criteria"]["scanner_activity_time"]

                                self.max_trades = step.get("criteria", []).get("max_trades")

                                start_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
                                print("Start at {} ".format(
                                    start_time
                                ))
                                stop_time = datetime.now() + timedelta(seconds=self.scanner_activity_time)
                                stop_time = stop_time.strftime(appconfig.TIME_FORMAT).lower()
                                stop_time = "Never" if self.scanner_activity_time == -1 else stop_time
                                print("Expected stop at {} ".format(
                                    stop_time
                                ))
                                stop_max_trades = "Infinite" if self.max_trades == -1 else self.max_trades
                                print("Expected max trades: {} ".format(
                                    stop_max_trades
                                ))
                                step_index += 1
                                continue

                            if step["system_action"] == Celebrimborg.exit:
                                self.stop_app = True
                                print("Exiting Celebrimborg as expected after reaching timeout.")
                                break

                        # REDIS DB HANDLING
                        if "redis" in step:
                            if step["redis"] == Redis.cleanTokens:
                                if "criteria" in step:
                                    if "delete_unchecked_tokens" in step["criteria"]:
                                        if step["criteria"]["delete_unchecked_tokens"]:
                                            deletions = redisdb.delete_unchecked_tokens()
                                            print("Deleted unchecked tokens from redis db: {}".format(
                                                deletions
                                            ))
                                step_index += 1
                                continue

                            # Listen to redis change
                            redisdb.subscribe()
                            if step["redis"] == Redis.readToken:
                                for message in redisdb.pubsub.listen():
                                    if message["type"] == "psubscribe":
                                        print("Subscribed to redis")

                                    if message["type"] == "pmessage":
                                        # Parse the message
                                        key = ":".join(message["channel"].split(":")[1:])
                                        # Get token information: Take key and retrieve token from redis
                                        tokens = redisdb.get_fresh_tokens(
                                            trader=Trader.sniper,
                                            mint_address=key
                                        )
                                        # - Ignore token that are not fresh or for not the current trader type
                                        if not tokens:
                                            continue
                                        # Snipe against many tokens
                                        how_many = appconfig.TRADING_TOKENS_AT_THE_SAME_TIME
                                        if len(tokens) < appconfig.TRADING_TOKENS_AT_THE_SAME_TIME:
                                            how_many = len(tokens)

                                        for token in tokens[0: how_many]:
                                            mint = token["mint"]
                                            amount = token["amount"]

                                            # FILTERING BY TOKEN'S CREATION TIME
                                            token_creation_time = datetime.fromtimestamp(token["timestamp"])
                                            token_age = (datetime.now() - token_creation_time).total_seconds()

                                            age_tolerance = appconfig.TRADING_TOKEN_TOO_OLD_SECONDS
                                            if "age_tolerance" in step["criteria"]:
                                                age_tolerance = step["criteria"]["age_tolerance"]

                                            if token_age >= age_tolerance and appconfig.APPMODE not in [AppMode.dummy.value]:
                                                print("Warning: susbscribe -> Token {} is too old for trading. Checking it and moving on".format(
                                                    token["name"]
                                                ))
                                                redisdb.update_token(
                                                    token=token,
                                                    is_checked=True,
                                                    is_closed=True
                                                )
                                                continue

                                            enough_balance = self.balance >= amount
                                            # Checking wallet's balance before trading                  
                                            if enough_balance:
                                                self.trading_amount = amount
                                            else:
                                                # Checking if we are allowed to use all balance
                                                if "criteria" in step and "use_all_balance" in step["criteria"]:
                                                    if step["criteria"]["use_all_balance"]:
                                                        self.trading_amount = self.balance
                                                        enough_balance = True

                                                print("{}: Warning: susbscribe -> Not enough balance for Token {} and amount {}. Balance is {}".format(
                                                    self.executor_name,
                                                    mint,
                                                    amount,
                                                    self.balance
                                                ))
                                                if appconfig.APPMODE in [AppMode.dummy.value, AppMode.simulation.value]:
                                                    self.trading_amount = amount
                                                else:
                                                    # TODO: send an alert message to redis notifying having not enough balance
                                                    print("{}: Sending message notifying that there's not enough balance for trading".format(
                                                        self.executor_name
                                                    ))

                                            # - move to next step and update the token as being checked
                                            # Also closing the token if there's not enough balance for trading
                                            token = redisdb.update_token(
                                                token=token,
                                                is_checked=True,
                                                is_closed=not enough_balance
                                            )
                                            self.add_update_token(token=token)

                                            print("Token {}:{} assigned to {} to trade {}Sols".format(
                                                token["name"],
                                                token["mint"],
                                                self.executor_name,
                                                self.trading_amount
                                            ))
                                        
                                        tokens_to_trade = any(token for token in tokens if token["is_checked"])

                                        # Safely unsubscribing from current channel listening
                                        if tokens_to_trade:
                                            redisdb.unsubscribe()
                                            break

                                step_index += 1
                                continue

                            if step["redis"] == Redis.closeToken:
                                for mint in list(self.tokens.keys()):
                                    self.remove_token(token=self.tokens[mint])
                                step_index += 1
                                continue
                        
                        if "action" in step:
                            if step["action"] == TxType.buy:
                                for mint_address, token_data in self.tokens.items():
                                    
                                    # We can trade closed tokens. This might happen if there's not enough balabnce
                                    if token_data["is_closed"]:
                                        print("  Can't buy {} as this token is closed".format(url))
                                        continue

                                    print("Attempting to buy token {}".format(mint_address))
            
                                    txn = self.trade(
                                        txtype=TxType.buy,
                                        token=mint_address,
                                        keypair=self.keypair,
                                        amount=self.trading_amount
                                    )

                                    if txn is None:
                                        if "on_error_go_to_step" in step:
                                            # Need to point to previous step
                                            step_index = step["on_error_go_to_step"] - 1
                                            break
                                    
                                    buy_time = datetime.now()
                                    url = "https://pump.fun/coin/{}".format(mint_address)
                                    print("Buy {} at {}".format(
                                        url,
                                        buy_time.strftime(appconfig.TIME_FORMAT).lower())
                                    )

                                    self.log_trade_token_timestamp(
                                        mint=mint_address,
                                        txtype=TxType.buy,
                                        trade_timestamp=buy_time.timestamp()
                                    )

                                    # Get the token balance in wallet
                                    token_balance = self.get_tkn_balance(
                                        wallet_pubkey=self.keypair.pubkey(),
                                        token_account=mint_address
                                    )

                                    self.tokens[mint_address]["token_balance"] = token_balance

                                    # Update token record in redis
                                    token_updated = redisdb.update_token(
                                        token=token_data,
                                        txn=txn,
                                        action=TxType.buy,
                                        amount=self.trading_amount,
                                        trader=self.trader_type,
                                        balance=self.balance,
                                        token_balance=token_balance
                                    )
                                    # Update token
                                    self.add_update_token(token=token_updated)

                                step_index += 1

                            if step["action"] == TxType.sell:
                                for mint_address, token_data in self.tokens.items():
                                    if token_data["is_closed"]:
                                        continue

                                    # TODO: If trade_time_delta > tolerance then check if the buy txn has been done

                                    txn = self.trade(
                                        txtype=TxType.sell,
                                        token=mint_address,
                                        keypair=self.keypair,
                                        amount=None             # Amount will be handled buy trade function
                                    )

                                    sell_time = datetime.now()
                                    print("Sell {} at {}".format(
                                            url,
                                            sell_time.strftime(appconfig.TIME_FORMAT).lower()
                                        )
                                    )

                                    self.log_trade_token_timestamp(
                                        mint=mint_address,
                                        txtype=TxType.sell,
                                        trade_timestamp=buy_time.timestamp()
                                    )
                                    # Update wallet balance after selling
                                    self.get_balance(public_key=self.keypair.pubkey())

                                    # Get the token balance in wallet
                                    # Note: although we're selling 100% of tokens we might sell a % of tokens
                                    #       in the future and that's way we get the token balance when selling
                                    token_balance = self.get_tkn_balance(
                                        wallet_pubkey=self.keypair.pubkey(),
                                        token_account=mint_address
                                    )
                                    # Update token record in redis
                                    token_updated = redisdb.update_token(
                                        token=token_data,
                                        txn=txn,
                                        action=TxType.sell,
                                        amount=self.trading_amount,
                                        trader=self.trader_type,
                                        is_closed=True,
                                        balance=self.balance,
                                        token_balance=token_balance,
                                        trades=self.tokens[mint_address]["trades"]
                                    )

                                    # Update token
                                    self.add_update_token(token=token_updated)

                                step_index += 1

                        if "subscription" in step:
                            try:
                                suscription = step["subscription"]

                                payload = {
                                    "method": suscription.value,
                                }

                                websocket_timeout = appconfig.TRADING_MARKETING_INACTIVITY_TIMEOUT
                                if "criteria" in step:
                                    if "market_inactivity" in step["criteria"]:
                                        websocket_timeout = step["criteria"]["market_inactivity"]
                                    if "discard_market_inactivity" in step["criteria"]:
                                        websocket_timeout = step["criteria"]["discard_market_inactivity"]

                                if suscription.value == Suscription.subscribeAccountTrade.value:
                                    payload["keys"] = self.accounts

                                if suscription.value == Suscription.subscribeTokenTrade.value:
                                    payload["keys"] = [mint for mint, _ in self.tokens.items() if self.tokens[mint]["is_checked"] and not self.tokens[mint]["is_traded"]]

                                if suscription.value == Suscription.unsubscribeTokenTrade.value:
                                    payload["keys"] = [mint for mint, _ in self.tokens.items() if self.tokens[mint]["is_closed"]]

                                await websocket.send(json.dumps(payload))

                                #####################
                                # ADD HERE THE BUYING TRADEs in separate threads and fix the step so Buy and Sell are inside subscription
                                # NOTE: test buy and sell in real before having them in threads
                                #####################
                                for mint, token_data in self.tokens.items():
                                    if not self.tokens[mint]["is_traded"] and \
                                        self.tokens[mint]["is_checked"] and \
                                        not self.tokens[mint]["is_closed"]:
                                        pass
                                
                                while True:
                                    try:
                                        message = await asyncio.wait_for(
                                            websocket.recv(),
                                            timeout=websocket_timeout
                                        )
                                        msg = json.loads(message)
                                        move_to_next_step = False

                                        # This is the first message we get when we connect
                                        if "message" in msg:
                                            print(msg["message"])
                                            # If the message is about unsibscribing, then we move on to the next step
                                            if suscription.value == Suscription.unsubscribeTokenTrade.value and "unsubscribed" in msg["message"].lower():
                                                move_to_next_step = True
                                            else:
                                                continue

                                        if suscription.value == Suscription.subscribeNewToken.value:
                                            if self.halt_trade > 0:
                                                print("HALT: for {} tokens".format(self.halt_trade))
                                                self.halt_trade -= 1
                                                continue

                                            move_to_next_step = self.new_token_suscription(
                                                msg=msg,
                                                step=step,
                                                redisdb=redisdb
                                            )

                                        if suscription.value == Suscription.subscribeTokenTrade.value:
                                            # Getting the mint address we'll work with
                                            # CHeck mint value for each tokeb being processed
                                            mint = msg["mint"]

                                            # We'll not pay attention to closed token trades
                                            if self.tokens[mint]["is_closed"]:
                                                continue

                                            # Key point: need to copy the token
                                            token = self.tokens[mint].copy()

                                            move_to_next_step, exit_criteria = self.token_trade_subscription(
                                                token=token,
                                                msg=msg,
                                                step=step
                                            )

                                            # Including exit criteria in token for further analytics
                                            self.tokens[mint]["exit_criteria"] = exit_criteria

                                        # Moving to the next step
                                        if move_to_next_step:
                                            step_index += 1
                                            move_to_next_step = False

                                            current_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()

                                            print("Exiting subscription criteria: {} at {}".format(
                                                self.tokens[mint]["exit_criteria"],
                                                current_time
                                            ))
                                            if suscription.value == Suscription.subscribeTokenTrade.value:
                                                if "discard_" in self.tokens[mint]["exit_criteria"]:
                                                    step_index = step["on_discard_token_go_to_step"]

                                            break

                                    except asyncio.TimeoutError:
                                        print("No trades detected during {} seconds. Moving to next step.".format(
                                            websocket_timeout
                                        ))
                                        step_index += 1
                                        self.tokens[mint]["exit_criteria"] = "market_inactivity"

                                        if "discard_market_inactivity" in step["criteria"]:
                                            step_index = step["on_discard_token_go_to_step"]

                                        move_to_next_step = False
                                        break

                            except Exception as e:
                                print("Exception in websocket: {}".format(e))
                                await websocket.close()
                                # TODO: add a safely exit way of ending the program
                                break



            except websockets.exceptions.ConnectionClosedError:
                print("Connection lost, reconnecting...")
                await asyncio.sleep(5)  # Wait before reconnecting
            except websockets.exceptions.ConnectionClosedOK:
                print("Closing connection as expected")
                break
            except Exception as e:
                print(f"Unexpected error: {e}. Exiting program abruptly.")
                break  # Exit on non-recoverable errors

    def new_token_suscription(self, msg: str, step: Dict, redisdb=RedisDB) -> bool:

        move_to_next_step = False

        if self.scanner_start_time is None:
            self.start_scanner()

        # Check if scanner needs to be torned off. scanner_activity_time == -1 -> runs forever.
        if (datetime.now() - self.scanner_start_time).total_seconds() >= self.scanner_activity_time and \
                self.scanner_activity_time != -1:
            move_to_next_step = True
            return move_to_next_step

        if self.trade_counter >= self.max_trades:
            self.add_update_token(token=msg)
            print("Max trades reached: {}".format(self.trade_counter))
            self.tokens[msg["mint"]]["exit_criteria"] = "MAX_TRADES_REACHED"
            move_to_next_step = True
            return move_to_next_step

        min_initial_buy = self.min_initial_buy
        if "min_initial_buy" in step["criteria"]:
            min_initial_buy = step["criteria"]["min_initial_buy"]

        capacity = appconfig.SCANNER_WRITTING_CAPACITY
        if "action" in step and "criteria" in step["action"]:
            if "capacity" in step["action"]["criteria"]:
                capacity = step["action"]["criteria"]["capacity"]

        trading_amount = appconfig.SCANNER_TRADING_AMOUNT
        if "trading_amount" in step["criteria"]:
            trading_amount = step["criteria"]["trading_amount"]

        trader = Trader.sniper.value        # Sniper as default trader. We can scann for Analytics
        if "trader" in step["criteria"]:
            trader = step["criteria"]["trader"]

        initial_buy_sols = initial_buy_calculator(sol_in_bonding_curve=msg["vSolInBondingCurve"])

        # if initial_buy_sols < min_initial_buy:
        #     print("Discarting token {}: initial buy {} is lower than expected {}".format(
        #         msg["mint"],
        #         initial_buy_sols,
        #         min_initial_buy
        #     ))
        #     move_to_next_step = False
        #     return move_to_next_step


        # TODO: retrieve block and check if this is a scamm token
        from bot.libs.solana_functions import get_block_by_signature
        from bot.libs.utils import get_token_data_from_block
        from bot.libs.pump_buy import (
            calculate_pump_curve_price_local,
            buy_token,
            sell_token
        )
        import asyncio

        block = asyncio.run(get_block_by_signature(signature_str=msg["signature"]))

        if block is None:
            move_to_next_step = False
            return move_to_next_step

        # Checking if the block is two old (fetching blocks produces a delay over time)
        block_time = datetime.fromtimestamp(block.value.block_time)
        block_age = (datetime.now() - block_time).total_seconds()
        if block_age > 8:
            # Block is too old and trade will be halted for X new token received.
            print("Block age is {}".format(block_age))
            self.halt_trade = int(block_age / 5) + 1
            move_to_next_step = False
            return move_to_next_step

        threshold = appconfig.SCANNER_THRESHOLD
        if "threshold" in step["criteria"]:
            threshold = step["criteria"]["threshold"]

        min_scam_buyers = step.get("criteria", []).get("min_scam_buyers", appconfig.SCANNER_MIN_SCAM_BUYERS)

        token_data_list = get_token_data_from_block(
            block=block,
            threshold=threshold,
            min_scam_buyers=min_scam_buyers
        )
        if not token_data_list:
            # if initial_buy_sols < min_initial_buy:
            #     print("Discarting token {}: initial buy {} is lower than expected {}".format(
            #         msg["mint"],
            #         initial_buy_sols,
            #         min_initial_buy
            #     ))
            move_to_next_step = False
            return move_to_next_step

        token_data = token_data_list[0]  # Note: As we're trading only one token at the time

        # Buy token immediately
        mint = Pubkey.from_string(token_data['mint'])
        bonding_curve = Pubkey.from_string(token_data['bondingCurve'])
        associated_bonding_curve = Pubkey.from_string(token_data['associatedBondingCurve'])
        crator_vault = Pubkey.from_string(token_data['buyers'][0]['creator_vault'])

        token_price_sol_local = calculate_pump_curve_price_local(token_data=token_data)

        buy_tx_hash, confirmation_stamp, token_amount = asyncio.run(
            buy_token(
                mint=mint,
                bonding_curve=bonding_curve,
                associated_bonding_curve=associated_bonding_curve,
                amount=appconfig.TRADING_DEFAULT_AMOUNT,
                slippage=appconfig.BUY_SLIPPAGE,
                token_price_sol_local=token_price_sol_local,
                crator_vault=crator_vault
            )
        )
        if buy_tx_hash:
            self.trade_counter += 1
            print("Trade #{}:  https://pump.fun/coin/{}".format(self.trade_counter, mint))
            print("** Token amount local: {}".format(token_price_sol_local))
            print("** Bought {:.6f} SOL worth of the new token with {:.1f}% slippage tolerance...".format(
                appconfig.TRADING_DEFAULT_AMOUNT,
                appconfig.BUY_SLIPPAGE * 100
            ))
        else:
            print("** Failed to buy {}. Looking for another new token".format(mint))
            move_to_next_step = True
            return move_to_next_step

        # ###############################################
        # MVP: awaiting and selling here at scanner level
        time_delta = abs(confirmation_stamp - token_data["blockTime"])
        sleep_time = 0 if appconfig.TRADING_TIME - time_delta < 0 else appconfig.TRADING_TIME - time_delta

        print("Trading-> Sleeping for {} seconds".format(sleep_time))
        time.sleep(sleep_time)

        # Sell
        print("Sell-> Time to sell it all")
        _ = asyncio.run(
            sell_token(
                mint=mint,
                token_balance=token_amount,
                bonding_curve=bonding_curve,
                associated_bonding_curve=associated_bonding_curve,
                crator_vault=crator_vault,
                slippage=appconfig.BUY_SLIPPAGE
            )
        )

        initial_buy_sols = 0  # Forcing not to write to redis
        print("\n")
        # ###############################################

        if initial_buy_sols >= min_initial_buy:
            if "action" in step and "redis" in step["action"]:
                if step["action"]["redis"] == Redis.saveToken:
                    # Read if there's any unchecked token based on reading capacity
                    tokens = redisdb.get_fresh_tokens(
                        trader=Trader.sniper
                    )

                    unchecked_tokens = [token for token in tokens if not token["is_checked"]]
                    # capacity reached: no more tokens will be added to redis
                    if len(unchecked_tokens) >= capacity:
                        return move_to_next_step
                    # Scanner has capacity to add more tokens to readis
                    for _ in range(capacity - len(unchecked_tokens)):
                        # Rule of thumb: never buy more than the token's initial buy
                        if trading_amount > initial_buy_sols:
                            print("INFO: redis -> Amount {} was reduced to {}. Token {} initial buy is lower than expected".format(
                                trading_amount,
                                initial_buy_sols,
                                "{}: {}".format(msg["name"], msg["mint"])
                            ))
                            trading_amount = initial_buy_sols

                        token_data = {
                            "amount": trading_amount,
                            "is_checked": False,
                            "is_traded": False,
                            "is_closed": False,
                            "timestamp": datetime.now().timestamp(),
                            "trader": trader,
                            "initial_buy_sols": initial_buy_sols,
                            "crator_vault": str(crator_vault)
                        }
                        token_data.update(msg)
                        save_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
                        print("Redis {}:-> Token '{}', mint {} and initial buy of {}".format(
                            save_time,
                            token_data["name"],
                            token_data["mint"],
                            initial_buy_sols
                        ))
                        redisdb.set_token(token=msg["mint"], token_data=token_data)

        # TODO: relase tokens to snipers with redis recods. At this moment we're listening to one token only
        return move_to_next_step

    def token_trade_subscription(self, token: dict,  msg: dict, step: dict) -> tuple[bool, str]:
        """
        Perform analysis on current and past trades and evaluate criteria to move on to the next step
        :param token[dict]: token stored in current PUmp pbject
        :param msg[dict]: message from Pump.fun when listening to trading tokens and modified by trading_analytics funciton.
        :param step[dict]: current step in trade roadmap list of steps.
        :return: move_to_next_step[bool] and exit_criteria[str] which is the reason why the trade subscription must be finished
        """
        time_stamps = {"buy_timestamp": None, "sell_timestamp": None}
        if "buy_timestamp" in token:
            time_stamps["buy_timestamp"] = token["buy_timestamp"]

        if "sell_timestamp" in token:
            time_stamps["sell_timestamp"] = token["sell_timestamp"]

        # By default we'll always track the developer
        traders = token.get("track_traders", [])

        if appconfig.APPMODE in [AppMode.dummy.value and AppMode.simulation.value]:
            if not token.get("trades", []):
                current_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
                print("  First trade received at: {}".format(current_time))

        # Doing some analytics like how many continuous buys have happend, etc
        new_msg = trading_analytics(
            msg=msg,
            previous_trades=token["trades"],
            amount_traded=self.trading_amount,
            pubkey=self.keypair.pubkey(),
            traders=traders,
            token_timestamps=time_stamps
        )
        # Including last message with new metadata into trades list
        if not token["trades"]:
            token["trades"] = [new_msg]
        else:
            token["trades"].append(new_msg)
        self.add_update_token(token=token)

        move_to_next_step, criteria = self.validate_criteria(
            msg=new_msg,
            amount_traded=self.trading_amount,
            criteria=step["criteria"]
        )
        return move_to_next_step, criteria

    def validate_criteria(self, msg: Dict, amount_traded: float, criteria: Dict) -> bool:
        """
        This function takes the incomming trading message from Pump.fun previouly
        trated by trading_analytics function and apply all criteria functions for the
        current step.
        :param msg: message from Pump.fun when listening to trading tokens and modified by trading_analytics funciton.
        :param criteria: list of functions and values for evaluation on exiting or not the trading position.
        :return: is_valid[True|False] and the function name as an exit_criteria .
        """
        is_valid = False
        exit_criteria = None
        for function_name, parameter in criteria.items():
            # Dynamically get the function reference
            function = getattr(criteria_functions, function_name, None)
            if callable(function):
                # Call the function with the parameter and msg
                is_valid = function(parameter, msg, amount_traded)
                # print(f"validate_criteria-> Function {function_name} returned: {is_valid}")
            else:
                if appconfig.APPMODE in [AppMode.dummy.value and AppMode.simulation.value]:
                    print(f"validate_criteria-> WARNING: {function_name} function was not found.")

            if is_valid:
                exit_criteria = function_name
                break

        return is_valid, exit_criteria

    def prepare_data(
        self,
        keypair: Keypair,
        txtype: TxType,
        token_address: str,
        amount: float = appconfig.TRADING_DEFAULT_AMOUNT,
        slippage: float = appconfig.SLIPPAGE,
        priority_fee: float = appconfig.FEES
    ):
        """
        Prepare body data when transaction will go through setted RPC endpoint
        """
        amount = amount if txtype.value == TxType.buy.value else "100%"
        denominated_in_sol = "true" if txtype.value == TxType.buy.value else "false"

        data = {
            "publicKey": str(keypair.pubkey()),
            "action": txtype.value,
            "mint": token_address,
            "amount": amount,                       # amount of SOL or tokens to trade. Can be "100%" when selling
            "denominatedInSol": denominated_in_sol, # "true" if amount is amount of SOL, "false" if amount is number of tokens
            "slippage": slippage,                   # percent slippage allowed
            "priorityFee": priority_fee,            # amount to use as priority fee
            "pool": "pump"                          # exchange to trade on. "pump" or "raydium"
        }

        return data

    def trade(self, txtype: TxType, token: str, keypair: Keypair, amount: float = None) -> str:
        """
            This function allows to BUY or SELL tokens.
            When BUYING
            - Amount of SOLs must be specified.
            When selling, we sell tokens and not solanas.
            For this MVP version, we're selling 100% of tokens.

            Parameters:
                tx_type (TxType): The type of transaction (e.g., buy, sell, transfer).
                token (str): The token symbol or identifier.
                amount (float | None): The amount to trade (can be an float when BUYING or None when SELLING).
                keypair (Keypair): The user's Solana keypair for signing the transaction.

            Returns:
                str: The transaction signature or identifier.
        """
        txSignature = None

        # Increase fees validation
        if "exit_criteria" in self.tokens[token]:
            if self.tokens[token]["exit_criteria"] == "validate_trade_timedelta_exceeded":
                self.increase_fees()

        # BUYING/SELLING tokens with an amount of Solana
        data = self.prepare_data(
            keypair=keypair,
            txtype=txtype,
            token_address=token,
            amount=amount
        )

        response = None
        retries = 0
        while True:
            # Faking transaction for none real modes
            if appconfig.APPMODE not in [AppMode.real.value]:
                current_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
                print("simulate trade -> {} MODE: returning dummy transaction at {}".format(
                    appconfig.APPMODE,
                    current_time
                ))
                txSignature = "txn_dummy_{}".format(txtype.value)
                break

            if retries == appconfig.TRADING_RETRIES and txtype.value == TxType.sell.value:
                # TODO: send a telegram message notifying that a manual sell must be done
                print("Trade->{} Error: Max retries reached. Exiting".format(txtype.value))
                break

            try:
                response = requests.post(
                    url=appconfig.PUMPFUN_TRANSACTION_URL,
                    data=data
                )
                if response.status_code != 200:
                    if txtype.value == TxType.buy.value:
                        print("Trade->{} Failed getting quote. Exiting trade function. Error: {} returned a status code {}.  Response: {}".format(
                            txtype.value,
                            appconfig.PUMPFUN_TRANSACTION_URL,
                            response.status_code,
                            response
                        ))
                        break

                    retries += 1

                    print("Trade->{} Error: {} returned a status code {}. Retrying again {} times. Response: {}".format(
                        txtype.value,
                        appconfig.PUMPFUN_TRANSACTION_URL,
                        response.status_code,
                        retries,
                        response
                    ))
                    time.sleep(appconfig.RETRYING_SECONDS)
                    continue
            except Exception as e:
                if txtype.value == TxType.buy.value:
                    print("Trade->{} Exception: {}. Exiting trade function. Message: {}".format(
                        txtype.value,
                        appconfig.PUMPFUN_TRANSACTION_URL,
                        e
                    ))
                    break

                retries += 1
                print("Trade->{} Exception: {}. Retrying again {} times. Message: {}".format(
                    txtype.value,
                    appconfig.PUMPFUN_TRANSACTION_URL,
                    retries,
                    e
                ))
                time.sleep(appconfig.RETRYING_SECONDS)
                continue

            vst = VersionedTransaction.from_bytes(response.content)
            msg = vst.message

            tx = VersionedTransaction(
                msg,
                [keypair]
            )

            config = RpcSendTransactionConfig(
                preflight_commitment=CommitmentLevel.Confirmed,
                skip_preflight=True
            )
            txPayload = SendVersionedTransaction(tx, config)

            try:
                response = requests.post(
                    url=appconfig.JITO_RPC_URL,
                    headers={"Content-Type": "application/json"},
                    data=txPayload.to_json()
                )

                current_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()

                txSignature = response.json()['result']
                print("Trade->{} Transaction: https://solscan.io/tx/{} at {}".format(
                    txtype.value,
                    txSignature,
                    current_time
                ))
                break

            except Exception:
                retries += 1
                if txtype.value == TxType.buy.value:
                    print("Trade->{} Transaction failed. Exiting trade function. Error: {}".format(
                        txtype.value,
                        response.json()["error"]["message"]
                    ))
                    break
                print("Trade->{} Transaction failed. Retrying again {} times: {}".format(
                    txtype.value,
                    retries,
                    response.json()["error"]["message"]
                ))

                time.sleep(appconfig.RETRYING_SECONDS)

        return txSignature

    def nuke(self, token: str, keypair: Keypair, amount: float = appconfig.TRADING_DEFAULT_AMOUNT) -> List[str]:
        import base58
        txSignatures = []
        try:
            buy_data = self.prepare_data(
                keypair=keypair,
                txtype=TxType.buy,
                token_address=token,
                amount=amount
            )
            sell_data = self.prepare_data(
                keypair=keypair,
                txtype=TxType.sell,
                token_address=token,
                amount=amount
            )
            response = requests.post(
                appconfig.PUMPFUN_TRANSACTION_URL,
                headers={"Content-Type": "application/json"},
                json=[buy_data, sell_data]
            )

            if response.status_code != 200: 
                print("Failed to generate transactions.")
                print(response.reason)
            else:
                encodedTransactions = response.json()
                encodedSignedTransactions = []
                txSignatures = []

                def get_tokens(message):
                    # Constants
                    TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
                    TRANSFER_INSTRUCTION_INDEX = 3  # Index for "transfer" instruction in SPL Token Program.

                    # Iterate through the instructions
                    for i, instruction in enumerate(message.instructions):
                        # Check if the program_id matches the Token Program ID
                        if instruction.program_id == TOKEN_PROGRAM_ID:
                            # Instruction data contains the operation type
                            data = instruction.data
                            if len(data) > 0 and data[0] == TRANSFER_INSTRUCTION_INDEX:
                                print(f"Instruction {i} is a Token Program 'transfer'")
                                print("Accounts involved:", instruction.accounts)
                                print("Instruction data (raw):", data)

                for index, encodedTransaction in enumerate(encodedTransactions):
                    msg = VersionedTransaction.from_bytes(
                        base58.b58decode(encodedTransaction)
                    ).message
                    get_tokens(message=msg)
                    signedTx = VersionedTransaction(
                        msg,
                        [keypair]
                    )
                    encodedSignedTransactions.append(base58.b58encode(bytes(signedTx)).decode())
                    txSignatures.append(str(signedTx.signatures[0]))

                jito_response = requests.post(
                    appconfig.JITO_RPC_URL + "/bundles",
                    headers={"Content-Type": "application/json"},
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "sendBundle",
                        "params": [
                            encodedSignedTransactions
                        ]
                    }
                )
                if jito_response.status_code == 200:
                    for i, signature in enumerate(txSignatures):
                        print(f'Nuke-> Transaction {i}: https://solscan.io/tx/{signature}')
                else:
                    print("Nuke-> error sending jito: {}".format(jito_response))

        except Exception as e:
            print(e)

        return txSignatures


def test():
    messages = [
        {
            "signature":"XGAnLe4EKCx4NNHv7soDimYZifwRndEGq1myrMDZR6DSRa6FgvcsMbpEz7XJrvRHxH6GcwPTr1oKt9jNWj5T4Uh",
            "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
            "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
            "txType":"buy",
            "tokenAmount":30582206.734745,
            "newTokenBalance":30582206.734745,
            "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
            "vTokensInBondingCurve":977513247.598136,
            "vSolInBondingCurve":32.93049999996889,
            "marketCapSol":33.68803449046135
        },
        {
            "signature":"5eZ88gyECt27NR47Rpe7yUd8t2FBxanVV5FUFLjUQjax3z4WzvWdbxAxJmMHkAHR6zVsYw9DRXuGFPBKxTVvFFY5",
            "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
            "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
            "txType":"buy",
            "tokenAmount":14605679.543704,
            "newTokenBalance":14605679.543704,
            "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
            "vTokensInBondingCurve":962907568.054432,
            "vSolInBondingCurve":33.42999999993804,
            "marketCapSol":34.717766386948036
        },
        {
            "signature":"5DcDFCF1L3A5m86GDSgCtM1vVFqXh9cQh1bf8K2Z8WobiStLUXbyE87wNFdLsEa2Az8xxY5ziC5bwEA9X2j47pkL",
            "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
            "traderPublicKey":"5gaewKWutRmK5J7iAFLFeEz8aeuhLMGsYwmXnZw8ib9L",
            "txType":"buy",
            "tokenAmount":7147473.040359,
            "newTokenBalance":7147473.040359,
            "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
            "vTokensInBondingCurve":955760095.014073,
            "vSolInBondingCurve":33.67999999992259,
            "marketCapSol":35.238968623634236
        },
        {
            "signature":"21KFHt6dgEVuk4qsetLiad9mnPwyt4Z2U6s3Sy8iefopBYffUxMd41XaYjrGjg1FWpBnn4DsAxuuZi4d9vvkSv3p",
            "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
            "traderPublicKey":"AuKQzaXcZwWH77sJmwheexwVAyVg9oGfrdmKpgPuj7at",
            "txType":"buy",
            "tokenAmount":8429777.204002,
            "newTokenBalance":8429777.204002,
            "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
            "vTokensInBondingCurve":947330317.810071,
            "vSolInBondingCurve":33.97969999990408,
            "marketCapSol":35.868903761524734
        },
        {
            "signature":"3ZNma6hgtYk5GqfjAsH2EzEXn2WfciTxuq9vWsBFdxpsk8HECu22YnY5qcWmGkGhh1Mav1Ma8M1CwntBr6ara4ux",
            "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
            "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
            "txType":"sell",
            "tokenAmount":14605679.543704,
            "newTokenBalance":0,
            "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
            "vTokensInBondingCurve":961935997.353775,
            "vSolInBondingCurve":33.46376483316213,
            "marketCapSol":34.78793279929104
        },
        {
            "signature":"4yvsGZZoT16C1Qjs6sEzBLbj7yfiA8wFHYfGbfk2p3coofKYYVwgEtJC2SxfxTqgontRKprmEfYXaHmF9f6Dkhs2",
            "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
            "traderPublicKey":"AuKQzaXcZwWH77sJmwheexwVAyVg9oGfrdmKpgPuj7at",
            "txType":"sell",
            "tokenAmount":8429777.204002,
            "newTokenBalance":0,
            "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
            "vTokensInBondingCurve":970365774.557777,
            "vSolInBondingCurve":33.173057875696294,
            "marketCapSol":34.18613758385511
        },
        {
            "signature":"55nSrxZQiCdFSxt1RGoMcDRHRJefkZFx5MZff6h3i86GswPa7yw4PJpGQfjzfzzCixuRAfs8R3zUxkKH3Wj55EuF",
            "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
            "traderPublicKey":"7d7iapfxQoMi5jM46h5vm8hHxrjsSVV2twYVSrYaCJdz",
            "txType":"sell",
            "tokenAmount":30582206.734745,
            "newTokenBalance":0,
            "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
            "vTokensInBondingCurve":1000947981.292522,
            "vSolInBondingCurve":32.15951338293637,
            "marketCapSol":32.12905563924397
        },
        {
            "signature":"4jSL1sa5nXqbvqzJ2nSL3kZwZqNTaksA7KaPDkfG6YwtN8RumMWD3UXLkaNRm3i2PUd6Wj2RGZX9huQKsFcGywFq",
            "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
            "traderPublicKey":"5gaewKWutRmK5J7iAFLFeEz8aeuhLMGsYwmXnZw8ib9L",
            "txType":"buy",
            "tokenAmount":584679.9521120004,
            "newTokenBalance":7732152.992471,
            "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
            "vTokensInBondingCurve":1000363301.34041,
            "vSolInBondingCurve":32.17830957699855,
            "marketCapSol":32.16662339960101
        },
        {
            "signature":"3nWLjZYrrbPvYGNshApaiHaQS9jidMvzYLgsqywNRNebJsNdhA4kYZhxXh6R3DRR7snYUMM5pTmCx6aQJHxPxc26",
            "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
            "traderPublicKey":"GazCsmGe5RkzZmaTtPrfYKnHqQ2RQZjq2uoW8nRUgYri",
            "txType":"sell",
            "tokenAmount":34612903.225806,
            "newTokenBalance":0,
            "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
            "vTokensInBondingCurve":1034976204.566216,
            "vSolInBondingCurve":31.102164337673464,
            "marketCapSol":30.051091223598853
        },
        {
            "signature":"22xyhmt35AutSph1ZdMcbrUADpdXPwiwe9G2VomMKuMHDUhNSeqEYN2XJXYSswHManeJnH6QJA8Z1xjfxiuwH94K",
            "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
            "traderPublicKey":"orcACRJYTFjTeo2pV8TfYRTpmqfoYgbVi9GeANXTCc8",
            "txType":"sell",
            "tokenAmount":30291642.440098997,
            "newTokenBalance":0.001214,
            "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
            "vTokensInBondingCurve":1065267847.006315,
            "vSolInBondingCurve":30.217752361964582,
            "marketCapSol":28.366342274278225
        },
        {
            "signature":"osUSpasfsvdPkGXZGoLa68X7b1PRSpgUimM8MUNtw9nwMW9em3L4UKzDUDTDuF7FMAw1XGNtNDtPRCBnE7jRdr5",
            "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
            "traderPublicKey":"5gaewKWutRmK5J7iAFLFeEz8aeuhLMGsYwmXnZw8ib9L",
            "txType":"sell",
            "tokenAmount":7732152.992471,
            "newTokenBalance":0,
            "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
            "vTokensInBondingCurve":1072999999.998786,
            "vSolInBondingCurve":30.000000000033943,
            "marketCapSol":27.958993476298126
        }
    ]


    tokens = {"mint_address": {"trades": []}}
    mint = "mint_address"
    trading_amount = 0.45
    keypair = Keypair.from_base58_string(appconfig.PRIVKEY)
    pump = Pump(
        executor_name="sniper_test",
        trader_type=Trader.sniper
    )

    # if "trades" not in tokens[mint]:
    #     tokens[mint]["trades"] = []

    # for msg in messages:
    #     # Doing some analytics like how many continuous buys have happend, etc
    #     new_msg = trading_analytics(
    #         msg=msg,
    #         previous_trades=tokens[mint]["trades"],
    #         amount_traded=trading_amount,
    #         pubkey=keypair.pubkey()
    #     )
    #     # Including last message with new metadata into trades list
    #     tokens[mint]["trades"].append(new_msg)
    #     exit_trade, exis_criteria = pump.validate_criteria(msg=new_msg, criteria=TradeRoadmap.sniper_1[2]["criteria"])
    #     if exit_trade:
    #         print("Pump.test -> Criteria out: {}".format(exis_criteria))
    # print(tokens[mint]["trades"])
    token={"mint": "ziFYNEyHmgJPGsmSA88W1fW5EUtH2VcxZhcuyxRpump"}
    pump.add_update_token(token=token)
    print("Balance before: {}".format(pump.balance))
    txn_list = pump.nuke(
        token=token["mint"],
        keypair=keypair,
        amount=1.48
    )
    balance = pump.get_balance(public_key=keypair.pubkey())
    print("Balance after:  {}".format(balance))


import json
import websockets

async def subscribe_to_trades():
    uri = "wss://mainnet.helius-rpc.com/?api-key=f32b640c-6877-43e7-924b-2035b448d17e"  # Replace with your RPC provider's WebSocket URL
    mint_address = "65ckwQJV8x8byusvMbGh4AWtRmvH8FiD3qVBHAdW1MRP"

    async with websockets.connect(uri) as websocket:
        # Subscription payload for the token account
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [
                {"mentions": [mint_address]},
                {"encoding": "base64"}
            ]
        }

        # Send subscription request
        await websocket.send(json.dumps(payload))

        # Listen for messages
        while True:
            message = await websocket.recv()
            print("Received trade update:", json.loads(message))

# Run the async function
#asyncio.run(subscribe_to_trades())
