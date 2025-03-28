from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch, Mock
import pytest
from bot.config import appconfig
from bot.tests.libs.fixtures_criterias import *
from bot.libs.criterias import (
    exit_on_first_sale,
    trading_analytics,
    exit_on_first_sale,
    max_consecutive_buys,
    max_seconds_between_buys,
    trader_has_sold,
    validate_trade_timedelta_exceeded,
    seller_is_an_unknown_trader,
    max_sols_in_token_after_buying_in_percentage,
    buys_in_the_same_second,
    max_seconds_in_market
)


@pytest.mark.parametrize(
    "expected_result, msg, description", [
        (
            True,
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
            },
            "Sell test"
        ),
        (
            False,
            {
                "signature":"osUSpasfsvdPkGXZGoLa68X7b1PRSpgUimM8MUNtw9nwMW9em3L4UKzDUDTDuF7FMAw1XGNtNDtPRCBnE7jRdr5",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"5gaewKWutRmK5J7iAFLFeEz8aeuhLMGsYwmXnZw8ib9L",
                "txType":"buy",
                "tokenAmount":7732152.992471,
                "newTokenBalance":0,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":1072999999.998786,
                "vSolInBondingCurve":30.000000000033943,
                "marketCapSol":27.958993476298126
            },
            "Buy test"
        )
    ]
)
def test_exit_on_first_sale(expected_result, msg, description):
    assert exit_on_first_sale(msg=msg) == expected_result, description

@pytest.mark.parametrize(
    """
        description,
        msg,
        previous_trades,
        amount,
        traders,
        relevant_trade,
        is_non_relevant_trade_count,
        max_consecutive_buys_result
    """,
    [
        (
            "Sniper is the first to do a trade",
            {
                "signature":"XGAnLe4EKCx4NNHv7soDimYZifwRndEGq1myrMDZR6DSRa6FgvcsMbpEz7XJrvRHxH6GcwPTr1oKt9jNWj5T4Uh",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":30582206.734745,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":977513247.598136,
                "vSolInBondingCurve":32.000,
                "marketCapSol":33.000
            },
            [],
            0.5,
            [],
            True,
            0,
            False
        ),
        (
            "Sniper: first non relevant trade",
            {
                "signature":"XGAnLe4EKCx4NNHv7soDimYZifwRndEGq1myrMDZR6DSRa6FgvcsMbpEz7XJrvRHxH6GcwPTr1oKt9jNWj5T4Uh",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":30582206.734745,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":977513247.598136,
                "vSolInBondingCurve":32.000,
                "marketCapSol":32.001
            },
            [],
            0.001,
            [],
            False,
            1,
            False
        ), 
        (
            "Other trader: first relevant trade",
            {
                "signature":"XGAnLe4EKCx4NNHv7soDimYZifwRndEGq1myrMDZR6DSRa6FgvcsMbpEz7XJrvRHxH6GcwPTr1oKt9jNWj5T4Uh",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                "txType":"buy",
                "tokenAmount":10000000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.000,
                "marketCapSol":33.000
            },
            [],
            0.5,
            [],
            True,
            0,
            False
        ),
        (
            "Other trader: first NON relevant trade",
            {
                "signature":"xxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.000,
                "marketCapSol":32.001
            },
            [],
            0.5,
            [],
            False,
            1,
            False
        ),
        (
            "Second trade: relevant Buy",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":1,
                            "sols":1.6
                        }
                    ],
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            0.5,
            [],
            True,
            0,
            True
        )
    ]
)
def test_trading_analytics_buys(
    get_pubkey,
    get_max_consecutive_buys,
    msg,
    previous_trades,
    amount,
    traders,
    description,
    relevant_trade,
    is_non_relevant_trade_count,
    max_consecutive_buys_result
):
    new_msg = trading_analytics(
        msg=msg,
        previous_trades=previous_trades,
        amount_traded=amount,
        pubkey=get_pubkey,
        traders=traders,
        token_timestamps={}
    )
    if str(get_pubkey) == new_msg["traderPublicKey"]:
        assert new_msg["vSolInBondingCurve_Base"] == new_msg["vSolInBondingCurve"] - amount, description
    else:
        new_amount = round(float(new_msg["sols_in_token_after_buying"]), 4)
        assert new_msg["vSolInBondingCurve_Base"] == new_msg["vSolInBondingCurve"] - new_amount, description
    assert new_msg["is_relevant_trade"] == relevant_trade, description
    assert new_msg["is_non_relevant_trade_count"] == is_non_relevant_trade_count, description

    assert max_consecutive_buys(buys=get_max_consecutive_buys, msg=new_msg) == max_consecutive_buys_result

