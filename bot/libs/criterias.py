from datetime import datetime
from typing import Dict, List
from bot.config import appconfig
from bot.libs.utils import TxType

from solders.pubkey import Pubkey


def same_balance(amount: float, trades: List[Dict]) -> bool:
    criteria_met = False

    return criteria_met

def exit_on_first_sale(msg: Dict) -> bool:
    return msg["txType"].lower() == TxType.sell.value

def trading_analytics(
        msg: Dict,
        previous_trades: List,
        amount_traded: float,
        pubkey: Pubkey,
        traders: List[str] = []
    ) -> Dict:
    """
    This function compare incomming messages with previous trades and include in the msg
    statistics new attributes that will help on deciding exit trading criteria
    :param msg: Incomming message when listening to Pump.fun tokens.
    :param previous_trades: history of incomming messages
    :return: msg with more attributes
    """

    new_msg = msg.copy()
    new_msg["timestamp"] = datetime.now().timestamp()       # Including timestamp in incomming message

    # Checking if the trade position is relevant enough to be considering for criteria
    new_msg["is_relevant_trade"] = True

    # Default values that might change
    new_msg["consecutive_buys"] = 1 if msg["txType"].lower() == TxType.buy.value else 0
    new_msg["consecutive_sells"] = 1 if msg["txType"].lower() == TxType.sell.value else 0

    if not previous_trades:
        aprox = 0
        # Math calculation for Solana in Bonding Courve just before we bought
        if new_msg["traderPublicKey"] == str(pubkey):
            # We're the first recorded trade: we discount the amount to the current bonding curve
            new_msg["vSolInBondingCurve_Base"] = new_msg["vSolInBondingCurve"] - amount_traded
            
            # Volume bot case: small trades might not be relevant. Starting counter
            new_msg["is_relevant_trade"] = amount_traded >= appconfig.TRADING_CRITERIA_TRADE_RELEVANT_AMOUNT
            new_msg["is_non_relevant_trade_count"] = 0 if new_msg["is_relevant_trade"] else 1
        else:
            # The first recorded trade is not from us. So we can make an aproximation
            aprox = new_msg["tokenAmount"] * new_msg["vSolInBondingCurve"]
            # This is an aproximation of the Sols traded by the current trader
            aprox = aprox / new_msg["vTokensInBondingCurve"]
            # We discount the Sols traded by the current trader to the current Sols in Bonding Curve
            new_msg["vSolInBondingCurve_Base"] = new_msg["vSolInBondingCurve"] - aprox
            # Checking if this trade is relavant or not and starting counter for consecutives buys/sells
            new_msg["is_relevant_trade"] = aprox >= appconfig.TRADING_CRITERIA_TRADE_RELEVANT_AMOUNT
            new_msg["is_non_relevant_trade_count"] = 0 if new_msg["is_relevant_trade"] else 1

        new_msg["seconds_between_buys"] = 0
        new_msg["seconds_between_sells"] = 0
        new_msg["market_inactivity"] = 0
        new_msg["max_seconds_in_market"] = 0
        new_msg["max_consecutive_buys"] = [
            {
                "quantity": new_msg["consecutive_buys"],
                "sols": amount_traded if aprox == 0 else aprox
            }
        ]

    else:
        last_msg = previous_trades[-1]

        last_msg_timestamp = datetime.fromtimestamp(last_msg["timestamp"])
        first_trade_timestamp = datetime.fromtimestamp(previous_trades[0]["timestamp"])

        # Current solanas traded
        sols = new_msg["vSolInBondingCurve"] - last_msg["vSolInBondingCurve"]
        # Checking if this trade is relavant or not. Keeping counter for consecutives buys/sells
        new_msg["is_relevant_trade"] = sols >= appconfig.TRADING_CRITERIA_TRADE_RELEVANT_AMOUNT
        # We just count non relevant trades with consecutives buys/sells
        new_msg["is_non_relevant_trade_count"] = 0 if new_msg["is_relevant_trade"] else 1

        # We always keep track of the consecutive buys
        new_msg["max_consecutive_buys"] = last_msg["max_consecutive_buys"]

        if msg["txType"].lower() == TxType.buy.value:
            new_msg["consecutive_sells"] = 0
            new_msg["seconds_between_sells"] = 0

            if last_msg["txType"].lower() == TxType.buy.value:
                # Starting counter for non relevant trades with consecutives buys/sells
                if not new_msg["is_relevant_trade"] and not last_msg["is_relevant_trade"]:
                    new_msg["is_non_relevant_trade_count"] += last_msg["is_non_relevant_trade_count"]
                
                # Considering consecutives buys for relevan trades or for consecutives non relevant
                # trades that have reached the accepted tolerance
                tolerance = appconfig.TRADING_CRITERIA_CONSECUTIVES_NON_RELEVANT_TRADES_TOLERANCE
                if new_msg["is_relevant_trade"] or \
                    not new_msg["is_relevant_trade"] and new_msg["is_non_relevant_trade_count"] >= tolerance:
        
                    new_msg["is_non_relevant_trade_count"] = 0

                    new_msg["consecutive_buys"] = 1 + last_msg["consecutive_buys"]
                    new_msg["seconds_between_buys"] = (datetime.now() - last_msg_timestamp).total_seconds()
                    # Updating the last record
                    new_msg["max_consecutive_buys"][-1]["quantity"] = 1 + last_msg["consecutive_buys"]
                    new_msg["max_consecutive_buys"][-1]["sols"] += sols
                
            else:
                new_msg["consecutive_buys"] = 1
                new_msg["seconds_between_buys"] = 0
                # Start again with a new record
                new_msg["max_consecutive_buys"].append(
                    {
                        "quantity": 1,
                        "sols": sols
                    }
                )

        if msg["txType"].lower() == TxType.sell.value:
            new_msg["consecutive_buys"] = 0
            new_msg["seconds_between_buys"] = 0

            if last_msg["txType"].lower() == TxType.sell.value:
                # Starting counter for non relevant trades with consecutives buys/sells
                if not new_msg["is_relevant_trade"] and not last_msg["is_relevant_trade"]:
                    new_msg["is_non_relevant_trade_count"] += last_msg["is_non_relevant_trade_count"]

                # Considering consecutives buys for relevan trades or for consecutives non relevant
                # trades that have reached the accepted tolerance
                tolerance = appconfig.TRADING_CRITERIA_CONSECUTIVES_NON_RELEVANT_TRADES_TOLERANCE
                if new_msg["is_relevant_trade"] or \
                    not new_msg["is_relevant_trade"] and new_msg["is_non_relevant_trade_count"] >= tolerance:
        
                    new_msg["is_non_relevant_trade_count"] = 0

                    new_msg["consecutive_sells"] = 1 + last_msg["consecutive_sells"]
                    new_msg["seconds_between_sells"] = (datetime.now() - last_msg_timestamp).total_seconds()

            else:
                new_msg["consecutive_sells"] = 1
                new_msg["seconds_between_sells"] = 0

        new_msg["market_inactivity"] = (datetime.now() - last_msg_timestamp).total_seconds()
        new_msg["max_seconds_in_market"] = (datetime.now() - first_trade_timestamp).total_seconds()

        if msg["txType"].lower() == TxType.buy.value:
            new_msg["seconds_between_buys"] = (datetime.now() - last_msg_timestamp).total_seconds()

        # We'll keep track of the Solanas in Bounding courve since the first recorded trade
        new_msg["vSolInBondingCurve_Base"] = last_msg["vSolInBondingCurve_Base"]


    # Checking if the current trader is in the trader's list
    new_msg["trader_has_sold"] = new_msg["traderPublicKey"] in traders

    # Amount of Solana the token is holding after our buy
    new_msg["sols_in_token_after_buying"] = new_msg["vSolInBondingCurve"] - new_msg["vSolInBondingCurve_Base"]

    return new_msg


