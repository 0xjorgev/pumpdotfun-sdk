import json
import redis
from redisearch import Client, NumericField
from datetime import datetime
from bot.config import appconfig
from bot.libs.utils import TxType, Path, Trader
from typing import List, Dict


class RedisDB:
    key_prefix = "token"
    index_name = "token_idx"

    def __init__(self) -> None:
        self.client = redis.StrictRedis(
            host=appconfig.REDIS_HOST,
            port=appconfig.REDIS_PORT,
            db=0, # DB index number
            decode_responses=True
        )
        self.search_client = Client("token_idx", conn=self.client)
        self.create_index()
        # Event listener
        self.pubsub = self.client.pubsub()
    
    def subscribe(self):
        self.pubsub.psubscribe({"__keyspace@0__:*"})
    
    def unsubscribe(self):
        self.pubsub.unsubscribe({"__keyspace@0__:*"})

    def stop(self):
        print("Unsubscribing and cleaning up...")
        self.pubsub.punsubscribe()
        self.pubsub.close()

    def index_exists(self, index_name):
        indexes = self.client.execute_command("FT._LIST")
        return index_name in indexes

    def create_index(self):
        if not self.index_exists(RedisDB.index_name):
            # Create the index on JSON fields
            self.search_client.create_index([
                NumericField("amount"),
                NumericField("timestamp"),
                NumericField("is_traded")
            ])
        else:
            print("Index '{}' already exists".format(RedisDB.index_name))

    def set_token(self, token: str, token_data: Dict)->bool:
        response = self.client.json().set(
            name="{}:{}".format(RedisDB.key_prefix, token),
            path=Path.rootPath(),
            obj=token_data
        )
        return response

    def get_token_keys(self, pattern="token:*"):
        keys = self.client.scan_iter(match=pattern)
        return keys
    
    def get_fresh_tokens(self, trader=Trader, mint_address: str = None) -> List[Dict]:
        tokens = []
        token_keys = []
        # Search for all tokens where is_checked = False
        if mint_address:
            token_keys = [mint_address]
        else:
            token_keys = self.get_token_keys()

        # query = Query('@is_traded:[0 0]').paging(0, 1000)
        # results = self.search_client.search(query)
        for key in token_keys:
            data = self.client.json().get(key)
            if not data:
                continue

            # Extract and validate fields
            is_checked = data.get("is_checked", False)

            trader_match = data.get("trader", "unknown") == trader.value

            if not is_checked and trader_match:
                track_traders = data["track_traders"] if "track_traders" in data else []
                token = {
                    "key": key,
                    "mint": key.replace("token:", ""),      # Mint address from key value
                    "amount": float(data["amount"]),        # Amount of Sols to be traded
                    "trader": data["trader"],               # Trader bot that will execute this trade
                    "is_checked": is_checked,               # By default is_checked is False.
                    "timestamp": data["timestamp"],         # Getting timestamp from redis
                    "name": data["name"],                   # Token name
                    "symbol": data["symbol"],               # Token's symbol
                    "track_traders": track_traders          # Tracking other traders activity
                }
                tokens.append(token)

        return tokens

    def update_token(
            self,
            token: Dict,
            txn: str = None,
            action: TxType = None,
            amount: float = None,
            trader: Trader = None,
            is_checked: bool = True,
            is_closed: bool = False,
            balance: float = None,
            token_balance: float = None,
            trades: List[Dict] = []
        ) -> Dict:

        key = token["key"]
        data = token.copy()
        data.pop("key")
        data.pop("mint")
        #data["timestamp"] = data["timestamp"].isoformat()

        # Prepare the data to update
        trading_time = datetime.now().timestamp()
        new_data = {}
        if not is_checked:
            new_data = {
                "checked_time": trading_time,
                "is_checked": True,
                "is_traded": False,
                "is_closed": is_closed,
                "trades": []                    # We'll keep track of every buy/sell during our trade
            }
        else:
            for trade in trades:
                trade["timestamp"] = trade["timestamp"]

            new_data = {
                "{}_time".format(action.value): trading_time,           # New trading time as timestamp
                "{}_txn".format(action.value): txn,                     # New transaction string
                "is_traded": True,
                "{}_amount".format(action.value): amount,               # Specifying the amount of buy/sell action
                "trader": trader.value,
                "{}_balance".format(action.value): balance,             # Wallet balance before buy / after sell
                "{}_token_balance".format(action.value): token_balance,  # Token balance after buy
                "is_closed": is_closed,
                "trades": trades
            }

        data.update(new_data)

        # Add or update the fields in the existing token
        self.client.json().set(key, Path.rootPath(), data)

        # Returning original token data with new data
        token.update(new_data)
        return token


def test_create_record(mint_address: str):
    redis_object = RedisDB()
    is_traded = False
    token_data = {
        "name": "Some Day",
        "symbol": "SMD",
        "amount": 15.500,
        "is_traded": is_traded,
        "timestamp": datetime.now().timestamp(),
        "trader": Trader.sniper.value
    }
    redis_object.set_token(token=mint_address, token_data=token_data)


def test_update_record():
    redis_object = RedisDB()
    tokens = redis_object.get_fresh_tokens(trader=Trader.sniper)
    
    trades = [
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
            "marketCapSol":33.68803449046135,
            "timestamp":1732830811.317805,
            "consecutive_buys":1,
            "consecutive_sells":0,
            "vSolInBondingCurve_Base":32.480499999968885,
            "seconds_between_buys":0,
            "seconds_between_sells":0,
            "market_inactivity":0,
            "max_seconds_in_market":0,
            "max_consecutive_buys":[
                {
                    "quantity":4,
                    "sols":1.4991999999351904
                },
                {
                    "quantity":1,
                    "sols":0.018796194062183247
                }
            ],
            "developer_has_sold":False,
            "sols_in_token_after_buying":0.45000000000000284
        }
    ]

    for token in tokens:
        data = redis_object.update_token(
            token=token,
            txn="txn1",
            action=TxType.buy,
            amount=15.500,
            trader=Trader.sniper,
            is_checked=True
        )
        data = redis_object.update_token(
            token=data,
            txn="txn2",
            action=TxType.sell,
            amount=45.500,
            trader=Trader.sniper,

            is_closed = False,
            balance = 21.500,
            token_balance = 1234567890,
            trades = trades
        )
        print(data)

#test_update_record()