@pytest.mark.parametrize(
    """
        description,
        msg,
        previous_trades,
        amount,
        traders,
        max_seconds_between_buys_result,
    """,
    [
        (
            "Max Seconds between buys: not exceeded",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":(datetime.now() - timedelta(seconds=2)).timestamp(),
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":1,
                            "sols":1.6
                        }
                    ],
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            0.5,
            [],
            False
        ),
        (
            "Max Seconds between buys: exceeded",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":(datetime.now() - timedelta(seconds=100)).timestamp(),
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":1,
                            "sols":1.6
                        }
                    ],
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            0.5,
            [],
            True
        )
    ]
)
def test_max_seconds_between_buys(
    get_pubkey,
    get_max_seconds_between_buys,
    msg,
    previous_trades,
    amount,
    traders,
    description,
    max_seconds_between_buys_result
):
    new_msg = trading_analytics(
        msg=msg,
        previous_trades=previous_trades,
        amount_traded=amount,
        pubkey=get_pubkey,
        token_timestamps={},
        traders=traders
    )

    seconds_exceeded = max_seconds_between_buys(
            seconds=get_max_seconds_between_buys,
            msg=new_msg
        )
    assert seconds_exceeded == max_seconds_between_buys_result, description

@pytest.mark.parametrize(
    """
        description,
        msg,
        previous_trades,
        amount,
        traders,
        trader_has_sold_result,
    """,
    [
        (
            "Trader has sold: False",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":(datetime.now() - timedelta(seconds=2)).timestamp(),
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":1,
                            "sols":1.6
                        }
                    ],
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            0.5,
            [
                "4XXnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43xxX"
            ],
            False
        ),
        (
            "Trader has sold: True",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":(datetime.now() - timedelta(seconds=2)).timestamp(),
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":1,
                            "sols":1.6
                        }
                    ],
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            0.5,
            [
                "4XXnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43xxX",
                "4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC"
            ],
            True
        ),
    ]
)
def test_trader_has_sold(
    get_pubkey,
    description,
    msg,
    previous_trades,
    amount,
    traders,
    trader_has_sold_result
):
    new_msg = trading_analytics(
        msg=msg,
        previous_trades=previous_trades,
        amount_traded=amount,
        pubkey=get_pubkey,
        token_timestamps={},
        traders=traders
    )
    has_sold = trader_has_sold(expected=trader_has_sold_result, msg=new_msg)
    assert has_sold == trader_has_sold_result, description

@pytest.mark.parametrize(
    """
        description,
        msg,
        previous_trades,
        amount,
        traders,
    """,
    [
        (
            "Receiving our own trade: no relevant trades tolerance reached",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"4RBnqw6CB9ANn9e16WWamqZNBZDHXwuFVWSjosk43ptC",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":(datetime.now() - timedelta(seconds=2)).timestamp(),
                    "is_relevant_trade":False,
                    "consecutive_buys":2,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":2,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":2,
                            "sols":1.6
                        }
                    ],
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            0.5,
            [],
        ),
    ]
)
def test_detect_own_trade(
    get_pubkey,
    description,
    msg,
    previous_trades,
    amount,
    traders
):
    new_msg = trading_analytics(
        msg=msg,
        previous_trades=previous_trades.copy(),
        amount_traded=amount,
        pubkey=get_pubkey,
        traders=traders,
        token_timestamps={"buy_timestamp":(datetime.now() - timedelta(seconds=0)).timestamp()}
    )

    last_max_consecutive_buys = previous_trades[0]["max_consecutive_buys"][0]["quantity"]
    max_consecutive_buys = new_msg["max_consecutive_buys"][0]["quantity"]
    # Our trades wont affect the max consecutive buys count
    assert max_consecutive_buys == last_max_consecutive_buys, description

@pytest.mark.parametrize(
    """
        description,
        txType,
        msg,
        previous_trades,
        amount,
        traders,
        tdelta,
        expected_result
    """,
    [
        (
            "Buy: Receiving our own trade with delay",
            "buy",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [],
            0.5,
            [],
            1.0,
            True
        ),
        (
            "Buy: Receiving our own trade with NO delay",
            "buy",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [],
            0.5,
            [],
            0.9999,
            False
        ),
        (
            "Sell: Receiving our own trade with delay",
            "sell",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"sell",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [],
            0.5,
            [],
            1.01,
            True
        ),
        (
            "Sell: Receiving our own trade with NO delay",
            "sell",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"sell",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [],
            0.5,
            [],
            0.9999,
            False
        ),
        (
            "Create: Receiving our own trade with delay",
            "create",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"create",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [],
            0.5,
            [],
            1.5,
            True
        ),
        (
            "Create: Receiving our own trade with NO delay",
            "create",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"create",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [],
            0.5,
            [],
            0.4999,
            False
        ),
    ]
)
def test_trade_timedelta(
    get_pubkey,
    txType,
    description,
    msg,
    previous_trades,
    amount,
    traders,
    tdelta,
    expected_result
):
    tkey = "{}_timestamp".format(txType)
    new_msg = trading_analytics(
        msg=msg,
        previous_trades=previous_trades,
        amount_traded=amount,
        pubkey=get_pubkey,
        traders=traders,
        token_timestamps={tkey:(datetime.now() - timedelta(seconds=tdelta)).timestamp()}
    )
    assert validate_trade_timedelta_exceeded(expected=expected_result, msg=new_msg) == expected_result, description

