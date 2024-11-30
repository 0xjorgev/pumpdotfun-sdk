import pytest
from solders.pubkey import Pubkey


@pytest.fixture
def get_pubkey():
    yield Pubkey.from_string("4ajMNhqWCeDVJtddbNhD3ss5N6CFZ37nV9Mg7StvBHdb")


@pytest.fixture
def get_max_consecutive_buys():
    yield 2

@pytest.fixture
def get_max_seconds_between_buys():
    yield 3
