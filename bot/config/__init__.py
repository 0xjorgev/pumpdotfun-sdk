import os
from enum import Enum
from solders.pubkey import Pubkey


class AppMode(Enum):
    dummy = "DUMMY"
    simulation = "SIMULATION"
    real = "REAL"
    analytics = "ANALYTICS"


class AuthConfig:
    # our code environment
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "local")
    APPMODE = os.environ.get("APPMODE", AppMode.simulation.value)

    TIME_FORMAT = "%b %-d %-I:%M:%S %p"

    # Stable and liquid pairs: 0.1% to 0.5%.
    # Moderate trading volumes: 0.5% to 1%.
    # High volatility or limited liquidity: 1% to 3%
    # Very volatile or low-liquidity asset: up to 5%
    SLIPPAGE = os.environ.get("SLIPPAGE", 40)
    FEES = float(os.environ.get("FEES", 0.0015))
    FEES_INCREASMENT = 0.000805
    FEES_TIMEDELTA_IN_SECONDS = 1.0     # Tolerance to delays between buying and entering in
                                        # the trade because of lower fees                      # noqa: E116
    FEES_BPS = float(os.environ.get("FEES", 0.0005)) * 10000   # Fees in BPS
    PRIVKEY = os.environ.get(
        "PRIVKEY",
        ""
    )
    MIN_SOL_TRADING_AMOUNT = float(
        os.environ.get("MIN_SOL_TRADING_AMOUNT", 0.5)
    )  # Minimum balance a token must have for being traded
    RETRYING_SECONDS = 1
    RPC_URL_HELIUS = "https://mainnet.helius-rpc.com/?api-key=f32b640c-6877-43e7-924b-2035b448d17e"
    WSS_URL_QUICKNODE = "wss://orbital-hardworking-knowledge.solana-mainnet.quiknode.pro/be0d348509d4f9ae26cd7371cd7a08b7d784324d"
    RPC_URL_QUICKNODE = "https://orbital-hardworking-knowledge.solana-mainnet.quiknode.pro/be0d348509d4f9ae26cd7371cd7a08b7d784324d"
    RPC_URL = "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1"
    PUMPFUN_TRANSACTION_URL = "https://pumpportal.fun/api/trade-local"
    PUMPFUN_WEBSOCKET = "wss://pumpportal.fun/api/data"
    MARKETMAKING_SOL_BUY_AMOUNT = 0.03
    TRADING_DEFAULT_AMOUNT = float(os.environ.get("TRADING_DEFAULT_AMOUNT", 0.01))
    TRADING_CRITERIA_TRADE_RELEVANT_AMOUNT = float(
        os.environ.get(
            "TRADING_CRITERIA_TRADE_RELEVANT_AMOUNT",
            0.05
        )
    )  # Min amount of a trade to be considered relevat enough for criteria decision making.
    TRADING_CRITERIA_CONSECUTIVES_NON_RELEVANT_TRADES_TOLERANCE = float(
        os.environ.get(
            "TRADING_CRITERIA_CONSECUTIVES_NON_RELEVANT_TRADES_TOLERANCE",
            3
        )
    )
    TRADING_TOKENS_AT_THE_SAME_TIME = 1
    TRADING_EXPECTED_GAIN_IN_PERCENTAGE = 0.5
    TRADING_RETRIES = 6
    TRADING_TOKEN_TOO_OLD_SECONDS = 5
    TRADING_MARKETING_INACTIVITY_TIMEOUT = 60
    SCANNER_MIN_TRADING_AMOUNT = 1.00       # Min Sols a token must have as first buy to be considered for trading
    SCANNER_WRITTING_CAPACITY = 1           # How many tokens to scanned will write at the same time in Redis
    SCANNER_TRADING_AMOUNT = 1.00           # Sols the sniper will trade
    SCANNER_WORKING_TIME = 600               # Seconds the scanner will be working
    SCANNER_PUMPDONTFUN_INITIAL_FUND = 30   # Sols placed by pump.fun to launch a token
    # DB
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = os.environ.get("REDIS_PORT", "6379")
    # BUY and SELL
    BUY_SLIPPAGE = 0.2  # 20% slippage tolerance for buying
    SELL_SLIPPAGE = 0.2
    LAMPORTS_PER_SOL = 1_000_000_000
    PUMP_PROGRAM = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
    PUMP_GLOBAL = Pubkey.from_string("4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf")
    PUMP_EVENT_AUTHORITY = Pubkey.from_string("Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1")
    PUMP_FEE = Pubkey.from_string("CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM")
    SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
    SYSTEM_TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    SYSTEM_ASSOCIATED_TOKEN_ACCOUNT_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
    SYSTEM_RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
    SOL = Pubkey.from_string("So11111111111111111111111111111111111111112")
    TOKEN_DECIMALS = 6
    TRADING_TIME = 35


appconfig: AuthConfig = AuthConfig()
