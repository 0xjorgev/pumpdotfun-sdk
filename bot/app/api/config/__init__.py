import os
from enum import Enum


class AppMode(Enum):
    development = "DEVELOPMENT"
    real = "PRODUCTION"


class AuthConfig:
    # our code environment
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "local")
    APPMODE = os.environ.get("APPMODE", AppMode.development.value)

    TIME_FORMAT = "%b %-d %-I:%M:%S %p"

    # Stable and liquid pairs: 0.1% to 0.5%.
    # Moderate trading volumes: 0.5% to 1%.
    # High volatility or limited liquidity: 1% to 3%
    # Very volatile or low-liquidity asset: up to 5%
    SLIPPAGE = os.environ.get("SLIPPAGE", 40)
    FEES = float(os.environ.get("FEES", 0.0015))
    FEES_INCREASMENT = 0.000805
    FEES_BPS = float(os.environ.get("FEES", 0.0005)) * 10000   # Fees in BPS
    GHOSTFUNDS_FIX_FEES = 0.00001
    GHOSTFUNDS_FEES_PERCENTAGES = {
        1: 0.1,
        100: 0.09,
        500: 0.08,
        1000: 0.07
    }
    GHOSTFUNDS_FIX_FEES_RECEIVER = "GhoStvfwEx5FYEX7jMEpsu6R13xJFJdTLs4BxEpB9qxQ"
    GHOSTFUNDS_VARIABLE_FEES_RECEIVER = "Ghost5UYkXcgLdja6Uhyac3gTnuefrx7TuSFat5JUVdW"
    BACKEND_MAX_INSTRUCTIONS_PER_TRANSACTION = 24

    MIN_TOKEN_VALUE = 0.0001  # Min value of a token to not be considered dust
    MAX_RETRIEVABLE_ACCOUNTS = 1100  # Safety. To avoid api server to crash
    MAX_RETRIEVABLE_ACCOUNTS_MESSAGE = "TOO_MANY_ATAS"

    RETRIES = 5
    RPC_URL_HELIUS = "https://mainnet.helius-rpc.com/?api-key=f32b640c-6877-43e7-924b-2035b448d17e"
    RPC_URL_QUICKNODE = "https://orbital-hardworking-knowledge.solana-mainnet.quiknode.pro/be0d348509d4f9ae26cd7371cd7a08b7d784324d"  # noqa: E501
    RPC_JITO_URL = "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1"
    SOL_USD_QUOTE = [
        {
            "url": "https://quote-api.jup.ag/v6/quote?inputMint=So11111111111111111111111111111111111111112&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000000&slippageBps=1",
            "vendor": "jupiter",
        },
        {
            "url": "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
            "vendor": "coingecko",
        }
    ]

    # PAGINATION
    DEFAULT_PAGE = 1
    DEFAULT_ITEMS_PER_PAGE = 10

    # DB
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = os.environ.get("REDIS_PORT", "6379")


appconfig: AuthConfig = AuthConfig()
