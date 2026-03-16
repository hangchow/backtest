from __future__ import annotations

import json
import logging
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import pandas as pd

from live_trading.broker import (
    DailyHistoryProvider,
    LocalDataDailyHistoryProvider,
    MockRealtimeQuoteClient,
    QuoteBrokerClient,
    TradeAccountClient,
)
from live_trading.config import RealtimeQuoteBrokerConfig, load_live_trading_config, load_quote_config, load_trade_accounts_config
from live_trading.engine import LiveTradingEngine
from live_trading.models import AccountSnapshot, QuoteUpdate
from live_trading.pool_strategies import build_pool_strategy


def build_daily_history(code: str, closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    if volumes is None:
        volumes = [1000.0] * len(closes)
    days = pd.date_range("2026-03-09", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "code": [code] * len(closes),
            "time_key": [day.strftime("%Y-%m-%d 16:00:00") for day in days],
            "open": closes,
            "close": closes,
            "high": closes,
            "low": closes,
            "volume": volumes,
        }
    )


def build_minute_bar(code: str, timestamp: str, close: float, volume: float = 100.0) -> dict[str, object]:
    return {
        "code": code,
        "time_key": pd.Timestamp(timestamp),
        "open": close,
        "close": close,
        "high": close,
        "low": close,
        "volume": volume,
    }


def build_quote_payload(
    realtime_host: str = "127.0.0.1",
    realtime_port: int = 11111,
    history_host: str = "127.0.0.1",
    history_port: int = 11111,
) -> dict[str, object]:
    return {
        "realtime_broker": {
            "type": "futu",
            "host": realtime_host,
            "port": realtime_port,
            "market": "US",
            "extended_time": False,
        },
        "history_broker": {
            "type": "futu",
            "host": history_host,
            "port": history_port,
            "market": "US",
        },
        "runtime": {
            "config_reload_interval_seconds": 5,
            "log_price_updates": False,
            "log_account_updates": False,
            "log_position_updates": False,
        },
        "stock_pool": {
            "codes": ["US.AAPL", "US.MSFT"],
            "strategy": {
                "name": "dual_momentum",
                "params": {
                    "lookback_days": 1,
                    "long_lookback_days": 2,
                    "long_lookback_weight": 0.0,
                    "top_n": 1,
                    "volume_window": 1,
                    "min_volume_ratio": 1.0,
                    "market_filter_window": 2,
                    "volatility_window": 2,
                    "target_annual_vol": 999.0,
                    "max_gross_exposure": 1.0,
                    "rebalance_band_pct": 0.0,
                },
            },
        },
    }


def build_trade_payload(accounts: list[dict[str, object]]) -> dict[str, object]:
    return {"trade_accounts": accounts}


def build_trade_account_payload(account_id: str, host: str, port: int = 21111, account_index: int = 0) -> dict[str, object]:
    return {
        "account_id": account_id,
        "broker": {
            "type": "futu",
            "host": host,
            "port": port,
            "market": "US",
            "trade_env": "SIMULATE",
            "account_index": account_index,
        },
    }

class FakeQuoteBroker(QuoteBrokerClient):
    instances: list["FakeQuoteBroker"] = []

    def __init__(self, config, event_sink, logger) -> None:
        self.config = config
        self.event_sink = event_sink
        self.logger = logger
        self.closed = False
        self.connect_calls = 0
        self.update_calls = 0
        self.connected_codes: list[tuple[str, ...]] = []
        FakeQuoteBroker.instances.append(self)

    def connect(self, codes):
        self.connect_calls += 1
        self.closed = False
        self.connected_codes.append(tuple(codes))

    def update_symbols(self, codes):
        self.update_calls += 1
        self.connected_codes.append(tuple(codes))

    def close(self) -> None:
        self.closed = True


