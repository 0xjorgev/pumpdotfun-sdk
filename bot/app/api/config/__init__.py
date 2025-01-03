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

    RETRIES = 5
    RPC_URL_HELIUS = "https://mainnet.helius-rpc.com/?api-key=f32b640c-6877-43e7-924b-2035b448d17e"
    RPC_URL_QUICKNODE = "https://orbital-hardworking-knowledge.solana-mainnet.quiknode.pro/be0d348509d4f9ae26cd7371cd7a08b7d784324d"
    RPC_JITO_URL = "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1"
    
    #PAGINATION
    DEFAULT_PAGE = 1
    DEFAULT_ITEMS_PER_PAGE = 10
    
    #DB
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = os.environ.get("REDIS_PORT", "6379")


appconfig: AuthConfig = AuthConfig()
