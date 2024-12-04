from bot.module.pump import Pump, TxType
from bot.config import appconfig
from bot.libs.utils import Trader, get_solana_balance
from bot.tests.module.fixture_pump import *

from datetime import datetime
from typing import Any
from unittest.mock import patch, Mock
from solders.message import Message


@patch.object(Pump, "get_balance")
def test_attribute_handling(
    get_balance_mocked,
    get_account,
    get_token,
    get_token2,
    get_trader
):
    get_balance_mocked.return_value = 5.00
    
    pump = Pump(executor_name="test", trader_type=Trader.sniper)

    pump.add_account(account=get_account)
    assert pump.accounts == [get_account]

    pump.remove_account(account=get_account)
    assert pump.accounts == []

    pump.add_update_token(token=get_token)
    assert get_token == pump.tokens[get_token["mint"]]

    pump.remove_token(token=get_token)
    assert pump.tokens == {}

    pump.add_update_token(token=get_token2)
    pump.clear_tokens()
    assert pump.tokens == {}

    pump.add_trader(trader=get_trader)
    assert pump.traders == [get_trader]

    pump.remove_trader(trader=get_trader)
    assert pump.traders == []


@pytest.mark.parametrize(
    "txtype, token, amount, expected_value, retries, status_code, content, description", [
        (
            TxType.buy,
            "49fRbSzsHhtjH6ZF4KQDCcmcFdSbU11uHGeVMWbSpump",
            1.0,
            None,
            1,
            404,
            "fake content",
            "PUMPFUN_TRANSACTION_URL returns a 404 status code error"
        ),
        (
            TxType.buy,
            "49fRbSzsHhtjH6ZF4KQDCcmcFdSbU11uHGeVMWbSpump",
            1.0,
            None,
            1,
            200,
            "fake content",
            "RPC_URL returns a 500 status code error"
        )
    ]
)
@patch.object(Keypair, "pubkey")
@patch("requests.post")
@patch("solders.transaction.VersionedTransaction.from_bytes")
@patch("solders.transaction.VersionedTransaction.message")
@patch.object(Pump, "get_balance")
def test_trade(
    pubkey_mocked,
    post_mocked,
    from_bytes_mocked,
    message_mocked,
    get_balance_mocked,
    txtype,
    token,
    amount,
    expected_value,
    retries,
    status_code,
    content,
    description,
    get_pubkey
):
    pubkey_mocked.return_value = Mock(get_pubkey)
    
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.content = content
    post_mocked.return_value = mock_response

    appconfig.TRADING_RETRIES = retries

    from_bytes_mocked.return_value = Mock(message=Mock())
    message_mocked.return_value = Mock()

    get_balance_mocked.return_value = 5.00
    
    pump = Pump(executor_name="test", trader_type=Trader.sniper)
    txn = pump.trade(txtype=txtype, token=token, keypair=pubkey_mocked, amount=amount)
    assert txn == expected_value, description
    post_mocked.assert_called_once

@pytest.mark.parametrize(
    "description, trade_action, mint_address", [
        (
            "Timestamp a buy", TxType.buy, "mint_key_address"
        ),
        (
            "Timestamp a sell", TxType.sell, "mint_key_address"
        )
    ]
)
def test_log_trade_token_timestamp(description, trade_action, mint_address):
    pump = Pump(executor_name="test", trader_type=Trader.sniper)
    token = {"mint": mint_address}
    pump.add_update_token(token=token)
    trade_timestamp = datetime.now().timestamp()
    pump.log_trade_token_timestamp(mint=mint_address, txtype=trade_action, trade_timestamp=trade_timestamp)
    key = "{}_timestamp".format(trade_action.value)
    assert key in pump.tokens[mint_address], description
    assert pump.tokens[mint_address][key] == trade_timestamp


def test_fees():
    pump = Pump(executor_name="test", trader_type=Trader.sniper)
    assert pump.trade_fees == appconfig.FEES

    pump.increase_fees()
    assert pump.trade_fees >= appconfig.FEES

    pump.decrease_fees()
    assert pump.trade_fees == appconfig.FEES

    pump.decrease_fees()
    pump.decrease_fees()
    pump.decrease_fees()
    assert pump.trade_fees == appconfig.FEES