class FakeHistoryProvider(DailyHistoryProvider):
    instances: list["FakeHistoryProvider"] = []

    def __init__(self, config, logger) -> None:
        self.config = config
        self.logger = logger
        self.closed = False
        self.fetch_calls: list[tuple[tuple[str, ...], dict[str, int]]] = []
        FakeHistoryProvider.instances.append(self)

    def fetch_daily_histories(self, codes, daily_warmup_bars):
        codes_tuple = tuple(codes)
        bars_copy = dict(daily_warmup_bars)
        self.fetch_calls.append((codes_tuple, bars_copy))
        return {
            code: build_daily_history(
                code,
                [100.0, 101.0, 102.0, 103.0] if code == "US.AAPL" else [100.0, 105.0, 110.0, 120.0],
                [1000.0, 1100.0, 1200.0, 1300.0] if code == "US.AAPL" else [1000.0, 1500.0, 1800.0, 2200.0],
            )
            for code in codes_tuple
        }

    def close(self) -> None:
        self.closed = True


class StaticHistoryProvider(DailyHistoryProvider):
    def __init__(self, payload: dict[str, pd.DataFrame]) -> None:
        self.payload = payload
        self.calls: list[tuple[tuple[str, ...], dict[str, int]]] = []
        self.closed = False

    def fetch_daily_histories(self, codes, daily_warmup_bars):
        codes_tuple = tuple(codes)
        self.calls.append((codes_tuple, dict(daily_warmup_bars)))
        return {code: self.payload[code] for code in codes_tuple}

    def close(self) -> None:
        self.closed = True


class FakeTradeAccountClient(TradeAccountClient):
    instances: list["FakeTradeAccountClient"] = []

    def __init__(self, config, event_sink, logger) -> None:
        self.config = config
        self.event_sink = event_sink
        self.logger = logger
        self.closed = False
        self.connect_calls = 0
        FakeTradeAccountClient.instances.append(self)

    def connect(self) -> None:
        self.connect_calls += 1
        self.closed = False

    def close(self) -> None:
        self.closed = True


class RecordingQuoteSink:
    def __init__(self) -> None:
        self.quotes: list[QuoteUpdate] = []
        self.bars: list[tuple[str, dict[str, object]]] = []
        self.messages: list[tuple[int, str]] = []

    def on_quote(self, update: QuoteUpdate) -> None:
        self.quotes.append(update)

    def on_bar(self, code: str, bar: pd.Series | dict[str, object]) -> None:
        self.bars.append((code, dict(bar)))

    def on_broker_message(self, level: int, message: str) -> None:
        self.messages.append((level, message))


class FakeHttpServer:
    def __init__(self) -> None:
        self.daemon_threads = False
        self.server_address = ("127.0.0.1", 19111)
        self.serve_forever_calls = 0
        self.shutdown_calls = 0
        self.server_close_calls = 0

    def serve_forever(self) -> None:
        self.serve_forever_calls += 1

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def server_close(self) -> None:
        self.server_close_calls += 1


