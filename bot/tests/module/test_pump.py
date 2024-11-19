from bot.module.pump import Pump
from bot.config import appconfig
from bot.tests.module.fixture_pump import *


def test_attribute_handling(
    get_account,
    get_token,
    get_token2,
    get_trader
):
    pump = Pump()

    pump.add_account(account=get_account)
    assert pump.accounts == [get_account]

    pump.remove_account(account=get_account)
    assert pump.accounts == []

    pump.add_token(token=get_token)
    assert pump.tokens == [get_token]

    pump.remove_token(token=get_token)
    assert pump.tokens == []

    pump.add_token(token=get_token2)
    pump.clear_tokens()
    assert pump.tokens == []

    pump.add_trader(trader=get_trader)
    assert pump.traders == [get_trader]

    pump.remove_trader(trader=get_trader)
    assert pump.traders == []

    