import redis
from redisearch import Client, NumericField
from datetime import datetime
from bot.config import appconfig
from bot.lib.utils import TxType, Path, Trader
from typing import List, Dict


# Connect to Redis
client = redis.StrictRedis(
    host=appconfig.REDIS_HOST,
    port=appconfig.REDIS_PORT,
    decode_responses=True
)

# Use SCAN to find keys with "Key*" prefix

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
        self.pubsub.psubscribe({"__keyspace@0__:*"})

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
    
    def get_fresh_tokens(self, trader=Trader) -> List[Dict]:
        tokens = []
        # Search for all tokens where is_traded = False
        token_keys = self.get_token_keys()

        # query = Query('@is_traded:[0 0]').paging(0, 1000)
        # results = self.search_client.search(query)
        for key in token_keys:
            data = client.json().get(key)
            if not data:
                continue

            # Extract and validate fields
            is_traded = data.get("is_traded") == 0
            trader_match = data.get("trader", "unknown") == trader.value

            if is_traded and trader_match:
                token = {
                    "key": key,
                    "mint": key.replace("token:", ""),
                    "amount": float(data["amount"]),
                    "trader": data["trader"],
                    "is_traded": True if int(data["is_traded"]) == 1 else False,
                    "timestamp": datetime.fromtimestamp(int(data["timestamp"])),
                    "name": data["name"],
                    "ticker": data["ticker"]
                }
                tokens.append(token)

        return tokens

    def update_token(
            self,
            token: Dict,
            txn: str,
            action: TxType,
            amount: float,
            trader: Trader
        ) -> Dict:

        key = token["key"]
        data = token.copy()
        data.pop("key")
        data.pop("mint")
        data["timestamp"] = data["timestamp"].timestamp()

        # Prepare the data to update
        trading_time = datetime.now().timestamp()
        new_data = {
            "{}_time".format(action.value): trading_time,   # New trading time as timestamp
            "{}_txn".format(action.value): txn,             # New transaction string
            "is_traded": 1,
            "{}_amount".format(action.value): amount,       # Specifying the amount of buy/sell action
            "trader": trader.value
        }

        data.update(new_data)

        # Add or update the fields in the existing token
        client.json().set(key, Path.rootPath(), data)

        # Returning original token data with new data
        token.update(new_data)
        return token


def test_create_record(mint_address: str):
    redis_object = RedisDB()
    is_traded = False
    token_data = {
        "name": "Some Day",
        "ticker": "SMD",
        "amount": 15.500,
        "is_traded": 1 if is_traded else 0,
        "timestamp": datetime.now().timestamp(),
        "trader": Trader.sniper.value
    }
    redis_object.set_token(token=mint_address, token_data=token_data)


def test_update_record():
    redis_object = RedisDB()
    tokens = redis_object.get_fresh_tokens(trader=Trader.sniper)
    
    print(tokens)

    for token in tokens:
        data = redis_object.update_token(
            token=token,
            txn="txn1",
            action=TxType.buy,
            amount=15.500,
            trader=Trader.sniper
        )
        data = redis_object.update_token(
            token=data,
            txn="txn2",
            action=TxType.sell,
            amount=45.500,
            trader=Trader.sniper
        )
        print(data)