class LiveTradingConfigTests(unittest.TestCase):
    def test_load_live_trading_config_supports_split_quote_and_trade_files(self) -> None:
        quote_payload = build_quote_payload(realtime_host="127.0.0.1", realtime_port=11111, history_host="127.0.0.2", history_port=22222)
        quote_payload["runtime"] = {"config_reload_interval_seconds": 3}
        trade_payload = build_trade_payload([build_trade_account_payload("sim_primary", "127.0.0.9")])

        config = load_live_trading_config_from_payloads(quote_payload, trade_payload)

        self.assertEqual(config.realtime_broker.type, "futu")
        self.assertEqual(config.realtime_broker.host, "127.0.0.1")
        self.assertEqual(config.realtime_broker.port, 11111)
        self.assertEqual(config.history_broker.type, "futu")
        self.assertEqual(config.history_broker.host, "127.0.0.2")
        self.assertEqual(config.history_broker.port, 22222)
        self.assertEqual(config.stock_pool.codes, ("US.AAPL", "US.MSFT"))
        self.assertEqual(config.stock_pool.strategy.name, "dual_momentum")
        self.assertEqual(config.runtime.config_reload_interval_seconds, 3.0)
        self.assertEqual(len(config.trade_accounts), 1)
        self.assertEqual(config.trade_accounts[0].account_id, "sim_primary")
        self.assertEqual(config.trade_accounts[0].broker.host, "127.0.0.9")

    def test_load_quote_config_supports_separate_realtime_and_history_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quote.json"
            path.write_text(
                json.dumps(build_quote_payload("127.0.0.1", 11111, "127.0.0.2", 22222)),
                encoding="utf-8",
            )

            config = load_quote_config(path)

        self.assertEqual(config.realtime_broker.type, "futu")
        self.assertEqual(config.realtime_broker.host, "127.0.0.1")
        self.assertEqual(config.realtime_broker.port, 11111)
        self.assertEqual(config.history_broker.type, "futu")
        self.assertEqual(config.history_broker.host, "127.0.0.2")
        self.assertEqual(config.history_broker.port, 22222)

    def test_load_quote_config_supports_legacy_shared_quote_broker_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quote.json"
            path.write_text(
                json.dumps(
                    {
                        "quote_broker": {
                            "type": "futu",
                            "host": "127.0.0.1",
                            "port": 11111,
                            "market": "US",
                            "extended_time": True,
                        },
                        "stock_pool": {
                            "codes": ["US.AAPL", "US.MSFT"],
                            "strategy": {"name": "dual_momentum"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = load_quote_config(path)

        self.assertEqual(config.realtime_broker.type, "futu")
        self.assertEqual(config.realtime_broker.host, "127.0.0.1")
        self.assertEqual(config.realtime_broker.port, 11111)
        self.assertTrue(config.realtime_broker.extended_time)
        self.assertEqual(config.history_broker.type, "futu")
        self.assertEqual(config.history_broker.host, "127.0.0.1")
        self.assertEqual(config.history_broker.port, 11111)

    def test_load_quote_config_supports_mock_realtime_broker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quote.json"
            payload = build_quote_payload()
            payload["realtime_broker"] = {
                "type": "mock",
                "host": "127.0.0.1",
                "port": 19111,
                "market": "US",
                "extended_time": False,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            config = load_quote_config(path)

        self.assertEqual(config.realtime_broker.type, "mock")
        self.assertEqual(config.realtime_broker.host, "127.0.0.1")
        self.assertEqual(config.realtime_broker.port, 19111)
        self.assertEqual(config.history_broker.type, "futu")

    def test_load_quote_config_rejects_unsupported_quote_broker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quote.json"
            path.write_text(
                json.dumps(
                    {
                        "realtime_broker": {"type": "polygon", "host": "127.0.0.1", "port": 11111},
                        "history_broker": {"type": "futu", "host": "127.0.0.1", "port": 11111},
                        "stock_pool": {
                            "codes": ["US.AAPL", "US.MSFT"],
                            "strategy": {"name": "dual_momentum"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_quote_config(path)

    def test_load_trade_accounts_config_supports_multiple_accounts(self) -> None:
        payload = build_trade_payload(
            [
                build_trade_account_payload("sim_primary", "127.0.0.9"),
                build_trade_account_payload("sim_secondary", "127.0.0.10", port=31111, account_index=1),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trade.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            config = load_trade_accounts_config(path)

        self.assertEqual([account.account_id for account in config.accounts], ["sim_primary", "sim_secondary"])
        self.assertEqual(config.accounts[1].broker.host, "127.0.0.10")
        self.assertEqual(config.accounts[1].broker.port, 31111)
        self.assertEqual(config.accounts[1].broker.account_index, 1)


class MockRealtimeQuoteClientTests(unittest.TestCase):
    def test_mock_quote_client_translates_runtime_push_payload(self) -> None:
        sink = RecordingQuoteSink()
        fake_server = FakeHttpServer()
        client = MockRealtimeQuoteClient(
            RealtimeQuoteBrokerConfig(
                type="mock",
                host="127.0.0.1",
                port=19111,
                market="US",
                extended_time=False,
            ),
            sink,
            logging.getLogger("test.mock_quote"),
        )
        with patch.object(client, "_build_server", return_value=fake_server):
            client.connect(["US.AAPL"])
            payload = client.push_bars(
                {
                    "code": "US.AAPL",
                    "time_key": "2026-03-13 09:30:00",
                    "close": 104.5,
                    "volume": 321,
                }
            )
            client.close()

        self.assertEqual(payload["accepted"], 1)
        self.assertEqual(payload["ignored"], 0)
        self.assertEqual(len(sink.quotes), 1)
        self.assertEqual(sink.quotes[0].code, "US.AAPL")
        self.assertEqual(sink.quotes[0].last_price, 104.5)
        self.assertEqual(sink.quotes[0].source, "mock")


class LocalDataDailyHistoryProviderTests(unittest.TestCase):
    def test_provider_prefers_kline_day_then_uses_kline_minute_then_remote_and_caches(self) -> None:
        remote_calls: list[tuple[str, int]] = []

        def remote_fetcher(code: str, bars: int, page_size: int, max_pages: int) -> pd.DataFrame:
            remote_calls.append((code, bars))
            return pd.DataFrame(
                {
                    "code": [code, code],
                    "time_key": pd.to_datetime(["2026-03-10 09:30:00", "2026-03-10 16:00:00"]),
                    "open": [30.0, 31.0],
                    "close": [31.0, 32.0],
                    "high": [31.0, 33.0],
                    "low": [29.0, 30.0],
                    "volume": [500.0, 700.0],
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            daily_dir_aapl = Path(tmp) / "kline_day" / "US.AAPL"
            daily_dir_aapl.mkdir(parents=True)
            (daily_dir_aapl / "US.AAPL_2026-03-10.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-10 00:00:00,10,11,12,9,300\n",
                encoding="utf-8",
            )

            minute_dir_msft = Path(tmp) / "kline_minute" / "US.MSFT"
            minute_dir_msft.mkdir(parents=True)
            (minute_dir_msft / "US.MSFT_2026-03-09.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-09 09:30:00,20,22,23,19,100\n"
                "2026-03-09 16:00:00,22,21,24,20,200\n",
                encoding="utf-8",
            )

            cfg = load_live_trading_config_from_payloads(build_quote_payload(), build_trade_payload([build_trade_account_payload("a", "127.0.0.1")])).history_broker
            provider = LocalDataDailyHistoryProvider(
                cfg,
                logging.getLogger("test.local_history"),
                kline_minute_root=Path(tmp) / "kline_minute",
                kline_day_root=Path(tmp) / "kline_day",
                remote_minute_fetcher=remote_fetcher,
            )
            histories = provider.fetch_daily_histories(["US.AAPL", "US.MSFT", "US.NVDA"], {"US.AAPL": 10, "US.MSFT": 10, "US.NVDA": 10})
            provider.close()

            cached_daily_nvda = sorted((Path(tmp) / "kline_day" / "US.NVDA").glob("*.csv"))
            cached_minute_nvda = sorted((Path(tmp) / "kline_minute" / "US.NVDA").glob("*.csv"))

        self.assertEqual(remote_calls, [("US.MSFT", 3900), ("US.NVDA", 3900)])
        self.assertIn("US.AAPL", histories)
        self.assertIn("US.MSFT", histories)
        self.assertIn("US.NVDA", histories)
        self.assertEqual(list(histories["US.AAPL"]["close"]), [11.0])
        self.assertEqual(list(histories["US.MSFT"]["close"]), [21.0, 32.0])
        self.assertEqual(list(histories["US.NVDA"]["close"]), [32.0])
        self.assertTrue(cached_daily_nvda)
        self.assertTrue(cached_minute_nvda)

    def test_provider_logs_error_and_deduplicates_local_minute_time_key(self) -> None:
        cfg = load_live_trading_config_from_payloads(build_quote_payload(), build_trade_payload([build_trade_account_payload("a", "127.0.0.1")])).history_broker
        with tempfile.TemporaryDirectory() as tmp:
            minute_dir = Path(tmp) / "kline_minute" / "US.AAPL"
            minute_dir.mkdir(parents=True)
            rows = ["time_key,open,close,high,low,volume"]
            for i in range(10):
                day = 10 + i
                rows.append(f"2026-03-{day:02d} 09:30:00,10,11,12,9,100")
            rows.append("2026-03-10 09:30:00,10,15,16,9,200")
            (minute_dir / "US.AAPL_2026-03-10.csv").write_text(
                "\n".join(rows) + "\n",
                encoding="utf-8",
            )
            provider = LocalDataDailyHistoryProvider(
                cfg,
                logging.getLogger("test.local_history"),
                kline_minute_root=Path(tmp) / "kline_minute",
                kline_day_root=Path(tmp) / "kline_day",
            )

            with self.assertLogs("test.local_history", level="ERROR") as logs:
                histories = provider.fetch_daily_histories(["US.AAPL"], {"US.AAPL": 1})

        self.assertTrue(any("duplicate minute time_key" in msg for msg in logs.output))
        self.assertIn(15.0, list(histories["US.AAPL"]["close"]))

    def test_weekly_cache_uses_natural_monday_start_and_creates_empty_gap_week(self) -> None:
        cfg = load_live_trading_config_from_payloads(build_quote_payload(), build_trade_payload([build_trade_account_payload("a", "127.0.0.1")])).history_broker

        def remote_fetcher(code: str, bars: int, page_size: int, max_pages: int) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "code": [code, code],
                    "time_key": pd.to_datetime(["2026-03-02 09:30:00", "2026-03-16 09:30:00"]),
                    "open": [10.0, 20.0],
                    "close": [11.0, 21.0],
                    "high": [12.0, 22.0],
                    "low": [9.0, 19.0],
                    "volume": [100.0, 200.0],
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            provider = LocalDataDailyHistoryProvider(
                cfg,
                logging.getLogger("test.local_history"),
                kline_minute_root=Path(tmp) / "kline_minute",
                kline_day_root=Path(tmp) / "kline_day",
                remote_minute_fetcher=remote_fetcher,
            )
            provider.fetch_daily_histories(["US.NVDA"], {"US.NVDA": 10})

            daily_dir = Path(tmp) / "kline_day" / "US.NVDA"
            created = sorted(path.name for path in daily_dir.glob("*.csv"))
            gap_file = daily_dir / "US.NVDA_2026-03-09.csv"
            gap_rows = pd.read_csv(gap_file).shape[0]

        self.assertEqual(created, ["US.NVDA_2026-03-02.csv", "US.NVDA_2026-03-09.csv", "US.NVDA_2026-03-16.csv"])
        self.assertEqual(gap_rows, 0)


class DualMomentumPoolStrategyTests(unittest.TestCase):
    def test_dual_momentum_builds_target_for_stronger_symbol(self) -> None:
        quote_payload = build_quote_payload()
        trade_payload = build_trade_payload([build_trade_account_payload("sim_primary", "127.0.0.9")])
        config = load_live_trading_config_from_payloads(quote_payload, trade_payload)
        strategy = build_pool_strategy(config.stock_pool)
        strategy.bootstrap(
            {
                "US.AAPL": build_daily_history("US.AAPL", [100.0, 101.0, 102.0, 103.0]),
                "US.MSFT": build_daily_history("US.MSFT", [100.0, 105.0, 110.0, 120.0]),
            }
        )

        decision = strategy.on_bar("US.AAPL", build_minute_bar("US.AAPL", "2026-03-13 09:30:00", 104.0))

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertIn("US.MSFT", decision.target_weights)
        self.assertGreater(decision.target_weights["US.MSFT"], 0.0)
        self.assertNotIn("US.AAPL", decision.target_weights)

    def test_dual_momentum_emits_only_one_rebalance_per_new_trade_date(self) -> None:
        quote_payload = build_quote_payload()
        trade_payload = build_trade_payload([build_trade_account_payload("sim_primary", "127.0.0.9")])
        config = load_live_trading_config_from_payloads(quote_payload, trade_payload)
        strategy = build_pool_strategy(config.stock_pool)
        strategy.bootstrap(
            {
                "US.AAPL": build_daily_history("US.AAPL", [100.0, 101.0, 102.0, 103.0]),
                "US.MSFT": build_daily_history("US.MSFT", [100.0, 105.0, 110.0, 120.0]),
            }
        )

        first = strategy.on_bar("US.AAPL", build_minute_bar("US.AAPL", "2026-03-13 09:30:00", 104.0))
        second = strategy.on_bar("US.MSFT", build_minute_bar("US.MSFT", "2026-03-13 09:30:00", 121.0))

        self.assertIsNotNone(first)
        self.assertIsNone(second)


class LiveTradingEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeQuoteBroker.instances.clear()
        FakeHistoryProvider.instances.clear()
        FakeTradeAccountClient.instances.clear()

    def test_engine_reconnects_when_realtime_quote_endpoint_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quote_path = Path(tmp) / "quote.json"
            trade_path = Path(tmp) / "trade.json"
            quote_path.write_text(json.dumps(build_quote_payload()), encoding="utf-8")
            trade_path.write_text(
                json.dumps(build_trade_payload([build_trade_account_payload("sim_primary", "127.0.0.9")])),
                encoding="utf-8",
            )
            config_a = load_live_trading_config(quote_path, trade_path)

            engine = LiveTradingEngine(
                quote_path,
                trade_path,
                quote_broker_factory=FakeQuoteBroker,
                history_provider_factory=FakeHistoryProvider,
                trade_account_factory=FakeTradeAccountClient,
            )
            engine.apply_config(config_a)

            quote_payload_b = build_quote_payload(realtime_host="127.0.0.2")
            quote_path.write_text(json.dumps(quote_payload_b), encoding="utf-8")
            config_b = load_live_trading_config(quote_path, trade_path)
            engine.apply_config(config_b)
            engine.stop()

        self.assertEqual(len(FakeQuoteBroker.instances), 2)
        self.assertTrue(FakeQuoteBroker.instances[0].closed)
        self.assertEqual(FakeQuoteBroker.instances[0].connect_calls, 1)
        self.assertEqual(FakeQuoteBroker.instances[1].connect_calls, 1)
        self.assertEqual(len(FakeHistoryProvider.instances), 1)
        self.assertEqual(len(FakeTradeAccountClient.instances), 1)
        self.assertEqual(FakeTradeAccountClient.instances[0].connect_calls, 1)

    def test_engine_refreshes_history_without_reconnecting_realtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quote_path = Path(tmp) / "quote.json"
            trade_path = Path(tmp) / "trade.json"
            quote_path.write_text(json.dumps(build_quote_payload()), encoding="utf-8")
            trade_path.write_text(
                json.dumps(build_trade_payload([build_trade_account_payload("sim_primary", "127.0.0.9")])),
                encoding="utf-8",
            )
            config_a = load_live_trading_config(quote_path, trade_path)

            engine = LiveTradingEngine(
                quote_path,
                trade_path,
                quote_broker_factory=FakeQuoteBroker,
                history_provider_factory=FakeHistoryProvider,
                trade_account_factory=FakeTradeAccountClient,
            )
            engine.apply_config(config_a)

            quote_payload_b = build_quote_payload(history_host="127.0.0.3", history_port=33333)
            quote_path.write_text(json.dumps(quote_payload_b), encoding="utf-8")
            config_b = load_live_trading_config(quote_path, trade_path)
            engine.apply_config(config_b)
            engine.stop()

        self.assertEqual(len(FakeQuoteBroker.instances), 1)
        self.assertEqual(FakeQuoteBroker.instances[0].connect_calls, 1)
        self.assertEqual(FakeQuoteBroker.instances[0].update_calls, 0)
        self.assertEqual(len(FakeHistoryProvider.instances), 2)
        self.assertTrue(FakeHistoryProvider.instances[0].closed)
        self.assertEqual(len(FakeHistoryProvider.instances[0].fetch_calls), 1)
        self.assertEqual(len(FakeHistoryProvider.instances[1].fetch_calls), 1)

    def test_engine_reconnects_when_trade_account_endpoint_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quote_path = Path(tmp) / "quote.json"
            trade_path = Path(tmp) / "trade.json"
            quote_path.write_text(json.dumps(build_quote_payload()), encoding="utf-8")
            trade_path.write_text(
                json.dumps(build_trade_payload([build_trade_account_payload("sim_primary", "127.0.0.9")])),
                encoding="utf-8",
            )
            config_a = load_live_trading_config(quote_path, trade_path)

            engine = LiveTradingEngine(
                quote_path,
                trade_path,
                quote_broker_factory=FakeQuoteBroker,
                history_provider_factory=FakeHistoryProvider,
                trade_account_factory=FakeTradeAccountClient,
            )
            engine.apply_config(config_a)

            trade_path.write_text(
                json.dumps(build_trade_payload([build_trade_account_payload("sim_primary", "127.0.0.10")])),
                encoding="utf-8",
            )
            config_b = load_live_trading_config(quote_path, trade_path)
            engine.apply_config(config_b)
            engine.stop()

        self.assertEqual(len(FakeQuoteBroker.instances), 1)
        self.assertEqual(FakeQuoteBroker.instances[0].connect_calls, 1)
        self.assertEqual(len(FakeHistoryProvider.instances), 1)
        self.assertEqual(len(FakeTradeAccountClient.instances), 2)
        self.assertTrue(FakeTradeAccountClient.instances[0].closed)
        self.assertEqual(FakeTradeAccountClient.instances[0].connect_calls, 1)
        self.assertEqual(FakeTradeAccountClient.instances[1].connect_calls, 1)

    def test_engine_updates_shadow_position_after_rebalance_signal_for_multiple_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quote_path = Path(tmp) / "quote.json"
            trade_path = Path(tmp) / "trade.json"
            quote_path.write_text(json.dumps(build_quote_payload()), encoding="utf-8")
            trade_path.write_text(
                json.dumps(
                    build_trade_payload(
                        [
                            build_trade_account_payload("sim_primary", "127.0.0.9"),
                            build_trade_account_payload("sim_secondary", "127.0.0.10", account_index=1),
                        ]
                    )
                ),
                encoding="utf-8",
            )
            config = load_live_trading_config(quote_path, trade_path)

            engine = LiveTradingEngine(
                quote_path,
                trade_path,
                quote_broker_factory=FakeQuoteBroker,
                history_provider_factory=FakeHistoryProvider,
                trade_account_factory=FakeTradeAccountClient,
            )
            engine.apply_config(config)
            engine.on_account(
                "sim_primary",
                AccountSnapshot(
                    timestamp=pd.Timestamp("2026-03-13 09:30:00"),
                    total_assets=10000.0,
                    cash=10000.0,
                    available_funds=10000.0,
                    buying_power=10000.0,
                    currency="USD",
                ),
            )
            engine.on_positions("sim_primary", {})
            engine.on_account(
                "sim_secondary",
                AccountSnapshot(
                    timestamp=pd.Timestamp("2026-03-13 09:30:00"),
                    total_assets=20000.0,
                    cash=20000.0,
                    available_funds=20000.0,
                    buying_power=20000.0,
                    currency="USD",
                ),
            )
            engine.on_positions("sim_secondary", {})
            engine.on_quote(
                QuoteUpdate(
                    code="US.AAPL",
                    timestamp=pd.Timestamp("2026-03-13 09:29:00"),
                    last_price=104.0,
                )
            )
            engine.on_quote(
                QuoteUpdate(
                    code="US.MSFT",
                    timestamp=pd.Timestamp("2026-03-13 09:29:00"),
                    last_price=121.0,
                )
            )
            engine.on_bar("US.AAPL", build_minute_bar("US.AAPL", "2026-03-13 09:30:00", 104.0))
            engine.stop()

        state_primary = engine._account_states["sim_primary"]
        state_secondary = engine._account_states["sim_secondary"]
        self.assertEqual(state_primary.shadow_positions["US.AAPL"], 0)
        self.assertGreater(state_primary.shadow_positions["US.MSFT"], 0)
        self.assertLess(state_primary.shadow_cash or 0.0, 10000.0)
        self.assertEqual(state_secondary.shadow_positions["US.AAPL"], 0)
        self.assertGreater(state_secondary.shadow_positions["US.MSFT"], 0)
        self.assertLess(state_secondary.shadow_cash or 0.0, 20000.0)


def load_live_trading_config_from_payloads(quote_payload: dict, trade_payload: dict) -> object:
    with tempfile.TemporaryDirectory() as tmp:
        quote_path = Path(tmp) / "quote.json"
        trade_path = Path(tmp) / "trade.json"
        quote_path.write_text(json.dumps(quote_payload), encoding="utf-8")
        trade_path.write_text(json.dumps(trade_payload), encoding="utf-8")
        return load_live_trading_config(quote_path, trade_path)


if __name__ == "__main__":
    unittest.main()
