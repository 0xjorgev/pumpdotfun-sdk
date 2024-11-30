import asyncio
import nest_asyncio
import json
import requests
import time
import websockets
import ssl
import certifi

from bot.libs.criterias import (
    trading_analytics,
    max_consecutive_buys,
    max_consecutive_sells,
    max_seconds_between_buys,
    max_seconds_in_market,
    max_sols_in_token_after_buying_in_percentage,
    trader_has_sold,
    market_inactivity
)
from bot.libs import criterias as criteria_functions
from bot.libs.utils import (
    get_solana_balance,
    get_own_token_balance,
    Trader,
    TxType
)
from bot.config import appconfig, AppMode
from bot.domain.redis_db import RedisDB

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
        {
            "step": 1,
            "name": "TRADER_SUBSCRIPTION",
            "subscription": Suscription.subscribeNewToken,
            "criteria": {
                "discard_lower_than_sols": 1.00,
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
    sniper_1 = [
        {"step": 0, "name": "WAIT_FOR_TOKEN", "redis": Redis.readToken},
        {"step": 1, "name": "TRADE_TOKEN_BUY", "action": TxType.buy},
        {
            "step": 2,
            "name": "TOKEN_SUBSCRIPTION",
            "subscription": Suscription.subscribeTokenTrade,
            "criteria": {
                "max_consecutive_buys": 2,
                "max_consecutive_sells": 1,
                "max_seconds_between_buys": 3,
                "trader_has_sold": True,
                "max_sols_in_token_after_buying_in_percentage": 100,
                "market_inactivity": 5,
                "max_seconds_in_market": 10
            }
        },
        {"step": 3, "name": "TRADE_TOKEN_SELL", "action": TxType.sell},
        {"step": 4, "name": "UNSUBSCRIBE_TO_TOKEN", "subscription": Suscription.unsubscribeTokenTrade},
        {"step": 5, "name": "CLOSE_TOKEN", "redis": Redis.closeToken},
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
        self.tokens = []

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
                    redisdb.subscribe()
                    if step["redis"] == Redis.readToken:
                        # TODO: Solve BUG: redis listener is not working at the second time
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
                                    if token_age >= appconfig.TRADING_TOKEN_TOO_OLD_SECONDS and \
                                        appconfig.APPMODE not in [AppMode.dummy.value, AppMode.simulation.value]:
                                        print("Warning: susbscribe -> Token {} is too old for trading.".format(
                                            token["name"]
                                        ))
                                        continue
                                    # Checking wallet's balance before trading                  
                                    if self.balance >= amount:
                                        self.trading_amount = amount
                                    else:
                                        print("{}: Warning: susbscribe -> Not enough balance for Token {} and amount {}. Balance is {}".format(
                                            self.executor_name,
                                            mint,
                                            amount,
                                            self.balance
                                        ))
                                        if appconfig.APPMODE in [AppMode.dummy.value, AppMode.simulation.value]:
                                            continue
                                        else:
                                            break
                                    
                                    # - move to next step and update the token as being checked
                                    token = redisdb.update_token(
                                        token=token,
                                        is_checked=False
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
                        self.remove_token(token=self.tokens[mint])
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
                            self.add_update_token(token=token_updated)

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
                                token_balance=token_balance,
                                trades=self.tokens[mint]["trades"]
                            )

                            # Update token
                            self.add_update_token(token=token_updated)

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
                        payload["keys"] = [mint for mint, _ in self.tokens.items() if self.tokens[mint]["is_checked"] and self.tokens[mint]["is_traded"]]

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
                            # If the message is about unsibscribing, then we move on to the next step
                            if suscription.value == Suscription.unsubscribeTokenTrade.value and "unsubscribed" in msg["message"].lower():
                                move_to_next_step = True
                            else:
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
                                pubkey=self.keypair.pubkey(),
                                traders=self.tokens[mint]["track_traders"] if "track_traders" in self.tokens[mint] else []
                            )
                            # Including last message with new metadata into trades list
                            self.tokens[mint]["trades"].append(new_msg)
 
                            move_to_next_step, criteria = self.validate_criteria(
                                msg=new_msg,
                                criteria=step["criteria"]
                            )
                            # Including exit criteria in token for further analytics
                            self.tokens[mint]["exit_criteria"] = criteria

                        # Moving to the next step
                        if move_to_next_step:
                            step_index += 1
                            move_to_next_step = False
                            break


                # TODO: add a safely exit way of ending the program


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
                self.add_update_token(token=msg["mint"])
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


    def validate_criteria(self, msg: Dict, criteria: Dict) -> bool:
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
                is_valid = function(parameter, msg)
                print(f"validate_criteria-> Function {function_name} returned: {is_valid}")
            else:
                print(f"validate_criteria-> Error: {function_name} not found.")
            
            if is_valid:
                exit_criteria = function_name
                break

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
            # Faking transaction for none real modes
            if appconfig.APPMODE not in [AppMode.real.value]:
                print("trade -> {} MODE: returning dummy transaction".format(appconfig.APPMODE))
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

    if "trades" not in tokens[mint]:
        tokens[mint]["trades"] = []

    for msg in messages:
        # Doing some analytics like how many continuous buys have happend, etc
        new_msg = trading_analytics(
            msg=msg,
            previous_trades=tokens[mint]["trades"],
            amount_traded=trading_amount,
            pubkey=keypair.pubkey()
        )
        # Including last message with new metadata into trades list
        tokens[mint]["trades"].append(new_msg)
        exit_trade, exis_criteria = pump.validate_criteria(msg=new_msg, criteria=TradeRoadmap.sniper_1[2]["criteria"])
        if exit_trade:
            print("Pump.test -> Criteria out: {}".format(exis_criteria))


    print(tokens[mint]["trades"])

#test()
