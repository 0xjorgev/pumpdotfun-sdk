from config import appconfig
import json
import requests
import time
import websockets

from enum import Enum
from solders.transaction import VersionedTransaction
from solders.keypair import Keypair
from solders.commitment_config import CommitmentLevel
from solders.rpc.requests import SendVersionedTransaction
from solders.rpc.config import RpcSendTransactionConfig


class Suscription(Enum):
    subscribeNewToken = "subscribeNewToken"
    subscribeAccountTrade = "subscribeAccountTrade"
    subscribeTokenTrade = "subscribeTokenTrade"


class TxType(Enum):
    buy = "buy"
    sell = "sell"


class TradeRoadmap:
    test = [
        {"step": 0, "name": "test", "suscription": Suscription.subscribeNewToken},
        {"step": 1, "name": "test", "suscription": Suscription.subscribeTokenTrade},
    ]


class Pump:
    sniping_token_list = []

    def __init__(self) -> None:
        self.uri_data = "wss://pumpportal.fun/api/data"
        self.accounts = []
        self.tokens = []
        self.traders = []
        self.min_initial_buy = 60000000
        self.token_target_amount = 1

    def add_account(self, account: str):
        self.accounts.append(account)

    def remove_account(self, account: str):
        if account in self.accounts:
            self.accounts.pop(self.accounts.index(account))

    # Tokens to pay attention to
    def add_token(self, token: str):
        self.tokens.append(token)

    def clear_tokens(self):
        self.tokens = []

    def remove_token(self, token: str):
        if token in self.tokens:
            self.tokens.pop(
                self.tokens.index(token)
            )

    # Traders to follow for starting and stoping pumps
    def add_trader(self, trader: str):
        self.traders.append(trader)

    def remove_trader(self, trader: str):
        if trader in self.traders:
            self.traders.pop(self.traders.index(trader))

    async def subscribe(self, steps: list):
        step_index = 0

        async with websockets.connect(self.uri_data) as websocket:
            # Subscribing to token creation events
            while True:
                suscription = steps[step_index]["suscription"]

                payload = {
                    "method": suscription.value,
                }

                if suscription.value == Suscription.subscribeAccountTrade.value:
                    payload["keys"] = self.accounts

                if suscription.value == Suscription.subscribeTokenTrade.value:
                    payload["keys"] = self.tokens

                await websocket.send(json.dumps(payload))

                async for message in websocket:
                    msg = json.loads(message)
                    move_to_next_step = False

                    # This is the first message we get when we connect
                    if "message" in msg:
                        print(msg["message"])
                        continue

                    if suscription.value == Suscription.subscribeNewToken.value:
                        move_to_next_step = self.newTokenSuscription(msg=msg)

                    if suscription.value == Suscription.subscribeTokenTrade.value:
                        move_to_next_step = self.tokenTradeSuscription(msg=msg)

                    # Moving to the next step or going back to the first one
                    if move_to_next_step:
                        step_index += 1
                        move_to_next_step = False
                        step_index = 0 if step_index >= len(steps) else step_index
                        roadmap_name = steps[step_index]["name"]
                        if step_index == 0:
                            print("subscribe -> restarting roadmap '{}'".format(roadmap_name))
                        
                        break
                
                # TODO: add exiting way of ending the program


    def newTokenSuscription(self, msg: str) -> bool:
        if "initialBuy" in msg and int(msg["initialBuy"]) > self.min_initial_buy:
            # Listening to a predefined amount of tokens
            if len(self.tokens) < self.token_target_amount:
                print(
                    "Symbol: {}. mint: {}. tarder: {}. Initial buy: {}".format(
                        msg["symbol"],
                        msg["mint"],
                        msg["traderPublicKey"][:5],
                        int(msg["initialBuy"])
                    )
                )
                self.clear_tokens()  # TODO: Change this when more than one token will be checked
                self.add_token(token=msg["mint"])
                # testing
                self.marketMaking(token=msg["mint"])

        return len(self.tokens) == self.token_target_amount

    def tokenTradeSuscription(self, msg: str) -> bool:
        # TODO: remove this temporal validation for testing
        if not self.traders and "txType" in msg:
            if TxType.buy.value == msg["txType"]:
                self.add_trader(trader=msg["traderPublicKey"])

        if "traderPublicKey" in msg and msg["traderPublicKey"] in self.traders:
            if TxType.buy.value == msg["txType"]:
                print("Starting pumping bot. Listening to trader: {} - Buy: {}. MarketCap: {}".format(
                        msg["traderPublicKey"][:5],
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

    # def start_suscription(self, suscription=Suscription.subscribeTokenTrade):
    #     # Run the subscribe function
    #     asyncio.get_event_loop().run_until_complete(
    #         self.subscribe(suscription=suscription)
    #     )
    def marketMaking(
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

        # BUYING tokens with an amount of Solana
        data = {
            "publicKey": str(keypair.pubkey()),
            "action": TxType.buy.value,
            "mint": token,
            "amount": amount,                # amount of SOL or tokens to trade
            "denominatedInSol": "true",      # "true" if amount is amount of SOL, "false" if amount is number of tokens
            "slippage": appconfig.SLIPPAGE,  # percent slippage allowed
            "priorityFee": appconfig.FEES,   # amount to use as priority fee
            "pool": "pump"                   # exchange to trade on. "pump" or "raydium"
        }

        response = None
        retries = 0
        while True:
            response = requests.post(
                url=appconfig.PUMPFUN_TRANSACTION_URL,
                data=data
            )
            if response.status_code != 200:
                time.sleep(appconfig.RETRYING_SECONDS)
                continue

            tx = VersionedTransaction(
                VersionedTransaction.from_bytes(response.content).message,
                [keypair]
            )

            config = RpcSendTransactionConfig(
                preflight_commitment=CommitmentLevel.Confirmed
            )
            txPayload = SendVersionedTransaction(tx, config)

            response = requests.post(
                url=appconfig.RPC_URL,
                headers={"Content-Type": "application/json"},
                data=txPayload.to_json()
            )
            if response.status_code == 200:
                try:
                    txSignature = response.json()['result']
                    print(f'Transaction: https://solscan.io/tx/{txSignature}')
                    break

                except Exception as e:
                    print("marketMaking->Buy. Transaction failed. retrying again: {}".format(
                        response.json()["error"]["message"]
                    ))
                    retries += 1
                    time.sleep(appconfig.RETRYING_SECONDS)
                    if retries == appconfig.MARKET_MAKING_RETRIES:
                        print("marketMaking.error-> Buy: Max retries reached. Exiting")
                        break
                    continue

        # SELLING 100% of tokens
        data = {
            "publicKey": keypair.pubkey(),
            "action": TxType.sell.value,
            "mint": token,
            "amount": "100%",
            "denominatedInSol": "false",
            "slippage": appconfig.SLIPPAGE,
            "priorityFee": appconfig.FEES,
            "pool": "pump"
        }

        response = None
        while True:
            response = requests.post(
                url=appconfig.PUMPFUN_TRANSACTION_URL,
                data=data
            )
            if response.status_code != 200:
                time.sleep(appconfig.RETRYING_SECONDS)
                continue

            tx = VersionedTransaction(
                VersionedTransaction.from_bytes(response.content).message,
                [keypair]
            )

            config = RpcSendTransactionConfig(
                preflight_commitment=CommitmentLevel.Confirmed
            )
            txPayload = SendVersionedTransaction(tx, config)

            response = requests.post(
                url=appconfig.RPC_URL,
                headers={"Content-Type": "application/json"},
                data=txPayload.to_json()
            )
            if response.status_code == 200:
                try:
                    txSignature = response.json()['result']
                    print(f'Transaction: https://solscan.io/tx/{txSignature}')
                    break
                except Exception as e:
                    print("marketMaking->Buy. Transaction failed. retrying again: {}".format(
                        response.json()["error"]["message"]
                    ))
                    time.sleep(appconfig.RETRYING_SECONDS)
                    continue
