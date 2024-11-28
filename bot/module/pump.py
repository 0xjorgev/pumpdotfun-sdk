import asyncio
import nest_asyncio
import json
import requests
import time
import websockets
import ssl
import certifi

from bot.libs.criterias import trading_analytics
from bot.libs.utils import (
    get_solana_balance,
    get_own_token_balance,
    Trader,
    TxType
)
from config import appconfig
from domain.redis_db import RedisDB

from datetime import datetime
from enum import Enum
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


class TradeRoadmap:
    test = [
        {"step": 0, "name": "test", "subscription": Suscription.subscribeNewToken},
        {"step": 1, "name": "test", "subscription": Suscription.subscribeTokenTrade},
    ]
    sniper_copytrade = [ # TODO: to be developed
        {"step": 0, "name": "WAIT_FOR_TRADERS", "redis": Redis.readTraders},
        {"step": 1, "name": "TRADER_SUBSCRIPTION", "subscription": Suscription.subscribeNewToken},
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
    sniper_1 = [
        {"step": 0, "name": "WAIT_FOR_TOKEN", "redis": Redis.readToken},
        {"step": 1, "name": "TRADE_TOKEN", "action": TxType.buy},
        {
            "step": 2,
            "name": "TOKEN_SUBSCRIPTION",
            "subscription": Suscription.subscribeTokenTrade,
            "criteria": {
                "max_consecutive_buys": 2,
                "max_consecutive_sells": 1,
                "max_seconds_between_buys": 3,
                "developer_has_sold": True,
                "max_sols_in_token_after_buying_in_percentage": 100,
                "market_inactivity": 10,
                "max_seconds_in_market": 60
            }
        },
        {"step": 3, "name": "TRADE_TOKEN", "action": TxType.sell},
        {"step": 4, "name": "UNSUBSCRIBE_TO_TOKEN", "subscription": Suscription.unsubscribeTokenTrade},
        {"step": 5, "name": "CLOSE_TOKEN", "grooming": Redis.closeToken},
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
        self.min_initial_buy = 60000000
        self.tokens_to_be_traded = appconfig.TRADING_TOKENS_AT_THE_SAME_TIME
        self.trading_amount = amount
        self.trading_sell_amount = amount * (1 + target)    # TODO: apply this when we have the Bounding Courve
        
        self.keypair = Keypair.from_base58_string(appconfig.PRIVKEY)
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.balance = self.get_balance(public_key=self.keypair.pubkey())


    def get_balance(self, public_key):
        balance = asyncio.run(get_solana_balance(public_key=public_key))
        return balance

    def get_tkn_balance(self, wallet_pubkey, token_account):
        token_balance = asyncio.run(get_own_token_balance(
                wallet_pubkey=wallet_pubkey,
                token_mint_addres=token_account
            )
        )
        return token_balance

    def add_account(self, account: str):
        self.accounts.append(account)

    def remove_account(self, account: str):
        if account in self.accounts:
            self.accounts.pop(self.accounts.index(account))

    # Tokens to pay attention to
    def add_token(self, token: Dict):
        self.tokens[token["mint"]] = token

    def remove_token(self, token: str):
        if token["mint"] in self.tokens:
            del self.tokens["miunt"]

    def clear_tokens(self):
        self.tokens = []

    # Traders to follow for starting and stoping pumps
    def add_trader(self, trader: str):
        self.traders.append(trader)

    def remove_trader(self, trader: str):
        if trader in self.traders:
            self.traders.pop(self.traders.index(trader))

    async def subscribe(self, steps: list):
        step_index = 0
        redisdb = RedisDB()
        await asyncio.sleep(2)  # Wait 2 seconds for the redis connection to start

        # SSL context is required in Mac and not on windows
        async with websockets.connect(self.uri_data, ssl=self.ssl_context) as websocket:
            # Subscribing to token creation events
            while True:
                # Step index reset if necessary
                step_index = 0 if step_index >= len(steps) else step_index
                roadmap_name = steps[step_index]["name"]
                if step_index == 0:
                    print("subscribe -> restarting roadmap '{}'".format(roadmap_name))
                    
                print("Step {}: {}".format(
                    step_index,
                    steps[step_index]["name"]
                ))

                step = steps[step_index]

                # REDIS DB HANDLING
                if "redis" in step:
                    # Listen to redis change
                    if step["redis"] == Redis.readToken:
                        for message in redisdb.pubsub.listen():
                            if message["type"] == "psubscribe":
                                print("Subscribed to redis")
                            if message["type"] == "pmessage":
                                # Parse the message
                                key = ":".join(message["channel"].split(":")[1:])
                                # - Take key and retrieve token from redis
                                tokens = redisdb.get_fresh_tokens(
                                    trader=Trader.sniper,
                                    mint_address=key
                                )
                                # - Ignore token that are not fresh or for not the current trader type
                                if not tokens:
                                    continue
                                # - Get token information
                                # TODO: snipe againt to more than one token at the same time
                                token = tokens[0]

                                mint = token["mint"]
                                amount = token["amount"]
                                
                                if self.balance >= amount:
                                    self.trading_amount = amount
                                else:
                                    print("{}: Not enough balance for Token {} and amount {}. Balance is {}".format(
                                        self.executor_name,
                                        mint,
                                        amount,
                                        self.balance
                                    ))
                                    continue
                                
                                # - move to next step and update the token as being checked
                                token = redisdb.update_token(
                                    token=token,
                                    is_checked=False
                                )
                                self.add_token(token=token)

                                # - safely exit this listening
                                redisdb.pubsub.close()

                                print("Token {} assigned to {} to trade {}".format(
                                    token["mint"],
                                    self.executor_name,
                                    self.trading_amount
                                ))
                                break

                        step_index += 1

                        continue
                    if step["redis"] == Redis.closeToken:
                        # Save in redis the amount of buy and sell with timestamp. Calculate P&L
                        step_index += 1
                        continue
                
                if "action" in step:
                    if step["action"] == TxType.buy:
                        for mint_address, token_data in self.tokens.items():
                            txn = self.trade(
                                txtype=TxType.buy,
                                token=mint_address,
                                keypair=self.keypair,
                                amount=self.trading_amount
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
                            self.remove_token(token=token)
                            self.add_token(token=token_updated)

                            step_index += 1
                        continue

                    if step["action"] == TxType.sell:
                        for mint_address, token_data in self.tokens.items():
                            txn = self.trade(
                                txtype=TxType.buy,
                                token=mint_address,
                                keypair=self.keypair,
                                amount=None             # Amount will be handled buy trade function
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
                                token_balance=token_balance
                            )

                            # Update token
                            self.remove_token(token=token)
                            self.add_token(token=token_updated)

                            step_index += 1
                        continue

                if "subscription" in step:
                    suscription = step["subscription"]

                    payload = {
                        "method": suscription.value,
                    }

                    if suscription.value == Suscription.subscribeAccountTrade.value:
                        payload["keys"] = self.accounts

                    if suscription.value == Suscription.subscribeTokenTrade.value:
                        payload["keys"] = [mint for mint, _ in self.tokens.items() if not self.tokens[mint]["is_traded"]]

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

                    # MAIN WEBSOCKET THREAD
                    async for message in websocket:
                        msg = json.loads(message)
                        move_to_next_step = False

                        # This is the first message we get when we connect
                        if "message" in msg:
                            print(msg["message"])
                            continue

                        if suscription.value == Suscription.subscribeNewToken.value:
                            move_to_next_step = self.new_token_suscription(msg=msg)

                        if suscription.value == Suscription.subscribeTokenTrade.value:
                            # Getting the mint address we'll work with
                            mint = msg["mint"]

                            # We'll not pay attention to closed token trades
                            if self.tokens[mint]["is_closed"]:
                                continue

                            if "trades" not in self.tokens[mint]:
                                self.tokens[mint]["trades"] = []

                            # Doing some analytics like how many continuous buys have happend, etc
                            new_msg = trading_analytics(
                                msg=msg,
                                previous_trades=self.tokens[mint]["trades"],
                                amount_traded=self.trading_amount,
                                pubkey=self.keypair.pubkey()
                            )
                            # Including last message with new metadata into trades list
                            self.tokens[mint]["trades"].append(new_msg)
 
                            move_to_next_step, criteria = self.validate_criteria(
                                trades=self.tokens[mint]["trades"],
                                criteria=step["criteria"]
                            )
                            # Including exit criteria in token for further analytics
                            self.tokens[0]["exit_criteria"] = criteria

                        # Moving to the next step
                        if move_to_next_step:
                            step_index += 1
                            move_to_next_step = False
                            break


                if "grooming" in step:
                    grooming = step["grooming"]
                    if grooming.value == Redis.closeToken.value:
                        self.remove_token(token=self.tokens[0])
                        # TODO: copy redis data to postgres and delete data from redis

                # TODO: add a saftley exit way of ending the program


    def new_token_suscription(self, msg: str) -> bool:
        if "initialBuy" in msg and int(msg["initialBuy"]) > self.min_initial_buy:
            # Listening to a predefined amount of tokens
            if len(self.tokens) < self.tokens_to_be_traded:
                print(
                    "New token subscription. Symbol: {}. mint: {}. tarder: {}. Initial buy: {}".format(
                        msg["symbol"],
                        msg["mint"],
                        msg["traderPublicKey"][:5],
                        int(msg["initialBuy"])
                    )
                )
                self.clear_tokens()  # TODO: Change this when more than one token will be checked
                self.add_token(token=msg["mint"])
                # testing
                # self.marketMaking(token=msg["mint"])

        # TODO: relase tokens to snipers with redis recods. At this moment we're listening to one token only
        return len(self.tokens) == self.tokens_to_be_traded


    def token_copytrade_suscription(self, msg: str) -> bool:
        # TODO: remove this temporal validation for testing
        # if not self.traders and "txType" in msg:
        #     if TxType.buy.value == msg["txType"]:
        #         self.add_trader(trader=msg["traderPublicKey"])

        if "traderPublicKey" in msg and msg["traderPublicKey"] in self.traders:
            if TxType.buy.value == msg["txType"]:
                print("Starting pumping bot. Listening to trader: {} - Buy: {}. MarketCap: {}".format(
                        msg["traderPublicKey"][:6],
                        msg["tokenAmount"],
                        msg["marketCapSol"]
                    )
                )

            if TxType.sell.value == msg["txType"]:
                print("Stoping pumping bot. Sell: {}. MarketCap: {}".format(
                        msg["tokenAmount"],
                        msg["marketCapSol"]
                    )
                )
                self.traders = []
                return True

        return False

    # TODO: implement criteria validation an required functions from lib.utils
    def validate_criteria(self, trades: List[Dict], criteria: Dict) -> bool:
        is_valid = False
        exit_criteria = None
        for key, value in criteria.items():
            {
                "max_seconds_between_buys": 3,
                "developer_has_sold": True,
                "same_balance": True,
                "market_inactivity": 10,
                "max_seconds_in_market": 30
            }

        return is_valid, exit_criteria
        


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

        denominated_in_sol = "true" if txtype.value == TxType.buy.value else "false"
        amount = amount if txtype.value == TxType.buy.value else "100%"

        # BUYING/SELLING tokens with an amount of Solana
        data = {
            "publicKey": str(keypair.pubkey()),
            "action": txtype.value,
            "mint": token,
            "amount": amount,                       # amount of SOL or tokens to trade. Can be "100%" when selling
            "denominatedInSol": denominated_in_sol, # "true" if amount is amount of SOL, "false" if amount is number of tokens
            "slippage": appconfig.SLIPPAGE,         # percent slippage allowed
            "priorityFee": appconfig.FEES,          # amount to use as priority fee
            "pool": "pump"                          # exchange to trade on. "pump" or "raydium"
        }

        response = None
        retries = 0
        while True:
            if appconfig.ENVIRONMENT == "DUMM":
                print("trade -> DUMMY MODE: returning dummy transaction")
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
                preflight_commitment=CommitmentLevel.Confirmed
            )
            txPayload = SendVersionedTransaction(tx, config)

            try:
                response = requests.post(
                    url=appconfig.RPC_URL,
                    headers={"Content-Type": "application/json"},
                    data=txPayload.to_json()
                )

                txSignature = response.json()['result']
                print("Trade->{} Transaction: https://solscan.io/tx/{}".format(
                    txtype.value,
                    txSignature
                ))
                break
                

            except Exception as e:
                retries += 1
                print("Trade->{} Transaction failed. Retrying again {} times: {}".format(
                    txtype.value,
                    retries,
                    response.json()["error"]["message"]
                ))
                
                time.sleep(appconfig.RETRYING_SECONDS)

        return txSignature


    def market_making(
        self,
        token: str,
        amount: int = appconfig.MARKETMAKING_SOL_BUY_AMOUNT
    ):
        """marketMaking will buy an amount of tokens and inmediatelly sell them

        Args:
            token (str): token mint address
            amount (int): amount of Solana
        """
        keypair = Keypair.from_base58_string(appconfig.PRIVKEY)

        txn = self.buy(token=token, amount=amount, keypair=keypair)

        