def max_consecutive_buys(buys: int, msg: dict) -> bool:
    """
    Checks if the maximum consecutive buys has been reached.
    
    Args:
        buys (int): The maximum number of consecutive buys allowed.
        msg (dict): The message dictionary containing context.

    Returns:
        bool: True if the condition is met, otherwise False.
    """
    return msg["consecutive_buys"] >= buys


def max_consecutive_sells(sells: int, msg: dict) -> bool:
    """
    Checks if the maximum consecutive sells condition is met.
    
    Args:
        sells (int): The maximum number of consecutive sells allowed.
        msg (dict): The message dictionary containing context.

    Returns:
        bool: True if the condition is met, otherwise False.
    """
    return msg["consecutive_sells"] >= sells


def max_seconds_between_buys(seconds: int, msg: dict) -> bool:
    """
    Checks if the maximum allowed seconds between buys has been reached.
    
    Args:
        seconds (int): The maximum number of seconds allowed between buys.
        msg (dict): The message dictionary containing context.

    Returns:
        bool: True if the condition is met, otherwise False.
    """
    return msg["seconds_between_buys"] >= seconds


def trader_has_sold(msg: dict) -> bool:
    """
    Checks if the trader or developer has sold their tokens.
    
    Args:
        sold (bool): A flag indicating whether the developer has sold tokens.
        msg (dict): The message dictionary containing context.

    Returns:
        bool: True if the condition is met, otherwise False.
    """
    return msg["trader_has_sold"]


def max_sols_in_token_after_buying_in_percentage(percentage: int, msg: dict) -> bool:
    """
    Checks if the maximum percentage of SOLs in the token after buying condition is met.
    
    Args:
        percentage (int): The maximum percentage of SOLs allowed in the token.
        msg (dict): The message dictionary containing context.

    Returns:
        bool: True if the condition is met, otherwise False.
    """
    pass


def market_inactivity(seconds: int, msg: dict) -> bool:
    """
    Checks if the market inactivity condition is met.
    
    Args:
        seconds (int): The maximum number of seconds of inactivity allowed.
        msg (dict): The message dictionary containing context.

    Returns:
        bool: True if the condition is met, otherwise False.
    """
    pass


def max_seconds_in_market(seconds: int, msg: dict) -> bool:
    """
    Checks if the maximum seconds in the market condition is met.
    
    Args:
        seconds (int): The maximum number of seconds allowed in the market.
        msg (dict): The message dictionary containing context.

    Returns:
        bool: True if the condition is met, otherwise False.
    """
    pass


def test():
    print("#######################")
    print(" TEST NON RELEVANT TRADES COUNT AND MODIFY MESSAGES IN THIS FUNCTION")
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
    from solders.keypair import Keypair
    from bot.config import appconfig
    keypair = Keypair.from_base58_string(appconfig.PRIVKEY)

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

    print(tokens[mint]["trades"])

#test()