@pytest.mark.parametrize(
    """
        description,
        txType,
        msg,
        previous_trades,
        amount,
        traders,
        expected_result
    """,
    [
        (
            "Sell: known seller who has traded at least one time after us. ",
            "sell",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"sell",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":1,
                            "sols":1.6
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            0.5,
            [],
            False
        ),
        (
            "Sell: unknown seller that might had buyed before we did. ",
            "sell",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"sell",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"4Xx7xxXxXX125XX3Xx2xxXxxxxXXxxxxXxXxXxxxpump",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":1,
                            "sols":1.6
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            0.5,
            [],
            True
        ),
        (
            "Buy: known buyer.",
            "sell",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4Xx7xxXxXX125XX3Xx2xxXxxxxXXxxxxXxXxXxxxpump",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"4Xx7xxXxXX125XX3Xx2xxXxxxxXXxxxxXxXxXxxxpump",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":1,
                            "sols":1.6
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            0.5,
            [],
            False
        ),
        (
            "Buy: unknown buyer.",
            "sell",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"4Xx7xxXxXX125XX3Xx2xxXxxxxXXxxxxXxXxXxxxpump",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":1,
                            "sols":1.6
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            0.5,
            [],
            False
        ),
    ]
)
def test_seller_is_an_unknown_trader(
    get_pubkey,
    txType,
    description,
    msg,
    previous_trades,
    amount,
    traders,
    expected_result
):
    tkey = "{}_timestamp".format(txType)
    new_msg = trading_analytics(
        msg=msg,
        previous_trades=previous_trades,
        amount_traded=amount,
        pubkey=get_pubkey,
        traders=traders,
        token_timestamps={tkey:(datetime.now() - timedelta(seconds=0)).timestamp()}
    )
    assert seller_is_an_unknown_trader(expected=expected_result, msg=new_msg) == expected_result, description

@pytest.mark.parametrize(
    """
        description,
        txType,
        msg,
        previous_trades,
        amount,
        percentage,
        expected_result
    """,
    [
        (
            "Buy: max Solanas in token after our buy have been reached ",
            "buy",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"1xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":2,
                            "sols":1.6
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            2.0,
            100,
            True
        ),
        (
            "Buy: 200% of amount traded compared with bought Solanas have NOT been reached ",
            "buy",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"1xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":2,
                            "sols":1.6
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            2.0,
            200,
            False
        ),
        (
            "Buy: 80% of amount traded compared with bouth Solanas have been reached ",
            "buy",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"1xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":1,
                            "sols":1.8
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {"20241212121212": 1}
                }
            ],
            1.0,
            80,
            True
        ),
    ]
)
def test_max_sols_in_token_after_buying(
    get_pubkey,
    description,
    txType,
    msg,
    previous_trades,
    amount,
    percentage,
    expected_result
):
    tkey = "{}_timestamp".format(txType)
    new_msg = trading_analytics(
        msg=msg,
        previous_trades=previous_trades,
        amount_traded=amount,
        pubkey=get_pubkey,
        traders=[],
        token_timestamps={tkey:(datetime.now() - timedelta(seconds=0)).timestamp()}
    )
    assert max_sols_in_token_after_buying_in_percentage(percentage=percentage, msg=new_msg, amount_traded=amount) == expected_result, description


