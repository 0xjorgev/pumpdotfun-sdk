import os


class AuthConfig:
    # our code environment
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "local")

    # Stable and liquid pairs: 0.1% to 0.5%.
    # Moderate trading volumes: 0.5% to 1%.
    # High volatility or limited liquidity: 1% to 3%
    # Very volatile or low-liquidity asset: up to 5%
    SLIPPAGE = os.environ.get("SLIPPAGE", 10)
    FEES = float(os.environ.get("FEES", 0.0005))
    FEES_BPS = float(os.environ.get("FEES", 0.0005)) * 10000   # Fees in BPS
    PRIVKEY = os.environ.get(
        "PRIVKEY",
        ""
    )
    SOL_BUY_AMOUNT = float(os.environ.get("SOL_BUY_AMOUNT", 0.001))  # here you can choose to increase/decrease the buy amount
    MIN_SOL_TRADING_AMOUNT = float(
        os.environ.get("MIN_SOL_TRADING_AMOUNT", 0.5)
    )  # Minimum balance a token must have for being traded
    RETRYING_SECONDS = 1
    RPC_URL = "https://mainnet.helius-rpc.com/?api-key=f32b640c-6877-43e7-924b-2035b448d17e"
    PUMPFUN_TRANSACTION_URL = "https://pumpportal.fun/api/trade-local"
    PUMPFUN_WEBSOCKET = "wss://pumpportal.fun/api/data"
    MARKETMAKING_SOL_BUY_AMOUNT = 0.03
    TRADING_DEFAULT_AMOUNT = 0.50
    TRADING_RETRIES = 3
    #DB
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = os.environ.get("REDIS_PORT", "6379")


appconfig: AuthConfig = AuthConfig()
