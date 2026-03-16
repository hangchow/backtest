from __future__ import annotations

from datetime import datetime
import json
import logging
import threading
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from live_trading.broker import (
    DailyHistoryProvider,
    FutuDailyHistoryProvider,
    LocalDataDailyHistoryProvider,
    MockRealtimeQuoteClient,
    PolygonCacheDailyHistoryProvider,
    QuoteBrokerClient,
    TradeAccountClient,
    create_daily_history_provider,
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
    history_type: str = "futu",
) -> dict[str, object]:
    history_broker: dict[str, object] = {
        "type": history_type,
        "market": "US",
    }
    if history_type == "futu":
        history_broker["host"] = history_host
        history_broker["port"] = history_port
    return {
        "realtime_broker": {
            "type": "futu",
            "host": realtime_host,
            "port": realtime_port,
            "market": "US",
            "extended_time": False,
        },
        "history_broker": history_broker,
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

    def test_load_quote_config_supports_polygon_history_broker_without_host_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quote.json"
            path.write_text(
                json.dumps(build_quote_payload(history_type="polygon")),
                encoding="utf-8",
            )

            config = load_quote_config(path)

        self.assertEqual(config.history_broker.type, "polygon")
        self.assertIsNone(config.history_broker.host)
        self.assertIsNone(config.history_broker.port)

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
    def test_aggregate_minute_to_daily_uses_1600_open_as_us_daily_close(self) -> None:
        cfg = load_live_trading_config_from_payloads(
            build_quote_payload(),
            build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
        ).history_broker
        provider = LocalDataDailyHistoryProvider(cfg, logging.getLogger("test.local_history"))
        minute = pd.DataFrame(
            {
                "code": ["US.MSFT"] * 4,
                "time_key": pd.to_datetime(
                    [
                        "2025-10-29 09:30:00",
                        "2025-10-29 15:59:00",
                        "2025-10-29 16:00:00",
                        "2025-10-29 16:01:00",
                    ]
                ),
                "open": [544.94, 541.14, 541.55, 543.26],
                "close": [544.14, 542.56, 543.75, 543.99],
                "high": [546.27, 543.15, 543.75, 544.00],
                "low": [543.04, 541.08, 541.3604, 542.39],
                "volume": [811744.0, 493651.0, 352401.0, 20304.0],
            }
        )

        daily = provider._aggregate_minute_to_daily("US.MSFT", minute)

        self.assertEqual(len(daily), 1)
        self.assertEqual(float(daily.iloc[0]["close"]), 541.55)
        self.assertEqual(float(daily.iloc[0]["volume"]), 1678100.0)

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
                now_provider=lambda: datetime(2026, 3, 10, 17, 0, tzinfo=ZoneInfo("America/New_York")),
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
        self.assertEqual(list(histories["US.MSFT"]["close"]), [22.0, 31.0])
        self.assertEqual(list(histories["US.NVDA"]["close"]), [31.0])
        self.assertTrue(cached_daily_nvda)
        self.assertEqual([path.name for path in cached_minute_nvda], ["US.NVDA_2026-03-10.csv"])

    def test_provider_backfills_stale_daily_week_and_missing_remote_minute_day(self) -> None:
        remote_calls: list[tuple[str, int]] = []

        def remote_fetcher(code: str, bars: int, page_size: int, max_pages: int) -> pd.DataFrame:
            remote_calls.append((code, bars))
            return pd.DataFrame(
                {
                    "code": [code, code],
                    "time_key": pd.to_datetime(["2026-03-13 09:30:00", "2026-03-13 15:59:00"]),
                    "open": [130.0, 131.0],
                    "close": [131.0, 132.0],
                    "high": [131.0, 133.0],
                    "low": [129.0, 130.0],
                    "volume": [500.0, 700.0],
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            daily_dir = Path(tmp) / "kline_day" / "US.AMZN"
            minute_dir = Path(tmp) / "kline_minute" / "US.AMZN"
            daily_dir.mkdir(parents=True)
            minute_dir.mkdir(parents=True)
            (daily_dir / "US.AMZN_2026-03-02.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-02 00:00:00,100,101,102,99,1000\n"
                "2026-03-03 00:00:00,101,102,103,100,1001\n"
                "2026-03-04 00:00:00,102,103,104,101,1002\n"
                "2026-03-05 00:00:00,103,104,105,102,1003\n"
                "2026-03-06 00:00:00,104,105,106,103,1004\n",
                encoding="utf-8",
            )
            for index, trade_date in enumerate(["2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12"], start=1):
                (minute_dir / f"US.AMZN_{trade_date}.csv").write_text(
                    "time_key,open,close,high,low,volume\n"
                    f"{trade_date} 09:30:00,{110 + index},"
                    f"{111 + index},{112 + index},{109 + index},{100 * index}\n"
                    f"{trade_date} 15:59:00,{111 + index},"
                    f"{112 + index},{113 + index},{110 + index},{120 * index}\n",
                    encoding="utf-8",
                )

            cfg = load_live_trading_config_from_payloads(
                build_quote_payload(),
                build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
            ).history_broker
            provider = LocalDataDailyHistoryProvider(
                cfg,
                logging.getLogger("test.local_history"),
                kline_minute_root=Path(tmp) / "kline_minute",
                kline_day_root=Path(tmp) / "kline_day",
                remote_minute_fetcher=remote_fetcher,
                now_provider=lambda: datetime(2026, 3, 14, 12, 0, tzinfo=ZoneInfo("America/New_York")),
            )
            histories = provider.fetch_daily_histories(["US.AMZN"], {"US.AMZN": 10})

            backfilled_daily = pd.read_csv(daily_dir / "US.AMZN_2026-03-09.csv")
            backfilled_minute = pd.read_csv(minute_dir / "US.AMZN_2026-03-13.csv")

        self.assertEqual(remote_calls, [("US.AMZN", 3900)])
        self.assertEqual(list(histories["US.AMZN"]["time_key"].dt.strftime("%Y-%m-%d")), [
            "2026-03-02",
            "2026-03-03",
            "2026-03-04",
            "2026-03-05",
            "2026-03-06",
            "2026-03-09",
            "2026-03-10",
            "2026-03-11",
            "2026-03-12",
            "2026-03-13",
        ])
        self.assertEqual(list(backfilled_daily["time_key"]), [
            "2026-03-09 00:00:00",
            "2026-03-10 00:00:00",
            "2026-03-11 00:00:00",
            "2026-03-12 00:00:00",
            "2026-03-13 00:00:00",
        ])
        self.assertEqual(list(backfilled_minute["time_key"]), ["2026-03-13 09:30:00", "2026-03-13 15:59:00"])

    def test_provider_updates_existing_weekly_daily_cache_from_local_minute_history(self) -> None:
        remote_calls: list[tuple[str, int]] = []

        def remote_fetcher(code: str, bars: int, page_size: int, max_pages: int) -> pd.DataFrame:
            remote_calls.append((code, bars))
            return pd.DataFrame(
                columns=["code", "time_key", "open", "close", "high", "low", "volume"]
            )

        with tempfile.TemporaryDirectory() as tmp:
            daily_dir = Path(tmp) / "kline_day" / "US.AMZN"
            minute_dir = Path(tmp) / "kline_minute" / "US.AMZN"
            daily_dir.mkdir(parents=True)
            minute_dir.mkdir(parents=True)
            (daily_dir / "US.AMZN_2026-03-02.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-02 00:00:00,100,101,102,99,1000\n"
                "2026-03-03 00:00:00,101,102,103,100,1001\n"
                "2026-03-04 00:00:00,102,103,104,101,1002\n"
                "2026-03-05 00:00:00,103,104,105,102,1003\n"
                "2026-03-06 00:00:00,104,105,106,103,1004\n",
                encoding="utf-8",
            )
            (daily_dir / "US.AMZN_2026-03-09.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-09 00:00:00,210.45,213.42,213.82,207.11,45432101\n"
                "2026-03-10 00:00:00,214.19,214.34,215.65,212.43,29280142\n"
                "2026-03-11 00:00:00,215.705,212.63,217.0,211.35,27566452\n"
                "2026-03-12 00:00:00,210.39,209.52,211.71,208.15,33119572\n",
                encoding="utf-8",
            )
            minute_rows = {
                "2026-03-02": (100.0, 101.0, 102.0, 99.0, 1000),
                "2026-03-03": (101.0, 102.0, 103.0, 100.0, 1001),
                "2026-03-04": (102.0, 103.0, 104.0, 101.0, 1002),
                "2026-03-05": (103.0, 104.0, 105.0, 102.0, 1003),
                "2026-03-06": (104.0, 105.0, 106.0, 103.0, 1004),
                "2026-03-09": (210.45, 213.42, 213.82, 207.11, 45432101),
                "2026-03-10": (214.19, 214.34, 215.65, 212.43, 29280142),
                "2026-03-11": (215.705, 212.63, 217.0, 211.35, 27566452),
                "2026-03-12": (210.39, 209.52, 211.71, 208.15, 33119572),
                "2026-03-13": (209.605, 207.49, 210.45, 206.12, 40123456),
            }
            for trade_date, values in minute_rows.items():
                open_price, close_price, high_price, low_price, volume = values
                (minute_dir / f"US.AMZN_{trade_date}.csv").write_text(
                    "time_key,open,close,high,low,volume\n"
                    f"{trade_date} 09:30:00,{open_price},{open_price},{high_price},{low_price},{volume // 2}\n"
                    f"{trade_date} 15:59:00,{open_price},{close_price},{high_price},{low_price},{volume - (volume // 2)}\n",
                    encoding="utf-8",
                )

            cfg = load_live_trading_config_from_payloads(
                build_quote_payload(),
                build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
            ).history_broker
            provider = LocalDataDailyHistoryProvider(
                cfg,
                logging.getLogger("test.local_history"),
                kline_minute_root=Path(tmp) / "kline_minute",
                kline_day_root=Path(tmp) / "kline_day",
                remote_minute_fetcher=remote_fetcher,
                now_provider=lambda: datetime(2026, 3, 14, 12, 0, tzinfo=ZoneInfo("America/New_York")),
            )
            histories = provider.fetch_daily_histories(["US.AMZN"], {"US.AMZN": 10})

            updated_daily = pd.read_csv(daily_dir / "US.AMZN_2026-03-09.csv")

        self.assertEqual(remote_calls, [])
        self.assertEqual(list(histories["US.AMZN"]["time_key"].dt.strftime("%Y-%m-%d"))[-1], "2026-03-13")
        self.assertEqual(list(updated_daily["time_key"]), [
            "2026-03-09 00:00:00",
            "2026-03-10 00:00:00",
            "2026-03-11 00:00:00",
            "2026-03-12 00:00:00",
            "2026-03-13 00:00:00",
        ])

    def test_provider_logs_error_when_remote_backfill_needed_but_unavailable(self) -> None:
        remote_calls: list[tuple[str, int]] = []

        def remote_fetcher(code: str, bars: int, page_size: int, max_pages: int) -> pd.DataFrame:
            remote_calls.append((code, bars))
            return pd.DataFrame(columns=["code", "time_key", "open", "close", "high", "low", "volume"])

        with tempfile.TemporaryDirectory() as tmp:
            daily_dir = Path(tmp) / "kline_day" / "US.AMZN"
            minute_dir = Path(tmp) / "kline_minute" / "US.AMZN"
            daily_dir.mkdir(parents=True)
            minute_dir.mkdir(parents=True)
            (daily_dir / "US.AMZN_2026-03-02.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-02 00:00:00,100,101,102,99,1000\n"
                "2026-03-03 00:00:00,101,102,103,100,1001\n"
                "2026-03-04 00:00:00,102,103,104,101,1002\n"
                "2026-03-05 00:00:00,103,104,105,102,1003\n"
                "2026-03-06 00:00:00,104,105,106,103,1004\n",
                encoding="utf-8",
            )
            for index, trade_date in enumerate(["2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12"], start=1):
                (minute_dir / f"US.AMZN_{trade_date}.csv").write_text(
                    "time_key,open,close,high,low,volume\n"
                    f"{trade_date} 09:30:00,{110 + index},"
                    f"{111 + index},{112 + index},{109 + index},{100 * index}\n"
                    f"{trade_date} 15:59:00,{111 + index},"
                    f"{112 + index},{113 + index},{110 + index},{120 * index}\n",
                    encoding="utf-8",
                )

            cfg = load_live_trading_config_from_payloads(
                build_quote_payload(),
                build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
            ).history_broker
            provider = LocalDataDailyHistoryProvider(
                cfg,
                logging.getLogger("test.local_history"),
                kline_minute_root=Path(tmp) / "kline_minute",
                kline_day_root=Path(tmp) / "kline_day",
                remote_minute_fetcher=remote_fetcher,
                now_provider=lambda: datetime(2026, 3, 14, 12, 0, tzinfo=ZoneInfo("America/New_York")),
            )

            with self.assertLogs("test.local_history", level="ERROR") as logs:
                histories = provider.fetch_daily_histories(["US.AMZN"], {"US.AMZN": 10})

        self.assertEqual(remote_calls, [("US.AMZN", 3900)])
        self.assertTrue(any("warm-up remote minute fetch returned no rows" in msg for msg in logs.output))
        self.assertEqual(list(histories["US.AMZN"]["time_key"].dt.strftime("%Y-%m-%d")), [
            "2026-03-02",
            "2026-03-03",
            "2026-03-04",
            "2026-03-05",
            "2026-03-06",
            "2026-03-09",
            "2026-03-10",
            "2026-03-11",
            "2026-03-12",
        ])

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
                histories = provider.fetch_daily_histories(["US.AAPL"], {"US.AAPL": 10})

        self.assertTrue(any("duplicate minute time_key" in msg for msg in logs.output))
        self.assertIn(15.0, list(histories["US.AAPL"]["close"]))

    def test_provider_logs_error_and_deduplicates_local_daily_time_key(self) -> None:
        cfg = load_live_trading_config_from_payloads(build_quote_payload(), build_trade_payload([build_trade_account_payload("a", "127.0.0.1")])).history_broker
        with tempfile.TemporaryDirectory() as tmp:
            daily_dir = Path(tmp) / "kline_day" / "US.AAPL"
            daily_dir.mkdir(parents=True)
            (daily_dir / "US.AAPL_2026-03-09.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-09 00:00:00,10,11,12,9,100\n"
                "2026-03-10 00:00:00,11,12,13,10,110\n",
                encoding="utf-8",
            )
            (daily_dir / "US.AAPL_2026-03-16.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-10 00:00:00,11,15,16,10,210\n"
                "2026-03-11 00:00:00,12,13,14,11,120\n",
                encoding="utf-8",
            )
            provider = LocalDataDailyHistoryProvider(
                cfg,
                logging.getLogger("test.local_history"),
                kline_minute_root=Path(tmp) / "kline_minute",
                kline_day_root=Path(tmp) / "kline_day",
            )

            with self.assertLogs("test.local_history", level="ERROR") as logs:
                histories = provider.fetch_daily_histories(["US.AAPL"], {"US.AAPL": 3})

        self.assertTrue(any("duplicate daily time_key" in msg for msg in logs.output))
        self.assertIn(15.0, list(histories["US.AAPL"]["close"]))


class PolygonCacheDailyHistoryProviderTests(unittest.TestCase):
    def test_create_daily_history_provider_uses_polygon_cache_provider(self) -> None:
        cfg = load_live_trading_config_from_payloads(
            build_quote_payload(history_type="polygon"),
            build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
        ).history_broker

        provider = create_daily_history_provider(cfg, logging.getLogger("test.polygon_cache_factory"))

        self.assertIsInstance(provider, PolygonCacheDailyHistoryProvider)
        self.assertEqual(provider._kline_day_root, Path(".kline_day"))

    def test_create_daily_history_provider_uses_futu_provider(self) -> None:
        cfg = load_live_trading_config_from_payloads(
            build_quote_payload(history_type="futu"),
            build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
        ).history_broker

        provider = create_daily_history_provider(cfg, logging.getLogger("test.futu_history_factory"))

        self.assertIsInstance(provider, FutuDailyHistoryProvider)

    def test_futu_provider_excludes_in_progress_daily_bar_and_rewrites_exact_cache(self) -> None:
        calls: list[tuple[str, int, object]] = []

        class FakeQuoteContext:
            def __init__(self, host: str, port: int) -> None:
                self.host = host
                self.port = port

            def get_cur_kline(self, code: str, bars: int, *, ktype: object) -> tuple[int, pd.DataFrame]:
                calls.append((code, bars, ktype))
                return (
                    0,
                    pd.DataFrame(
                        {
                            "code": [code] * 4,
                            "time_key": [
                                "2026-03-16 00:00:00",
                                "2026-03-17 00:00:00",
                                "2026-03-18 00:00:00",
                                "2026-03-19 00:00:00",
                            ],
                            "open": [10.0, 11.0, 12.0, 13.0],
                            "close": [10.5, 11.5, 12.5, 13.5],
                            "high": [11.0, 12.0, 13.0, 14.0],
                            "low": [9.5, 10.5, 11.5, 12.5],
                            "volume": [100.0, 110.0, 120.0, 130.0],
                        }
                    ),
                )

            def close(self) -> None:
                return None

        fake_futu = {
            "OpenQuoteContext": FakeQuoteContext,
            "KLType": type("FakeKLType", (), {"K_DAY": "K_DAY"}),
            "RET_OK": 0,
        }

        with tempfile.TemporaryDirectory() as tmp, patch("live_trading.broker._load_futu_api", return_value=fake_futu):
            cfg = load_live_trading_config_from_payloads(
                build_quote_payload(history_type="futu"),
                build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
            ).history_broker
            provider = FutuDailyHistoryProvider(
                cfg,
                logging.getLogger("test.futu_history_provider"),
                kline_day_root=Path(tmp) / ".kline_day",
                now_provider=lambda: datetime(2026, 3, 19, 15, 0, tzinfo=ZoneInfo("America/New_York")),
            )

            histories = provider.fetch_daily_histories(["US.AAPL"], {"US.AAPL": 3})
            cached_files = sorted((Path(tmp) / ".kline_day" / "US.AAPL").glob("*.csv"))
            cached_rows = []
            for path in cached_files:
                cached_rows.extend(pd.read_csv(path)["time_key"].tolist())

        self.assertEqual(calls, [("US.AAPL", 4, "K_DAY")])
        self.assertEqual(list(histories["US.AAPL"]["time_key"].dt.strftime("%Y-%m-%d")), [
            "2026-03-16",
            "2026-03-17",
            "2026-03-18",
        ])
        self.assertEqual([path.name for path in cached_files], ["US.AAPL_2026-03-16.csv"])
        self.assertEqual(cached_rows, [
            "2026-03-16 00:00:00",
            "2026-03-17 00:00:00",
            "2026-03-18 00:00:00",
        ])

    def test_polygon_cache_provider_reads_dot_kline_day_and_trims_to_requested_bars_when_fresh(self) -> None:
        remote_calls: list[tuple[str, int]] = []

        def remote_fetcher(code: str, bars: int) -> pd.DataFrame:
            remote_calls.append((code, bars))
            return pd.DataFrame(columns=["code", "time_key", "open", "close", "high", "low", "volume"])

        with tempfile.TemporaryDirectory() as tmp:
            dot_daily_dir = Path(tmp) / ".kline_day" / "US.MSFT"
            backtest_daily_dir = Path(tmp) / "kline_day" / "US.MSFT"
            dot_daily_dir.mkdir(parents=True)
            backtest_daily_dir.mkdir(parents=True)
            (dot_daily_dir / "US.MSFT_2026-03-09.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-09 00:00:00,100,101,102,99,1000\n"
                "2026-03-10 00:00:00,101,102,103,100,1001\n"
                "2026-03-11 00:00:00,102,103,104,101,1002\n"
                "2026-03-12 00:00:00,103,104,105,102,1003\n"
                "2026-03-13 00:00:00,104,105,106,103,1004\n"
                "2026-03-16 00:00:00,105,106,107,104,1005\n"
                "2026-03-17 00:00:00,106,107,108,105,1006\n"
                "2026-03-18 00:00:00,107,108,109,106,1007\n"
                "2026-03-19 00:00:00,108,109,110,107,1008\n"
                "2026-03-20 00:00:00,109,110,111,108,1009\n",
                encoding="utf-8",
            )
            (backtest_daily_dir / "US.MSFT_2026-03-09.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-09 00:00:00,200,201,202,199,2000\n",
                encoding="utf-8",
            )

            cfg = load_live_trading_config_from_payloads(
                build_quote_payload(history_type="polygon"),
                build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
            ).history_broker
            provider = PolygonCacheDailyHistoryProvider(
                cfg,
                logging.getLogger("test.polygon_cache"),
                kline_day_root=Path(tmp) / ".kline_day",
                remote_daily_fetcher=remote_fetcher,
                now_provider=lambda: datetime(2026, 3, 21, 12, 0, tzinfo=ZoneInfo("America/New_York")),
            )

            histories = provider.fetch_daily_histories(["US.MSFT"], {"US.MSFT": 3})
            cached_files = sorted((Path(tmp) / ".kline_day" / "US.MSFT").glob("*.csv"))
            cached_rows = []
            for path in cached_files:
                cached_rows.extend(pd.read_csv(path)["time_key"].tolist())

        self.assertEqual(remote_calls, [])
        self.assertEqual(list(histories["US.MSFT"]["close"]), [108.0, 109.0, 110.0])
        self.assertEqual([path.name for path in cached_files], ["US.MSFT_2026-03-16.csv"])
        self.assertEqual(cached_rows, [
            "2026-03-18 00:00:00",
            "2026-03-19 00:00:00",
            "2026-03-20 00:00:00",
        ])

    def test_polygon_cache_provider_fetches_remote_daily_and_writes_weekly_cache_when_missing(self) -> None:
        remote_calls: list[tuple[str, int]] = []

        def remote_fetcher(code: str, bars: int) -> pd.DataFrame:
            remote_calls.append((code, bars))
            return pd.DataFrame(
                {
                    "code": [code] * 10,
                    "time_key": pd.to_datetime(
                        [
                            "2026-03-09",
                            "2026-03-10",
                            "2026-03-11",
                            "2026-03-12",
                            "2026-03-13",
                            "2026-03-16",
                            "2026-03-17",
                            "2026-03-18",
                            "2026-03-19",
                            "2026-03-20",
                        ]
                    ),
                    "open": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0],
                    "close": [10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5],
                    "high": [11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0],
                    "low": [9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5],
                    "volume": [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0, 190.0],
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_live_trading_config_from_payloads(
                build_quote_payload(history_type="polygon"),
                build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
            ).history_broker
            provider = PolygonCacheDailyHistoryProvider(
                cfg,
                logging.getLogger("test.polygon_cache"),
                kline_day_root=Path(tmp) / ".kline_day",
                remote_daily_fetcher=remote_fetcher,
                now_provider=lambda: datetime(2026, 3, 21, 12, 0, tzinfo=ZoneInfo("America/New_York")),
            )

            histories = provider.fetch_daily_histories(["US.NVDA"], {"US.NVDA": 10})
            cached_files = sorted((Path(tmp) / ".kline_day" / "US.NVDA").glob("*.csv"))

        self.assertEqual(remote_calls, [("US.NVDA", 10)])
        self.assertEqual(list(histories["US.NVDA"]["close"]), [10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5])
        self.assertEqual([path.name for path in cached_files], ["US.NVDA_2026-03-09.csv", "US.NVDA_2026-03-16.csv"])

    def test_polygon_cache_refresh_keeps_exact_requested_bars_when_boundary_week_is_partial(self) -> None:
        def remote_fetcher(code: str, bars: int) -> pd.DataFrame:
            self.assertEqual(bars, 3)
            return pd.DataFrame(
                {
                    "code": [code, code, code],
                    "time_key": pd.to_datetime(["2026-03-11", "2026-03-12", "2026-03-13"]),
                    "open": [8.0, 9.0, 10.0],
                    "close": [8.5, 9.5, 10.5],
                    "high": [9.0, 10.0, 11.0],
                    "low": [7.5, 8.5, 9.5],
                    "volume": [180.0, 190.0, 200.0],
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            code_dir = Path(tmp) / ".kline_day" / "US.MSFT"
            code_dir.mkdir(parents=True)
            (code_dir / "US.MSFT_2026-03-02.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-02 00:00:00,1,1.5,2,0.5,100\n"
                "2026-03-03 00:00:00,2,2.5,3,1.5,110\n"
                "2026-03-04 00:00:00,3,3.5,4,2.5,120\n"
                "2026-03-05 00:00:00,4,4.5,5,3.5,130\n"
                "2026-03-06 00:00:00,5,5.5,6,4.5,140\n",
                encoding="utf-8",
            )
            (code_dir / "US.MSFT_2026-03-09.csv").write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-09 00:00:00,6,6.5,7,5.5,150\n"
                "2026-03-10 00:00:00,7,7.5,8,6.5,160\n",
                encoding="utf-8",
            )

            cfg = load_live_trading_config_from_payloads(
                build_quote_payload(history_type="polygon"),
                build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
            ).history_broker
            provider = PolygonCacheDailyHistoryProvider(
                cfg,
                logging.getLogger("test.polygon_cache_partial_week"),
                kline_day_root=Path(tmp) / ".kline_day",
                remote_daily_fetcher=remote_fetcher,
                now_provider=lambda: datetime(2026, 3, 14, 12, 0, tzinfo=ZoneInfo("America/New_York")),
            )

            histories = provider.fetch_daily_histories(["US.MSFT"], {"US.MSFT": 3})
            week_b = pd.read_csv(code_dir / "US.MSFT_2026-03-09.csv")
            remaining_files = sorted(path.name for path in code_dir.glob("*.csv"))

        self.assertEqual(list(week_b["time_key"]), [
            "2026-03-11 00:00:00",
            "2026-03-12 00:00:00",
            "2026-03-13 00:00:00",
        ])
        self.assertEqual(remaining_files, ["US.MSFT_2026-03-09.csv"])
        self.assertEqual(list(histories["US.MSFT"]["close"]), [8.5, 9.5, 10.5])

    def test_polygon_cache_returns_unavailable_when_stale_cache_refresh_fails(self) -> None:
        def remote_fetcher(code: str, bars: int) -> pd.DataFrame:
            return pd.DataFrame(columns=["code", "time_key", "open", "close", "high", "low", "volume"])

        with tempfile.TemporaryDirectory() as tmp:
            code_dir = Path(tmp) / ".kline_day" / "US.MSFT"
            code_dir.mkdir(parents=True)
            stale_file = code_dir / "US.MSFT_2026-03-09.csv"
            stale_file.write_text(
                "time_key,open,close,high,low,volume\n"
                "2026-03-09 00:00:00,6,6.5,7,5.5,150\n"
                "2026-03-10 00:00:00,7,7.5,8,6.5,160\n"
                "2026-03-11 00:00:00,8,8.5,9,7.5,170\n",
                encoding="utf-8",
            )

            cfg = load_live_trading_config_from_payloads(
                build_quote_payload(history_type="polygon"),
                build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
            ).history_broker
            provider = PolygonCacheDailyHistoryProvider(
                cfg,
                logging.getLogger("test.polygon_cache_stale_failure"),
                kline_day_root=Path(tmp) / ".kline_day",
                remote_daily_fetcher=remote_fetcher,
                now_provider=lambda: datetime(2026, 3, 14, 12, 0, tzinfo=ZoneInfo("America/New_York")),
            )

            histories = provider.fetch_daily_histories(["US.MSFT"], {"US.MSFT": 3})
            cached_rows = pd.read_csv(stale_file)["time_key"].tolist()

        self.assertTrue(histories["US.MSFT"].empty)
        self.assertEqual(cached_rows, [
            "2026-03-09 00:00:00",
            "2026-03-10 00:00:00",
            "2026-03-11 00:00:00",
        ])

    def test_polygon_remote_fetch_stops_expanding_when_larger_window_adds_no_rows(self) -> None:
        cfg = load_live_trading_config_from_payloads(
            build_quote_payload(history_type="polygon"),
            build_trade_payload([build_trade_account_payload("a", "127.0.0.1")]),
        ).history_broker
        provider = PolygonCacheDailyHistoryProvider(
            cfg,
            logging.getLogger("test.polygon_cache_stalled"),
            now_provider=lambda: datetime(2026, 3, 21, 12, 0, tzinfo=ZoneInfo("America/New_York")),
        )
        results = []
        for trade_date in pd.date_range("2026-02-20", periods=20, freq="B"):
            results.append(
                {
                    "t": int(pd.Timestamp(trade_date, tz="America/New_York").timestamp() * 1000),
                    "o": 10.0,
                    "c": 10.5,
                    "h": 11.0,
                    "l": 9.5,
                    "v": 100.0,
                }
            )

        with patch.dict("os.environ", {"POLYGON_API_KEY": "test-key"}), patch.object(
            provider,
            "_request_polygon_daily_results",
            side_effect=[results, results],
        ) as request_results:
            history = provider._fetch_remote_daily_history("US.IPO", 35)

        self.assertEqual(request_results.call_count, 2)
        self.assertEqual(len(history), 20)

    def test_weekly_cache_uses_natural_monday_start_without_creating_gap_week(self) -> None:
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

        self.assertEqual(created, ["US.NVDA_2026-03-02.csv", "US.NVDA_2026-03-16.csv"])


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

    def test_engine_retries_history_warmup_until_provider_recovers(self) -> None:
        class FlakyHistoryProvider(DailyHistoryProvider):
            instances: list["FlakyHistoryProvider"] = []

            def __init__(self, config, logger) -> None:
                self.config = config
                self.logger = logger
                self.closed = False
                self.fetch_calls = 0
                FlakyHistoryProvider.instances.append(self)

            def fetch_daily_histories(self, codes, daily_warmup_bars):
                self.fetch_calls += 1
                codes_tuple = tuple(codes)
                if self.fetch_calls == 1:
                    return {code: pd.DataFrame(columns=["code", "time_key", "open", "close", "high", "low", "volume"]) for code in codes_tuple}
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

        FakeQuoteBroker.instances.clear()
        FakeTradeAccountClient.instances.clear()
        FlakyHistoryProvider.instances.clear()

        with tempfile.TemporaryDirectory() as tmp:
            quote_path = Path(tmp) / "quote.json"
            trade_path = Path(tmp) / "trade.json"
            quote_payload = build_quote_payload()
            quote_payload["runtime"]["config_reload_interval_seconds"] = 0.05
            quote_path.write_text(json.dumps(quote_payload), encoding="utf-8")
            trade_path.write_text(
                json.dumps(build_trade_payload([build_trade_account_payload("sim_primary", "127.0.0.9")])),
                encoding="utf-8",
            )

            engine = LiveTradingEngine(
                quote_path,
                trade_path,
                quote_broker_factory=FakeQuoteBroker,
                history_provider_factory=FlakyHistoryProvider,
                trade_account_factory=FakeTradeAccountClient,
            )
            thread = threading.Thread(target=engine.run, daemon=True)
            thread.start()
            deadline = time.time() + 1.5
            while time.time() < deadline:
                if engine._pool_strategy is not None and FlakyHistoryProvider.instances and FlakyHistoryProvider.instances[0].fetch_calls >= 2:
                    break
                time.sleep(0.05)
            engine.stop()
            thread.join(timeout=1.0)

        self.assertEqual(len(FlakyHistoryProvider.instances), 1)
        self.assertGreaterEqual(FlakyHistoryProvider.instances[0].fetch_calls, 2)
        self.assertFalse(engine._history_warmup_pending)
        self.assertIsNotNone(engine._pool_strategy)
        self.assertEqual(len(FakeQuoteBroker.instances), 1)
        self.assertEqual(FakeQuoteBroker.instances[0].connect_calls, 1)


def load_live_trading_config_from_payloads(quote_payload: dict, trade_payload: dict) -> object:
    with tempfile.TemporaryDirectory() as tmp:
        quote_path = Path(tmp) / "quote.json"
        trade_path = Path(tmp) / "trade.json"
        quote_path.write_text(json.dumps(quote_payload), encoding="utf-8")
        trade_path.write_text(json.dumps(trade_payload), encoding="utf-8")
        return load_live_trading_config(quote_path, trade_path)


if __name__ == "__main__":
    unittest.main()
