from __future__ import annotations

from abc import ABC, abstractmethod
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterable, Mapping, Protocol

import pandas as pd

try:
    from .config import HistoryBrokerConfig, RealtimeQuoteBrokerConfig, TradeAccountConfig
    from .models import AccountSnapshot, PositionSnapshot, QuoteUpdate
except ImportError:
    from live_trading.config import HistoryBrokerConfig, RealtimeQuoteBrokerConfig, TradeAccountConfig
    from live_trading.models import AccountSnapshot, PositionSnapshot, QuoteUpdate


class QuoteBrokerEventSink(Protocol):
    def on_quote(self, update: QuoteUpdate) -> None:
        raise NotImplementedError

    def on_bar(self, code: str, bar: pd.Series | dict[str, Any]) -> None:
        raise NotImplementedError

    def on_broker_message(self, level: int, message: str) -> None:
        raise NotImplementedError


class TradeAccountEventSink(Protocol):
    def on_account(self, account_id: str, snapshot: AccountSnapshot) -> None:
        raise NotImplementedError

    def on_positions(self, account_id: str, positions: dict[str, PositionSnapshot]) -> None:
        raise NotImplementedError

    def on_broker_message(self, level: int, message: str) -> None:
        raise NotImplementedError


class QuoteBrokerClient(ABC):
    @abstractmethod
    def connect(self, codes: Iterable[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_symbols(self, codes: Iterable[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class DailyHistoryProvider(ABC):
    @abstractmethod
    def fetch_daily_histories(
        self,
        codes: Iterable[str],
        daily_warmup_bars: Mapping[str, int],
    ) -> dict[str, pd.DataFrame]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class TradeAccountClient(ABC):
    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class FutuRealtimeQuoteClient(QuoteBrokerClient):
    def __init__(self, config: RealtimeQuoteBrokerConfig, event_sink: QuoteBrokerEventSink, logger: logging.Logger) -> None:
        self._config = config
        self._event_sink = event_sink
        self._logger = logger
        self._quote_ctx = None
        self._futu = None
        self._codes: list[str] = []
        self._lock = threading.RLock()

    def connect(self, codes: Iterable[str]) -> None:
        with self._lock:
            self.close()
            self._futu = _load_futu_api()
            self._quote_ctx = self._futu["OpenQuoteContext"](host=self._config.host, port=self._config.port)
            self._quote_ctx.set_handler(self._build_quote_handler())
            self._quote_ctx.set_handler(self._build_kline_handler())
            self._quote_ctx.start()
        self.update_symbols(codes)

    def update_symbols(self, codes: Iterable[str]) -> None:
        with self._lock:
            if self._quote_ctx is None or self._futu is None:
                raise RuntimeError("Futu realtime quote broker is not connected")

            target_codes = sorted({str(code).strip().upper() for code in codes if str(code).strip()})
            if self._codes:
                ret, data = self._quote_ctx.unsubscribe(self._codes, [self._futu["SubType"].QUOTE, self._futu["SubType"].K_1M])
                if ret != self._futu["RET_OK"]:
                    self._event_sink.on_broker_message(logging.WARNING, f"quote unsubscribe failed: {data}")

            if target_codes:
                ret, data = self._quote_ctx.subscribe(
                    target_codes,
                    [self._futu["SubType"].QUOTE, self._futu["SubType"].K_1M],
                    is_first_push=False,
                    subscribe_push=True,
                    extended_time=self._config.extended_time,
                )
                if ret != self._futu["RET_OK"]:
                    raise RuntimeError(f"quote subscribe failed: {data}")

            self._codes = target_codes

    def close(self) -> None:
        with self._lock:
            quote_ctx = self._quote_ctx
            self._quote_ctx = None
            self._codes = []
            if quote_ctx is not None:
                try:
                    quote_ctx.close()
                except Exception as exc:
                    self._event_sink.on_broker_message(logging.WARNING, f"quote context close failed: {exc}")

    def _build_quote_handler(self):
        futu = self._futu
        broker = self

        class QuoteHandler(futu["StockQuoteHandlerBase"]):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code != futu["RET_OK"]:
                    broker._event_sink.on_broker_message(logging.ERROR, f"quote push error: {content}")
                    return ret_code, content
                broker._handle_quote_frame(content)
                return ret_code, content

        return QuoteHandler()

    def _build_kline_handler(self):
        futu = self._futu
        broker = self

        class KlineHandler(futu["CurKlineHandlerBase"]):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code != futu["RET_OK"]:
                    broker._event_sink.on_broker_message(logging.ERROR, f"kline push error: {content}")
                    return ret_code, content
                broker._handle_kline_frame(content)
                return ret_code, content

        return KlineHandler()

    def _handle_quote_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        for row in frame.itertuples(index=False):
            timestamp = pd.Timestamp(f"{row.data_date} {row.data_time}")
            self._event_sink.on_quote(
                QuoteUpdate(
                    code=str(row.code),
                    timestamp=timestamp,
                    last_price=float(row.last_price),
                    volume=float(row.volume) if not pd.isna(row.volume) else None,
                    turnover=float(row.turnover) if not pd.isna(row.turnover) else None,
                    open_price=float(row.open_price) if not pd.isna(row.open_price) else None,
                    high_price=float(row.high_price) if not pd.isna(row.high_price) else None,
                    low_price=float(row.low_price) if not pd.isna(row.low_price) else None,
                    prev_close_price=float(row.prev_close_price) if not pd.isna(row.prev_close_price) else None,
                    source="quote",
                )
            )

    def _handle_kline_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        normalized = frame.copy()
        normalized["time_key"] = pd.to_datetime(normalized["time_key"])
        for row in normalized.sort_values("time_key").itertuples(index=False):
            self._event_sink.on_bar(
                str(row.code),
                {
                    "code": str(row.code),
                    "time_key": pd.Timestamp(row.time_key),
                    "open": float(row.open),
                    "close": float(row.close),
                    "high": float(row.high),
                    "low": float(row.low),
                    "volume": float(row.volume) if not pd.isna(row.volume) else 0.0,
                },
            )


class MockRealtimeQuoteClient(QuoteBrokerClient):
    def __init__(self, config: RealtimeQuoteBrokerConfig, event_sink: QuoteBrokerEventSink, logger: logging.Logger) -> None:
        self._config = config
        self._event_sink = event_sink
        self._logger = logger
        self._codes: list[str] = []
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None

    def connect(self, codes: Iterable[str]) -> None:
        with self._lock:
            self.close()
            self._codes = self._normalize_codes(codes)
            self._server = self._build_server()
            server_host, server_port = self._server.server_address[:2]
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                name=f"mock-quote-server-{server_host}:{server_port}",
                daemon=True,
            )
            self._server_thread.start()
            self._event_sink.on_broker_message(
                logging.INFO,
                f"mock realtime quote broker listening at http://{server_host}:{server_port}/push "
                f"codes={','.join(self._codes)}",
            )

    def update_symbols(self, codes: Iterable[str]) -> None:
        with self._lock:
            self._codes = self._normalize_codes(codes)
            self._event_sink.on_broker_message(
                logging.INFO,
                f"mock realtime quote broker updated symbols: {','.join(self._codes)}",
            )

    def close(self) -> None:
        with self._lock:
            server = self._server
            thread = self._server_thread
            self._server = None
            self._server_thread = None
            self._codes = []
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

    def push_bar(self, payload: Mapping[str, Any]) -> bool:
        bar = self._normalize_bar_payload(payload)
        code = str(bar["code"])
        with self._lock:
            subscribed_codes = tuple(self._codes)
        if not subscribed_codes or code not in subscribed_codes:
            self._event_sink.on_broker_message(
                logging.WARNING,
                f"mock realtime quote broker ignored push for unsubscribed code={code}",
            )
            return False

        timestamp = pd.Timestamp(bar["time_key"])
        self._event_sink.on_quote(
            QuoteUpdate(
                code=code,
                timestamp=timestamp,
                last_price=float(bar["close"]),
                volume=float(bar["volume"]),
                turnover=_coerce_optional_float(payload.get("turnover")),
                open_price=float(bar["open"]),
                high_price=float(bar["high"]),
                low_price=float(bar["low"]),
                prev_close_price=_coerce_optional_float(payload.get("prev_close_price")),
                source="mock",
                raw=dict(payload),
            )
        )
        self._event_sink.on_bar(code, bar)
        self._event_sink.on_broker_message(
            logging.INFO,
            f"mock realtime quote broker pushed code={code} time={timestamp} close={bar['close']}",
        )
        return True

    def push_bars(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        items_raw = payload.get("bars", payload)
        if isinstance(items_raw, Mapping):
            items = [items_raw]
        elif isinstance(items_raw, list):
            items = items_raw
        else:
            raise ValueError("payload must be a JSON object or contain bars[]")
        if not items:
            raise ValueError("bars[] must not be empty")

        accepted = 0
        ignored = 0
        for item in items:
            if not isinstance(item, Mapping):
                raise ValueError("each bar payload must be a JSON object")
            if self.push_bar(item):
                accepted += 1
            else:
                ignored += 1
        return {
            "accepted": accepted,
            "ignored": ignored,
            "subscribed_codes": list(self._codes),
        }

    def _build_server(self) -> ThreadingHTTPServer:
        broker = self

        class MockQuotePushServer(ThreadingHTTPServer):
            allow_reuse_address = True

        class MockQuotePushHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != "/health":
                    self._send_json(404, {"error": "not found"})
                    return
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "codes": list(broker._codes),
                    },
                )

            def do_POST(self) -> None:
                if self.path != "/push":
                    self._send_json(404, {"error": "not found"})
                    return
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(400, {"error": "invalid content length"})
                    return
                body = self.rfile.read(content_length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                    if not isinstance(payload, Mapping):
                        raise ValueError("payload must be a JSON object")
                    result = broker.push_bars(payload)
                except Exception as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(200, result)

            def log_message(self, format: str, *args: object) -> None:
                return None

            def _send_json(self, status: int, payload: Mapping[str, Any]) -> None:
                encoded = json.dumps(dict(payload)).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        server = MockQuotePushServer((self._config.host, self._config.port), MockQuotePushHandler)
        server.daemon_threads = True
        return server

    def _normalize_codes(self, codes: Iterable[str]) -> list[str]:
        return sorted({str(code).strip().upper() for code in codes if str(code).strip()})

    def _normalize_bar_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        code = str(payload.get("code", "")).strip().upper()
        if not code:
            raise ValueError("bar.code must not be empty")
        raw_time_key = payload.get("time_key")
        if raw_time_key is None:
            raise ValueError("bar.time_key must not be empty")

        timestamp = pd.Timestamp(raw_time_key)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)

        close = float(payload.get("close"))
        open_price = float(payload.get("open", close))
        high_price = float(payload.get("high", max(open_price, close)))
        low_price = float(payload.get("low", min(open_price, close)))
        volume = float(payload.get("volume", 0.0))
        return {
            "code": code,
            "time_key": timestamp,
            "open": open_price,
            "close": close,
            "high": high_price,
            "low": low_price,
            "volume": volume,
        }


class FutuDailyHistoryProvider(DailyHistoryProvider):
    def __init__(self, config: HistoryBrokerConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger

    def fetch_daily_histories(
        self,
        codes: Iterable[str],
        daily_warmup_bars: Mapping[str, int],
    ) -> dict[str, pd.DataFrame]:
        futu = _load_futu_api()
        quote_ctx = futu["OpenQuoteContext"](host=self._config.host, port=self._config.port)
        try:
            histories: dict[str, pd.DataFrame] = {}
            for code in sorted({str(code).strip().upper() for code in codes if str(code).strip()}):
                bars = min(max(int(daily_warmup_bars.get(code, 10)), 10), 1000)
                ret, data = quote_ctx.get_cur_kline(code, bars, ktype=futu["KLType"].K_DAY)
                if ret != futu["RET_OK"]:
                    self._logger.warning("get_cur_kline failed for %s: %s", code, data)
                    histories[code] = pd.DataFrame(columns=["code", "time_key", "open", "close", "high", "low", "volume"])
                    continue
                history = data.copy()
                history["time_key"] = pd.to_datetime(history["time_key"])
                histories[code] = history
            return histories
        finally:
            quote_ctx.close()

    def close(self) -> None:
        return None


class LocalDataDailyHistoryProvider(DailyHistoryProvider):
    def __init__(
        self,
        config: HistoryBrokerConfig,
        logger: logging.Logger,
        *,
        data_root: Path | str = "data",
        daily_data_root: Path | str = "daily_data",
        remote_minute_fetcher: Callable[..., pd.DataFrame] | None = None,
        remote_minute_page_size: int = 1000,
        remote_minute_max_pages: int = 20,
    ) -> None:
        self._config = config
        self._logger = logger
        self._data_root = Path(data_root)
        self._daily_data_root = Path(daily_data_root)
        self._remote_minute_fetcher = remote_minute_fetcher
        self._remote_minute_page_size = max(int(remote_minute_page_size), 1)
        self._remote_minute_max_pages = max(int(remote_minute_max_pages), 1)

    def fetch_daily_histories(
        self,
        codes: Iterable[str],
        daily_warmup_bars: Mapping[str, int],
    ) -> dict[str, pd.DataFrame]:
        normalized_codes = sorted({str(code).strip().upper() for code in codes if str(code).strip()})
        histories: dict[str, pd.DataFrame] = {}

        for code in normalized_codes:
            bars = min(max(int(daily_warmup_bars.get(code, 10)), 10), 1000)
            history = self._load_daily_from_daily_data(code, bars)
            if history is not None:
                histories[code] = history
                continue

            minute_history, minute_from_remote = self._load_minute_for_warmup(code, bars)
            if minute_history is None or minute_history.empty:
                self._logger.warning("warm-up minute data unavailable code=%s", code)
                histories[code] = pd.DataFrame(columns=["code", "time_key", "open", "close", "high", "low", "volume"])
                continue

            daily_history = self._aggregate_minute_to_daily(code, minute_history, bars)
            self._write_daily_weekly_csv_if_missing(code, daily_history)
            if minute_from_remote:
                self._write_minute_weekly_csv_if_missing(code, minute_history)
            histories[code] = daily_history

        return histories

    def close(self) -> None:
        return None

    def _load_daily_from_daily_data(self, code: str, bars: int) -> pd.DataFrame | None:
        code_dir = self._daily_data_root / code
        daily = self._load_local_csv_history(code_dir, code, frame_type="daily")
        if daily is None:
            return None
        result = daily.tail(bars).reset_index(drop=True)
        self._logger.info("warm-up loaded from daily_data code=%s rows=%d dir=%s", code, len(result), code_dir)
        return result

    def _load_minute_for_warmup(self, code: str, bars: int) -> tuple[pd.DataFrame | None, bool]:
        code_dir = self._data_root / code
        minute = self._load_local_csv_history(code_dir, code, frame_type="minute", dedupe_error=True)
        if minute is not None:
            self._logger.info("warm-up minute loaded from data code=%s rows=%d dir=%s", code, len(minute), code_dir)
            local_daily_bars = minute["time_key"].dt.date.nunique()
            if local_daily_bars >= bars:
                return minute, False

        minute_target_bars = max(bars * 390, 390)
        if self._remote_minute_fetcher is not None:
            try:
                remote = self._remote_minute_fetcher(
                    code,
                    minute_target_bars,
                    self._remote_minute_page_size,
                    self._remote_minute_max_pages,
                )
            except TypeError:
                remote = self._remote_minute_fetcher(code, minute_target_bars)
        else:
            remote = self._fetch_remote_minute_history(code, minute_target_bars)
        if remote is None or remote.empty:
            return minute, True

        if minute is not None:
            remote = pd.concat([minute, remote], ignore_index=True)

        remote = remote.copy()
        remote["time_key"] = pd.to_datetime(remote["time_key"])
        remote = remote.sort_values("time_key").reset_index(drop=True)
        remote = remote.drop_duplicates(subset=["time_key"], keep="last").reset_index(drop=True)
        self._logger.info("warm-up minute fetched remote code=%s rows=%d", code, len(remote))
        return remote, True

    def _load_local_csv_history(self, code_dir: Path, code: str, *, frame_type: str, dedupe_error: bool = False) -> pd.DataFrame | None:
        if not code_dir.is_dir():
            return None
        csv_files = sorted(code_dir.glob("*.csv"))
        if not csv_files:
            return None

        frames: list[pd.DataFrame] = []
        required_columns = {"time_key", "open", "close", "high", "low", "volume"}
        for path in csv_files:
            frame = pd.read_csv(path)
            if not required_columns.issubset(set(frame.columns)):
                self._logger.warning("local %s warm-up file missing columns code=%s path=%s", frame_type, code, path)
                continue
            frame = frame.copy()
            frame["time_key"] = pd.to_datetime(frame["time_key"])
            frame["code"] = code
            frames.append(frame[["code", "time_key", "open", "close", "high", "low", "volume"]])

        if not frames:
            return None
        merged = pd.concat(frames, ignore_index=True)
        merged = merged.sort_values("time_key").reset_index(drop=True)
        duplicated_mask = merged.duplicated(subset=["time_key"], keep="last")
        duplicated_count = int(duplicated_mask.sum())
        if duplicated_count > 0:
            if dedupe_error:
                self._logger.error(
                    "duplicate %s time_key detected and deduplicated code=%s dir=%s duplicated_rows=%d",
                    frame_type,
                    code,
                    code_dir,
                    duplicated_count,
                )
            else:
                self._logger.warning(
                    "duplicate %s time_key detected and deduplicated code=%s dir=%s duplicated_rows=%d",
                    frame_type,
                    code,
                    code_dir,
                    duplicated_count,
                )
            merged = merged.drop_duplicates(subset=["time_key"], keep="last").reset_index(drop=True)
        return merged

    def _aggregate_minute_to_daily(self, code: str, minute: pd.DataFrame, bars: int) -> pd.DataFrame:
        minute = minute.copy()
        minute["trade_date"] = minute["time_key"].dt.date
        daily = (
            minute.groupby("trade_date", as_index=False)
            .agg(
                open=("open", "first"),
                close=("close", "last"),
                high=("high", "max"),
                low=("low", "min"),
                volume=("volume", "sum"),
            )
            .sort_values("trade_date")
            .reset_index(drop=True)
        )
        daily["code"] = code
        daily["time_key"] = pd.to_datetime(daily["trade_date"])
        daily = daily[["code", "time_key", "open", "close", "high", "low", "volume"]]
        return daily.tail(bars).reset_index(drop=True)

    def _fetch_remote_minute_history(self, code: str, bars: int) -> pd.DataFrame:
        futu = _load_futu_api()
        quote_ctx = futu["OpenQuoteContext"](host=self._config.host, port=self._config.port)
        try:
            rows: list[pd.DataFrame] = []
            remaining = bars
            page_req_key = None
            for _ in range(self._remote_minute_max_pages):
                page_size = min(self._remote_minute_page_size, remaining)
                ret, data, page_req_key = quote_ctx.request_history_kline(
                    code,
                    start=None,
                    end=None,
                    ktype=futu["KLType"].K_1M,
                    max_count=page_size,
                    page_req_key=page_req_key,
                )
                if ret != futu["RET_OK"]:
                    self._logger.warning("request_history_kline K_1M failed for %s: %s", code, data)
                    break
                if data is None or data.empty:
                    break
                rows.append(data.copy())
                remaining -= len(data)
                if remaining <= 0 or page_req_key is None:
                    break

            if not rows:
                return pd.DataFrame(columns=["code", "time_key", "open", "close", "high", "low", "volume"])
            history = pd.concat(rows, ignore_index=True)
            history["time_key"] = pd.to_datetime(history["time_key"])
            history = history.sort_values("time_key").drop_duplicates(subset=["time_key"], keep="last").reset_index(drop=True)
            return history[["code", "time_key", "open", "close", "high", "low", "volume"]]
        finally:
            quote_ctx.close()

    def _write_daily_weekly_csv_if_missing(self, code: str, daily: pd.DataFrame) -> None:
        code_dir = self._daily_data_root / code
        code_dir.mkdir(parents=True, exist_ok=True)
        self._write_weekly_csv_if_missing(code_dir, code, daily)

    def _write_minute_weekly_csv_if_missing(self, code: str, minute: pd.DataFrame) -> None:
        code_dir = self._data_root / code
        code_dir.mkdir(parents=True, exist_ok=True)
        self._write_weekly_csv_if_missing(code_dir, code, minute)

    def _write_weekly_csv_if_missing(self, code_dir: Path, code: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        data = frame.copy()
        data["time_key"] = pd.to_datetime(data["time_key"])
        data["week_start"] = data["time_key"].dt.normalize() - pd.to_timedelta(data["time_key"].dt.weekday, unit="D")
        grouped = {pd.Timestamp(week_start): weekly for week_start, weekly in data.groupby("week_start")}
        min_week = min(grouped.keys())
        max_week = max(grouped.keys())
        cursor = min_week
        while cursor <= max_week:
            file_path = code_dir / f"{code}_{cursor.date().isoformat()}.csv"
            if not file_path.exists():
                weekly = grouped.get(cursor)
                if weekly is None:
                    payload = pd.DataFrame(columns=["time_key", "open", "close", "high", "low", "volume"])
                else:
                    payload = weekly[["time_key", "open", "close", "high", "low", "volume"]].copy()
                    payload["time_key"] = payload["time_key"].dt.strftime("%Y-%m-%d %H:%M:%S")
                payload.to_csv(file_path, index=False)
                self._logger.info("warm-up cache file created path=%s rows=%d", file_path, len(payload))
            cursor = cursor + pd.Timedelta(days=7)


class FutuTradeAccountClient(TradeAccountClient):
    def __init__(self, config: TradeAccountConfig, event_sink: TradeAccountEventSink, logger: logging.Logger) -> None:
        self._config = config
        self._event_sink = event_sink
        self._logger = logger
        self._trade_ctx = None
        self._futu = None
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def connect(self) -> None:
        with self._lock:
            self.close()
            self._poll_stop = threading.Event()
            self._futu = _load_futu_api()
            self._trade_ctx = self._futu["OpenSecTradeContext"](
                filter_trdmarket=self._futu["TrdMarket"].US,
                host=self._config.broker.host,
                port=self._config.broker.port,
            )
            self._trade_ctx.set_handler(self._build_trade_order_handler())
            self._trade_ctx.set_handler(self._build_trade_deal_handler())
            self._trade_ctx.start()
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name=f"futu-account-poller-{self._config.account_id}",
                daemon=True,
            )
            self._poll_thread.start()
            self._poll_account()
            self._poll_positions()

    def close(self) -> None:
        with self._lock:
            self._poll_stop.set()
            if self._poll_thread is not None and self._poll_thread.is_alive():
                self._poll_thread.join(timeout=3.0)
            self._poll_thread = None

            trade_ctx = self._trade_ctx
            self._trade_ctx = None
            if trade_ctx is not None:
                try:
                    trade_ctx.close()
                except Exception as exc:
                    self._event_sink.on_broker_message(
                        logging.WARNING,
                        f"account={self._config.account_id} trade context close failed: {exc}",
                    )

    def _build_trade_order_handler(self):
        futu = self._futu
        broker = self

        class TradeOrderHandler(futu["TradeOrderHandlerBase"]):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code != futu["RET_OK"]:
                    broker._event_sink.on_broker_message(
                        logging.ERROR,
                        f"account={broker._config.account_id} order push error: {content}",
                    )
                    return ret_code, content
                if not content.empty:
                    row = content.iloc[0]
                    broker._event_sink.on_broker_message(
                        logging.INFO,
                        "ORDER_PUSH "
                        f"account={broker._config.account_id} code={row.get('code')} status={row.get('order_status')} "
                        f"dealt_qty={row.get('dealt_qty')} avg_price={row.get('dealt_avg_price')} side={row.get('trd_side')}",
                    )
                return ret_code, content

        return TradeOrderHandler()

    def _build_trade_deal_handler(self):
        futu = self._futu
        broker = self

        class TradeDealHandler(futu["TradeDealHandlerBase"]):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code != futu["RET_OK"]:
                    broker._event_sink.on_broker_message(
                        logging.ERROR,
                        f"account={broker._config.account_id} deal push error: {content}",
                    )
                    return ret_code, content
                if not content.empty:
                    row = content.iloc[0]
                    broker._event_sink.on_broker_message(
                        logging.INFO,
                        "DEAL_PUSH "
                        f"account={broker._config.account_id} code={row.get('code')} qty={row.get('qty')} "
                        f"price={row.get('price')} side={row.get('trd_side')}",
                    )
                return ret_code, content

        return TradeDealHandler()

    def _poll_loop(self) -> None:
        next_account_poll = 0.0
        next_position_poll = 0.0
        while not self._poll_stop.wait(0.5):
            now = time.monotonic()
            if now >= next_account_poll:
                self._poll_account()
                next_account_poll = now + self._config.broker.account_poll_interval_seconds
            if now >= next_position_poll:
                self._poll_positions()
                next_position_poll = now + self._config.broker.position_poll_interval_seconds

    def _poll_account(self) -> None:
        with self._lock:
            if self._trade_ctx is None or self._futu is None:
                return
            ret, data = self._trade_ctx.accinfo_query(
                trd_env=self._resolve_trade_env(),
                acc_index=self._config.broker.account_index,
                currency=self._futu["Currency"].USD,
            )
        if ret != self._futu["RET_OK"]:
            self._event_sink.on_broker_message(
                logging.WARNING,
                f"account={self._config.account_id} accinfo_query failed: {data}",
            )
            return
        if data.empty:
            return
        row = data.iloc[0]
        snapshot = AccountSnapshot(
            timestamp=pd.Timestamp.utcnow(),
            total_assets=_coerce_optional_float(row.get("total_assets")),
            cash=_coerce_optional_float(row.get("cash")),
            available_funds=_coerce_optional_float(row.get("available_funds")),
            buying_power=_coerce_optional_float(row.get("power")),
            currency=_coerce_optional_str(row.get("currency")) or "USD",
            raw=row.to_dict(),
        )
        self._event_sink.on_account(self._config.account_id, snapshot)

    def _poll_positions(self) -> None:
        with self._lock:
            if self._trade_ctx is None or self._futu is None:
                return
            ret, data = self._trade_ctx.position_list_query(
                trd_env=self._resolve_trade_env(),
                acc_index=self._config.broker.account_index,
                refresh_cache=True,
            )
        if ret != self._futu["RET_OK"]:
            self._event_sink.on_broker_message(
                logging.WARNING,
                f"account={self._config.account_id} position_list_query failed: {data}",
            )
            return
        positions: dict[str, PositionSnapshot] = {}
        for row in data.itertuples(index=False):
            positions[str(row.code)] = PositionSnapshot(
                code=str(row.code),
                qty=int(_coerce_optional_float(row.qty) or 0),
                can_sell_qty=int(_coerce_optional_float(row.can_sell_qty) or 0),
                average_cost=_coerce_optional_float(row.average_cost),
                market_val=_coerce_optional_float(row.market_val),
                unrealized_pl=_coerce_optional_float(row.unrealized_pl),
                realized_pl=_coerce_optional_float(row.realized_pl),
                currency=_coerce_optional_str(row.currency) or "USD",
                raw=row._asdict(),
            )
        self._event_sink.on_positions(self._config.account_id, positions)

    def _resolve_trade_env(self):
        if self._config.broker.trade_env == "SIMULATE":
            return self._futu["TrdEnv"].SIMULATE
        return self._futu["TrdEnv"].REAL


def _load_futu_api() -> dict[str, Any]:
    runtime_home = Path.cwd() / ".futu_runtime"
    runtime_home.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(runtime_home)
    from futu import (
        Currency,
        CurKlineHandlerBase,
        KLType,
        OpenQuoteContext,
        OpenSecTradeContext,
        RET_OK,
        StockQuoteHandlerBase,
        SubType,
        TradeDealHandlerBase,
        TradeOrderHandlerBase,
        TrdEnv,
        TrdMarket,
    )

    return {
        "Currency": Currency,
        "CurKlineHandlerBase": CurKlineHandlerBase,
        "KLType": KLType,
        "OpenQuoteContext": OpenQuoteContext,
        "OpenSecTradeContext": OpenSecTradeContext,
        "RET_OK": RET_OK,
        "StockQuoteHandlerBase": StockQuoteHandlerBase,
        "SubType": SubType,
        "TradeDealHandlerBase": TradeDealHandlerBase,
        "TradeOrderHandlerBase": TradeOrderHandlerBase,
        "TrdEnv": TrdEnv,
        "TrdMarket": TrdMarket,
    }


def _coerce_optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        normalized = value.strip().upper()
        if not normalized or normalized == "N/A":
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_str(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    normalized = str(value).strip()
    if not normalized or normalized.upper() == "N/A":
        return None
    return normalized


def create_quote_broker_client(
    config: RealtimeQuoteBrokerConfig,
    event_sink: QuoteBrokerEventSink,
    logger: logging.Logger,
) -> QuoteBrokerClient:
    if config.type == "futu":
        return FutuRealtimeQuoteClient(config, event_sink, logger)
    if config.type == "mock":
        return MockRealtimeQuoteClient(config, event_sink, logger)
    raise ValueError(f"unsupported broker type: {config.type}")


def create_daily_history_provider(
    config: HistoryBrokerConfig,
    logger: logging.Logger,
) -> DailyHistoryProvider:
    if config.type == "futu":
        return LocalDataDailyHistoryProvider(config, logger)
    raise ValueError(f"unsupported broker type: {config.type}")


def create_trade_account_client(
    config: TradeAccountConfig,
    event_sink: TradeAccountEventSink,
    logger: logging.Logger,
) -> TradeAccountClient:
    if config.broker.type == "futu":
        return FutuTradeAccountClient(config, event_sink, logger)
    raise ValueError(f"unsupported broker type: {config.broker.type}")
