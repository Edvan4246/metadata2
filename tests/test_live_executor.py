from __future__ import annotations

import os
from unittest.mock import MagicMock

import ccxt
import pytest

from arbitrage_bot.live_executor import (
    LIVE_CONFIRM_ENV_VAR,
    LIVE_CONFIRM_VALUE,
    AuthenticatedExchangeClient,
    LiveCrossExchangeExecutor,
    LiveExecutionError,
    is_live_trading_enabled,
    load_credentials,
    load_env_file,
)


def _client_with_mock_exchange(exchange_id: str = "binance") -> AuthenticatedExchangeClient:
    client = AuthenticatedExchangeClient.__new__(AuthenticatedExchangeClient)
    client.exchange_id = exchange_id
    client.exchange = MagicMock()
    return client


@pytest.mark.parametrize(
    "config_enabled,cli_flag,env_value,expected",
    [
        (True, True, LIVE_CONFIRM_VALUE, True),
        (False, True, LIVE_CONFIRM_VALUE, False),
        (True, False, LIVE_CONFIRM_VALUE, False),
        (True, True, "nope", False),
        (True, True, None, False),
        (False, False, None, False),
    ],
)
def test_is_live_trading_enabled_requires_all_three_gates(
    monkeypatch, config_enabled, cli_flag, env_value, expected
):
    if env_value is None:
        monkeypatch.delenv(LIVE_CONFIRM_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(LIVE_CONFIRM_ENV_VAR, env_value)

    assert is_live_trading_enabled(config_enabled, cli_flag) is expected


def test_load_credentials_reads_from_env(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "key123")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret456")

    api_key, api_secret = load_credentials("binance")

    assert api_key == "key123"
    assert api_secret == "secret456"


def test_load_credentials_missing_raises(monkeypatch):
    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)

    with pytest.raises(LiveExecutionError):
        load_credentials("kraken")


@pytest.mark.parametrize(
    "exception",
    [
        ccxt.InsufficientFunds("no funds"),
        ccxt.InvalidOrder("bad order"),
        ccxt.NetworkError("timeout"),
        ccxt.ExchangeError("rejected"),
    ],
)
def test_create_market_order_maps_ccxt_exceptions(exception):
    client = _client_with_mock_exchange()
    client.exchange.create_order.side_effect = exception

    with pytest.raises(LiveExecutionError):
        client.create_market_order("BTC/USDT", "buy", 0.01)


def test_create_market_order_returns_order_on_success():
    client = _client_with_mock_exchange()
    client.exchange.create_order.return_value = {"id": "1", "status": "closed"}

    order = client.create_market_order("BTC/USDT", "buy", 0.01)

    assert order == {"id": "1", "status": "closed"}


def test_wait_for_fill_polls_until_no_longer_open(monkeypatch):
    client = _client_with_mock_exchange()
    client.exchange.fetch_order.side_effect = [
        {"id": "1", "status": "open"},
        {"id": "1", "status": "closed", "filled": 0.01},
    ]
    monkeypatch.setattr("time.sleep", lambda _: None)

    order = client.wait_for_fill("1", "BTC/USDT", timeout_seconds=5, poll_interval=0.01)

    assert order["status"] == "closed"
    assert client.exchange.fetch_order.call_count == 2


def test_live_cross_exchange_executor_full_fill():
    buy_client = _client_with_mock_exchange()
    buy_client.exchange.create_order.return_value = {"id": "buy1"}
    buy_client.exchange.fetch_order.return_value = {
        "id": "buy1",
        "status": "closed",
        "filled": 0.05,
        "cost": 1000.0,
    }

    sell_client = _client_with_mock_exchange()
    sell_client.exchange.create_order.return_value = {"id": "sell1"}
    sell_client.exchange.fetch_order.return_value = {
        "id": "sell1",
        "status": "closed",
        "filled": 0.05,
        "cost": 1010.0,
    }

    executor = LiveCrossExchangeExecutor({"binance": buy_client, "kraken": sell_client})
    result = executor.execute("binance", "kraken", "BTC/USDT", 0.05)

    assert result.base_amount_bought == 0.05
    assert result.quote_spent == 1000.0
    assert result.base_amount_sold == 0.05
    assert result.quote_received == 1010.0
    assert result.fully_hedged is True


def test_live_cross_exchange_executor_partial_sell_fill_not_hedged():
    buy_client = _client_with_mock_exchange()
    buy_client.exchange.create_order.return_value = {"id": "buy1"}
    buy_client.exchange.fetch_order.return_value = {
        "id": "buy1",
        "status": "closed",
        "filled": 0.05,
        "cost": 1000.0,
    }

    sell_client = _client_with_mock_exchange()
    sell_client.exchange.create_order.return_value = {"id": "sell1"}
    sell_client.exchange.fetch_order.return_value = {
        "id": "sell1",
        "status": "closed",
        "filled": 0.03,
        "cost": 606.0,
    }

    executor = LiveCrossExchangeExecutor({"binance": buy_client, "kraken": sell_client})
    result = executor.execute("binance", "kraken", "BTC/USDT", 0.05)

    assert result.base_amount_sold == 0.03
    assert result.fully_hedged is False


def test_live_cross_exchange_executor_zero_buy_fill_raises():
    buy_client = _client_with_mock_exchange()
    buy_client.exchange.create_order.return_value = {"id": "buy1"}
    buy_client.exchange.fetch_order.return_value = {
        "id": "buy1",
        "status": "canceled",
        "filled": 0.0,
        "cost": 0.0,
    }

    sell_client = _client_with_mock_exchange()

    executor = LiveCrossExchangeExecutor({"binance": buy_client, "kraken": sell_client})

    with pytest.raises(LiveExecutionError):
        executor.execute("binance", "kraken", "BTC/USDT", 0.05)

    sell_client.exchange.create_order.assert_not_called()


def test_assert_trade_only_permissions_raises_when_withdrawals_enabled():
    client = _client_with_mock_exchange("binance")
    client.exchange.sapiGetAccountApiRestrictions.return_value = {"enableWithdrawals": True}

    with pytest.raises(LiveExecutionError):
        client.assert_trade_only_permissions()


def test_assert_trade_only_permissions_passes_when_withdrawals_disabled():
    client = _client_with_mock_exchange("binance")
    client.exchange.sapiGetAccountApiRestrictions.return_value = {"enableWithdrawals": False}

    client.assert_trade_only_permissions()  # should not raise


def test_assert_trade_only_permissions_does_not_block_on_check_failure(caplog):
    client = _client_with_mock_exchange("binance")
    client.exchange.sapiGetAccountApiRestrictions.side_effect = ccxt.NetworkError("timeout")

    client.assert_trade_only_permissions()  # best-effort: warns, never raises on check failure


def test_assert_trade_only_permissions_warns_for_unsupported_exchange(caplog):
    client = _client_with_mock_exchange("kraken")

    client.assert_trade_only_permissions()  # best-effort: warns, never raises

    client.exchange.sapiGetAccountApiRestrictions.assert_not_called()


def test_load_env_file_does_not_override_existing_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_TEST_VAR", "from_process_env")
    env_file = tmp_path / ".env"
    env_file.write_text("SOME_TEST_VAR=from_dotenv_file\n")
    monkeypatch.chdir(tmp_path)

    load_env_file()

    assert os.environ["SOME_TEST_VAR"] == "from_process_env"
    monkeypatch.delenv("SOME_TEST_VAR", raising=False)