@pytest.mark.parametrize(
    """
        description,
        txType,
        msg,
        previous_trades,
        expected_result
    """,
    [
        (
            "Buy: No artifical pump is found",
            "buy",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"1xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":2,
                            "sols":1.6
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {
                        (datetime.now() - timedelta(seconds=2)).strftime("%Y%m%d%H%M%S"): 2,
                        (datetime.now() - timedelta(seconds=1)).strftime("%Y%m%d%H%M%S"): 3,
                        (datetime.now() - timedelta(seconds=0)).strftime("%Y%m%d%H%M%S"): 1
                    }
                },
            ],
            False
        ),
        (
            "Buy: artifical pump was found!",
            "buy",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"1xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":2,
                            "sols":1.6
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {
                        (datetime.now() - timedelta(seconds=3)).strftime("%Y%m%d%H%M%S"): 4,
                        (datetime.now() - timedelta(seconds=2)).strftime("%Y%m%d%H%M%S"): 2,
                        (datetime.now() - timedelta(seconds=1)).strftime("%Y%m%d%H%M%S"): 3,
                        (datetime.now() - timedelta(seconds=0)).strftime("%Y%m%d%H%M%S"): 7
                    }
                },
            ],
            True
        ),

        (
            "Buy: artifical pump was found OUTSIDE expected seconds since token genesis",
            "buy",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"1xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":2,
                            "sols":1.6
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {
                        (datetime.now() - timedelta(seconds=13)).strftime("%Y%m%d%H%M%S"): 4,
                        (datetime.now() - timedelta(seconds=6)).strftime("%Y%m%d%H%M%S"): 2,
                        (datetime.now() - timedelta(seconds=3)).strftime("%Y%m%d%H%M%S"): 3,
                        (datetime.now() - timedelta(seconds=0)).strftime("%Y%m%d%H%M%S"): 7
                    }
                },
            ],
            False
        ),
    ]
)
def test_buys_in_the_same_second(
    description,
    txType,
    msg,
    previous_trades,
    expected_result,
    get_artifical_pump_validations
):
    tkey = "{}_timestamp".format(txType)
    new_msg = trading_analytics(
        msg=msg,
        previous_trades=previous_trades,
        amount_traded=0.1,
        pubkey=get_pubkey,
        traders=[],
        token_timestamps={tkey:(datetime.now() - timedelta(seconds=0)).timestamp()}
    )
    result = buys_in_the_same_second(
        validations=get_artifical_pump_validations,
        msg=new_msg
    )
    assert result == expected_result, description

@pytest.mark.parametrize(
    """
        description,
        txType,
        msg,
        previous_trades,
        expected_result
    """,
    [
        (
            "Buy: Still in market",
            "buy",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"1xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":2,
                            "sols":1.6
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {
                        (datetime.now() - timedelta(seconds=2)).strftime("%Y%m%d%H%M%S"): 2,
                        (datetime.now() - timedelta(seconds=1)).strftime("%Y%m%d%H%M%S"): 3,
                        (datetime.now() - timedelta(seconds=0)).strftime("%Y%m%d%H%M%S"): 1
                    }
                },
            ],
            False
        ),
        (
            "Buy: max seconds in market has beed reached!",
            "buy",
            {
                "signature":"xxxx",
                "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                "traderPublicKey":"4xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                "txType":"buy",
                "tokenAmount":10000.00,
                "newTokenBalance":30582206.734745,
                "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                "vTokensInBondingCurve":200000000.00,
                "vSolInBondingCurve":32.500,
                "marketCapSol":32.001
            },
            [
                {
                    "signature":"xxxx",
                    "mint":"4Wo7nxVsPV125DW3Tr2ppPrzrnNFwidiKjWyVsifpump",
                    "traderPublicKey":"1xxMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb",
                    "txType":"buy",
                    "tokenAmount":10000000.0,
                    "newTokenBalance":30582206.734745,
                    "bondingCurveKey":"HPWxfYdBitgdK4VcevMgE1VHaKgpcKJWiJh9dFAsP6SE",
                    "vTokensInBondingCurve":200000000.0,
                    "vSolInBondingCurve":32.0,
                    "marketCapSol":33.0,
                    "timestamp":1732963950.837367,
                    "is_relevant_trade":True,
                    "consecutive_buys":1,
                    "consecutive_sells":0,
                    "vSolInBondingCurve_Base":30.4,
                    "is_non_relevant_trade_count":0,
                    "seconds_between_buys":0,
                    "seconds_between_sells":0,
                    "market_inactivity":0,
                    "max_seconds_in_market":0,
                    "max_consecutive_buys":[
                        {
                            "quantity":2,
                            "sols":1.6
                        }
                    ],
                    "seller_is_an_unknown_trader": False,
                    "consecutive_buys_timestamps": {
                        (datetime.now() - timedelta(seconds=31)).strftime("%Y%m%d%H%M%S"): 4,
                        (datetime.now() - timedelta(seconds=2)).strftime("%Y%m%d%H%M%S"): 2,
                        (datetime.now() - timedelta(seconds=1)).strftime("%Y%m%d%H%M%S"): 3,
                        (datetime.now() - timedelta(seconds=0)).strftime("%Y%m%d%H%M%S"): 7
                    }
                },
            ],
            True
        ),
    ]
)
def test_max_seconds_in_market(
    description,
    txType,
    msg,
    previous_trades,
    expected_result,
    get_max_seconds_in_market
):
    tkey = "{}_timestamp".format(txType)
    new_msg = trading_analytics(
        msg=msg,
        previous_trades=previous_trades,
        amount_traded=0.1,
        pubkey=get_pubkey,
        traders=[],
        token_timestamps={tkey:(datetime.now() - timedelta(seconds=0)).timestamp()}
    )
    result = max_seconds_in_market(
        time_in_market=get_max_seconds_in_market,
        msg=new_msg
    )
    assert result == expected_result, description

