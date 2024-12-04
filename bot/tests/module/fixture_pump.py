import pytest
from solders.keypair import Keypair


@pytest.fixture
def get_account():
    yield "Some_account"


@pytest.fixture
def get_token():
    yield {"mint": "Some_token_pump"}


@pytest.fixture
def get_token2():
    yield {"mint": "Some_token2_pump"}


@pytest.fixture
def get_trader():
    yield "Some_trader_address"


@pytest.fixture
def get_pubkey():
    yield "1ajMNhqWCeDVJtddbNhD1ss1N1CFZ11nV1Mg1StvBHdb"
