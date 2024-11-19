import pytest


@pytest.fixture
def get_account():
    yield "Some_account"


@pytest.fixture
def get_token():
    yield "Some_token_pump"


@pytest.fixture
def get_token2():
    yield "Some_token2_pump"


@pytest.fixture
def get_trader():
    yield "Some_trader_address"
