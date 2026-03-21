from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, time as datetime_time, timedelta
from functools import lru_cache
from urllib.error import HTTPError
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Protocol
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from .config import HistoryBrokerConfig, RealtimeQuoteBrokerConfig, TradeAccountConfig
from .models import AccountSnapshot, PositionSnapshot
from .quote_brokers.base import QuoteBrokerClient, QuoteBrokerEventSink
from .quote_brokers.futu import FutuRealtimeQuoteClient, _load_futu_api
from .quote_brokers.mock import MockRealtimeQuoteClient


HISTORY_COLUMNS = ["code", "time_key", "open", "close", "high", "low", "volume"]
CSV_COLUMNS = ["time_key", "open", "close", "high", "low", "volume"]
NEW_YORK = ZoneInfo("America/New_York")
HONG_KONG = ZoneInfo("Asia/Hong_Kong")
US_MARKET_CLOSE = datetime_time(16, 0)
HK_MARKET_CLOSE = datetime_time(16, 0)
MARKET_SESSIONS: dict[str, tuple[ZoneInfo, datetime_time]] = {
    "US": (NEW_YORK, US_MARKET_CLOSE),
    "HK": (HONG_KONG, HK_MARKET_CLOSE),
}
MARKET_CALENDAR_NAMES: dict[str, str] = {
    "US": "XNYS",
    "HK": "XHKG",
}
MARKET_DAILY_BAR_READY_DELAYS: dict[str, timedelta] = {
    "US": timedelta(hours=2),
    "HK": timedelta(hours=2),
}


def _market_session(market: str | None) -> tuple[ZoneInfo, datetime_time] | None:
    normalized_market = (market or "US").strip().upper()
    return MARKET_SESSIONS.get(normalized_market)


def _default_now_provider_for_market(market: str | None) -> Callable[[], datetime]:
    session = _market_session(market)
    timezone = session[0] if session is not None else NEW_YORK
    return lambda: datetime.now(tz=timezone)


@lru_cache(maxsize=None)
def _market_calendar(market: str | None):
    normalized_market = (market or "US").strip().upper()
    calendar_name = MARKET_CALENDAR_NAMES.get(normalized_market)
    if calendar_name is None:
        return None
    return xcals.get_calendar(calendar_name)


def _expected_latest_trade_date_for_market(market: str | None, now: datetime) -> date | None:
    session = _market_session(market)
    if session is None:
        return None
    timezone, market_close = session
    calendar = _market_calendar(market)
    if calendar is None:
        return None
    current = now
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone)
    current = current.astimezone(timezone)
    current_session_label = pd.Timestamp(current.date())
    ready_delay = MARKET_DAILY_BAR_READY_DELAYS.get((market or "US").strip().upper(), timedelta())
    if calendar.is_session(current_session_label):
        current_session_close = calendar.session_close(current_session_label).tz_convert(timezone)
        if current >= current_session_close + ready_delay:
            return current.date()
        return pd.Timestamp(calendar.previous_session(current_session_label)).date()
    return pd.Timestamp(calendar.date_to_session(current_session_label, direction="previous")).date()


class TradeAccountEventSink(Protocol):
    def on_account(self, account_id: str, snapshot: AccountSnapshot) -> None:
        raise NotImplementedError

    def on_positions(self, account_id: str, positions: dict[str, PositionSnapshot]) -> None:
        raise NotImplementedError

    def on_broker_message(self, level: int, message: str) -> None:
        raise NotImplementedError


class DailyHistoryProvider(ABC):
    @abstractmethod
    def fetch_daily_histories(
        self,
        codes: Iterable[str],
        daily_warmup_bars: Mapping[str, int],
    ) -> dict[str, pd.DataFrame]:
        """为股票池拉取 warm-up 所需的日线窗口。"""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class TradeAccountClient(ABC):
    @abstractmethod
    def connect(self) -> None:
        """建立账户连接，并开始同步账户资金和持仓状态。"""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class LocalDataDailyHistoryProvider(DailyHistoryProvider):
    def __init__(
        self,
        config: HistoryBrokerConfig,
        logger: logging.Logger,
        *,
        kline_day_root: Path | str = "kline_day",
        daily_data_root: Path | str | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._logger = logger
        if daily_data_root is not None:
            kline_day_root = daily_data_root
        self._kline_day_root = Path(kline_day_root)
        self._now_provider = now_provider or _default_now_provider_for_market(config.market)

    def fetch_daily_histories(
        self,
        codes: Iterable[str],
        daily_warmup_bars: Mapping[str, int],
    ) -> dict[str, pd.DataFrame]:
        """从本地 kline_day 目录读取 warm-up 所需日线窗口。"""
        normalized_codes = sorted({str(code).strip().upper() for code in codes if str(code).strip()})
        histories: dict[str, pd.DataFrame] = {}

        for code in normalized_codes:
            bars = min(max(int(daily_warmup_bars.get(code, 1)), 1), 1000)
            daily_history = self._load_daily_from_kline_day(code, bars)
            if daily_history is None or daily_history.empty:
                self._logger.error("warm-up daily data unavailable code=%s", code)
                histories[code] = pd.DataFrame(columns=HISTORY_COLUMNS)
                continue
            histories[code] = daily_history

        return histories

    def close(self) -> None:
        return None

    def _load_daily_from_kline_day(self, code: str, bars: int) -> pd.DataFrame | None:
        code_dir = self._kline_day_root / code
        daily = self._load_local_csv_history(code_dir, code, frame_type="daily", dedupe_error=True)
        if daily is None:
            return None
        result = daily.tail(bars).reset_index(drop=True)
        self._logger.info("warm-up loaded from kline_day code=%s rows=%d dir=%s", code, len(result), code_dir)
        return result

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
            frames.append(frame[HISTORY_COLUMNS])

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


    def _latest_trade_date(self, history: pd.DataFrame | None) -> date | None:
        if history is None or history.empty or "time_key" not in history.columns:
            return None
        timestamps = pd.to_datetime(history["time_key"], errors="coerce")
        if timestamps.isna().all():
            return None
        return timestamps.max().date()

    def _expected_latest_trade_date(self) -> date | None:
        return _expected_latest_trade_date_for_market(self._config.market, self._now_provider())

    def _write_csv_payload(self, file_path: Path, payload: pd.DataFrame) -> str | None:
        existed = file_path.exists()
        if not self._should_write_csv_payload(file_path, payload):
            return None
        payload.to_csv(file_path, index=False)
        return "updated" if existed else "created"

    def _should_write_csv_payload(self, file_path: Path, payload: pd.DataFrame) -> bool:
        if not file_path.exists():
            return True
        try:
            existing = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            existing = pd.DataFrame(columns=CSV_COLUMNS)
        normalized_existing = self._normalize_csv_payload(existing)
        normalized_payload = self._normalize_csv_payload(payload)
        return not normalized_existing.equals(normalized_payload)

    def _normalize_csv_payload(self, frame: pd.DataFrame) -> pd.DataFrame:
        normalized = frame.copy()
        for column in CSV_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = ""
        normalized = normalized[CSV_COLUMNS].reset_index(drop=True).fillna("")
        for column in CSV_COLUMNS:
            normalized[column] = normalized[column].astype(str)
        return normalized


class CachedRemoteDailyHistoryProvider(LocalDataDailyHistoryProvider):
    def __init__(
        self,
        config: HistoryBrokerConfig,
        logger: logging.Logger,
        *,
        kline_day_root: Path | str = ".kline_day",
        remote_daily_fetcher: Callable[[str, int], pd.DataFrame] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(
            config,
            logger,
            kline_day_root=kline_day_root,
            now_provider=now_provider,
        )
        self._remote_daily_fetcher = remote_daily_fetcher

    def fetch_daily_histories(
        self,
        codes: Iterable[str],
        daily_warmup_bars: Mapping[str, int],
    ) -> dict[str, pd.DataFrame]:
        """优先复用本地缓存，不足时回源远端补齐 warm-up 日线。"""
        normalized_codes = sorted({str(code).strip().upper() for code in codes if str(code).strip()})
        histories: dict[str, pd.DataFrame] = {}

        for code in normalized_codes:
            bars = min(max(int(daily_warmup_bars.get(code, 1)), 1), 1000)
            full_daily_history = self._load_full_daily_from_kline_day(code)
            daily_history = self._tail_daily_history(full_daily_history, bars)
            if self._should_refresh_remote_daily(daily_history, bars):
                try:
                    remote_daily = self._fetch_remote_daily_history(code, bars)
                except HTTPError as exc:
                    try:
                        if exc.code == 429 and self._can_use_stale_daily_history(daily_history, bars):
                            self._logger.warning(
                                "warm-up using stale local daily history due to remote rate limit code=%s bars=%d expected_latest=%s daily_latest=%s stale_business_days=%d",
                                code,
                                bars,
                                self._expected_latest_trade_date(),
                                self._latest_trade_date(daily_history),
                                self._daily_history_business_day_lag(daily_history) or 0,
                            )
                            histories[code] = daily_history.tail(bars).reset_index(drop=True)
                            continue
                        self._logger.error(
                            "warm-up remote daily fetch failed code=%s bars=%d expected_latest=%s daily_latest=%s error=%s",
                            code,
                            bars,
                            self._expected_latest_trade_date(),
                            self._latest_trade_date(daily_history),
                            exc,
                        )
                        histories[code] = pd.DataFrame(columns=HISTORY_COLUMNS)
                        continue
                    finally:
                        exc.close()
                except Exception as exc:
                    self._logger.exception(
                        "warm-up remote daily fetch failed code=%s bars=%d expected_latest=%s daily_latest=%s error=%s",
                        code,
                        bars,
                        self._expected_latest_trade_date(),
                        self._latest_trade_date(daily_history),
                        exc,
                    )
                    histories[code] = pd.DataFrame(columns=HISTORY_COLUMNS)
                    continue
                if remote_daily is None or remote_daily.empty:
                    self._logger.error(
                        "warm-up remote daily fetch returned no rows code=%s expected_latest=%s daily_latest=%s",
                        code,
                        self._expected_latest_trade_date(),
                        self._latest_trade_date(daily_history),
                    )
                    histories[code] = pd.DataFrame(columns=HISTORY_COLUMNS)
                    continue
                else:
                    merged_daily = self._merge_daily_frames(full_daily_history, remote_daily)
                    exact_daily = self._tail_daily_history(merged_daily, bars)
                    if exact_daily is None or exact_daily.empty:
                        self._logger.error("warm-up daily history unavailable after remote fetch code=%s", code)
                        histories[code] = pd.DataFrame(columns=HISTORY_COLUMNS)
                        continue
                    if not self._daily_history_meets_latest_requirement(exact_daily):
                        self._logger.error(
                            "warm-up daily history remains stale after remote fetch code=%s expected_latest=%s daily_latest=%s",
                            code,
                            self._expected_latest_trade_date(),
                            self._latest_trade_date(exact_daily),
                        )
                        histories[code] = pd.DataFrame(columns=HISTORY_COLUMNS)
                        continue
                    if len(exact_daily) < bars:
                        self._logger.error(
                            "warm-up daily history insufficient after remote fetch code=%s required_bars=%d available_bars=%d",
                            code,
                            bars,
                            len(exact_daily),
                        )
                    self._rewrite_kline_day_weekly_csv(code, exact_daily)
                    daily_history = exact_daily
            elif full_daily_history is not None and daily_history is not None and len(full_daily_history) != len(daily_history):
                self._rewrite_kline_day_weekly_csv(code, daily_history)

            if daily_history is None or daily_history.empty:
                self._logger.error("warm-up daily data unavailable code=%s", code)
                histories[code] = pd.DataFrame(columns=HISTORY_COLUMNS)
                continue

            histories[code] = daily_history.tail(bars).reset_index(drop=True)

        return histories

    def _load_full_daily_from_kline_day(self, code: str) -> pd.DataFrame | None:
        code_dir = self._kline_day_root / code
        daily = self._load_local_csv_history(code_dir, code, frame_type="daily", dedupe_error=True)
        if daily is None:
            return None
        self._logger.info("warm-up loaded from kline_day code=%s rows=%d dir=%s", code, len(daily), code_dir)
        return daily

    def _tail_daily_history(self, daily_history: pd.DataFrame | None, bars: int) -> pd.DataFrame | None:
        if daily_history is None or daily_history.empty:
            return daily_history
        return daily_history.tail(bars).reset_index(drop=True)

    def _merge_daily_frames(self, cached: pd.DataFrame | None, remote: pd.DataFrame | None) -> pd.DataFrame | None:
        frames = [frame for frame in (cached, remote) if frame is not None and not frame.empty]
        if not frames:
            return None
        merged = pd.concat(frames, ignore_index=True)
        merged = merged.copy()
        merged["time_key"] = pd.to_datetime(merged["time_key"])
        merged = merged.sort_values("time_key").drop_duplicates(subset=["time_key"], keep="last").reset_index(drop=True)
        return merged

    def _rewrite_kline_day_weekly_csv(self, code: str, daily: pd.DataFrame | None) -> None:
        if daily is None:
            return
        code_dir = self._kline_day_root / code
        code_dir.mkdir(parents=True, exist_ok=True)
        self._rewrite_weekly_csv_exact(code_dir, code, daily)

    def _should_refresh_remote_daily(self, daily_history: pd.DataFrame | None, bars: int) -> bool:
        expected_latest_trade_date = self._expected_latest_trade_date()
        daily_latest_trade_date = self._latest_trade_date(daily_history)
        if daily_history is None or daily_history.empty:
            return True
        if len(daily_history) < bars:
            return True
        if expected_latest_trade_date is not None and daily_latest_trade_date is not None and daily_latest_trade_date < expected_latest_trade_date:
            self._logger.info(
                "warm-up daily cache stale code=%s daily_latest=%s expected_latest=%s",
                daily_history["code"].iloc[-1] if "code" in daily_history.columns and not daily_history.empty else "N/A",
                daily_latest_trade_date,
                expected_latest_trade_date,
            )
            return True
        return False

    def _daily_history_meets_latest_requirement(self, daily_history: pd.DataFrame | None) -> bool:
        expected_latest_trade_date = self._expected_latest_trade_date()
        if expected_latest_trade_date is None:
            return True
        daily_latest_trade_date = self._latest_trade_date(daily_history)
        return daily_latest_trade_date is not None and daily_latest_trade_date >= expected_latest_trade_date

    def _daily_history_business_day_lag(self, daily_history: pd.DataFrame | None) -> int | None:
        expected_latest_trade_date = self._expected_latest_trade_date()
        daily_latest_trade_date = self._latest_trade_date(daily_history)
        if expected_latest_trade_date is None or daily_latest_trade_date is None:
            return None
        if daily_latest_trade_date >= expected_latest_trade_date:
            return 0
        calendar = _market_calendar(self._config.market)
        if calendar is None:
            return None
        lag_sessions = calendar.sessions_in_range(
            pd.Timestamp(daily_latest_trade_date + timedelta(days=1)),
            pd.Timestamp(expected_latest_trade_date),
        )
        return len(lag_sessions)

    def _can_use_stale_daily_history(self, daily_history: pd.DataFrame | None, bars: int) -> bool:
        if daily_history is None or daily_history.empty:
            return False
        if len(daily_history) < bars:
            return False
        lag = self._daily_history_business_day_lag(daily_history)
        return lag is not None and lag <= 1

    def _fetch_remote_daily_history(self, code: str, bars: int) -> pd.DataFrame:
        raise NotImplementedError

    def _rewrite_weekly_csv_exact(self, code_dir: Path, code: str, frame: pd.DataFrame) -> None:
        desired_paths: set[Path] = set()
        if frame is not None and not frame.empty:
            data = frame.copy()
            data["time_key"] = pd.to_datetime(data["time_key"])
            data = data.sort_values("time_key").drop_duplicates(subset=["time_key"], keep="last").reset_index(drop=True)
            data["week_start"] = data["time_key"].dt.normalize() - pd.to_timedelta(data["time_key"].dt.weekday, unit="D")
            for week_start, weekly in data.groupby("week_start", sort=True):
                week_start = pd.Timestamp(week_start)
                file_path = code_dir / f"{code}_{week_start.date().isoformat()}.csv"
                desired_paths.add(file_path)
                payload = weekly[CSV_COLUMNS].copy()
                payload["time_key"] = payload["time_key"].dt.strftime("%Y-%m-%d %H:%M:%S")
                action = self._write_csv_payload(file_path, payload)
                if action is not None:
                    self._logger.info("warm-up cache file %s path=%s rows=%d", action, file_path, len(payload))
        for existing in sorted(code_dir.glob("*.csv")):
            if existing not in desired_paths:
                existing.unlink()
                self._logger.info("warm-up cache file removed path=%s", existing)


class PolygonCacheDailyHistoryProvider(CachedRemoteDailyHistoryProvider):
    def _fetch_remote_daily_history(self, code: str, bars: int) -> pd.DataFrame:
        if self._remote_daily_fetcher is not None:
            return self._remote_daily_fetcher(code, bars)

        api_key = os.environ.get("POLYGON_API_KEY", "").strip()
        if not api_key:
            self._logger.error("POLYGON_API_KEY is not set; cannot fetch remote daily history for %s", code)
            return pd.DataFrame(columns=HISTORY_COLUMNS)

        ticker = code.split(".", 1)[1] if "." in code else code
        end_date = self._expected_latest_trade_date() or self._now_provider().astimezone(NEW_YORK).date()
        window_days = self._estimate_polygon_daily_window_days(bars)
        max_window_days = 3650
        results: list[dict[str, object]] = []
        previous_result_count = -1
        while window_days <= max_window_days:
            start_date = end_date - timedelta(days=window_days)
            results = self._request_polygon_daily_results(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key,
                code=code,
                bars=bars,
            )
            if len(results) >= bars or window_days == max_window_days:
                break
            if len(results) <= previous_result_count:
                self._logger.info(
                    "warm-up polygon daily fetch stalled code=%s target_bars=%d returned_rows=%d window_days=%d",
                    code,
                    bars,
                    len(results),
                    window_days,
                )
                break
            previous_result_count = len(results)
            window_days = min(window_days + max(14, bars // 3), max_window_days)
        if not results:
            return pd.DataFrame(columns=HISTORY_COLUMNS)

        rows: list[dict[str, object]] = []
        for item in results:
            trade_date = datetime.fromtimestamp(item["t"] / 1000, tz=NEW_YORK).date()
            rows.append(
                {
                    "code": code,
                    "time_key": pd.Timestamp(trade_date),
                    "open": item["o"],
                    "close": item["c"],
                    "high": item["h"],
                    "low": item["l"],
                    "volume": item["v"],
                }
            )
        return pd.DataFrame(rows, columns=HISTORY_COLUMNS)

    def _estimate_polygon_daily_window_days(self, bars: int) -> int:
        trading_days_as_calendar = max((bars * 7 + 4) // 5, bars)
        # Add a small buffer for market holidays without expanding into a multi-year fetch by default.
        return max(trading_days_as_calendar + 14, 30)

    def _request_polygon_daily_results(
        self,
        *,
        ticker: str,
        start_date: date,
        end_date: date,
        api_key: str,
        code: str,
        bars: int,
    ) -> list[dict[str, object]]:
        query = urlencode(
            {
                "adjusted": "true",
                "sort": "asc",
                "limit": 50000,
                "apiKey": api_key,
            }
        )
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start_date.isoformat()}/{end_date.isoformat()}?{query}"
        max_attempts = 3
        payload: dict[str, Any] | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                with urlopen(url, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                try:
                    if exc.code != 429 or attempt >= max_attempts:
                        raise
                    retry_after = self._polygon_retry_delay_seconds(exc, attempt)
                    self._logger.warning(
                        "warm-up polygon daily fetch rate limited code=%s target_bars=%d start=%s end=%s attempt=%d/%d retry_after=%.2fs",
                        code,
                        bars,
                        start_date,
                        end_date,
                        attempt,
                        max_attempts,
                        retry_after,
                    )
                    time.sleep(retry_after)
                finally:
                    exc.close()
        if payload is None:
            return []
        status = payload.get("status")
        if status not in {"OK", "DELAYED"}:
            detail = payload.get("error") or payload.get("message") or payload
            raise RuntimeError(f"polygon daily fetch failed for {code}: {detail}")
        results = payload.get("results", [])
        self._logger.info(
            "warm-up polygon daily fetch code=%s target_bars=%d start=%s end=%s returned_rows=%d",
            code,
            bars,
            start_date,
            end_date,
            len(results),
        )
        return results

    def _polygon_retry_delay_seconds(self, exc: HTTPError, attempt: int) -> float:
        retry_after_raw = exc.headers.get("Retry-After") if exc.headers is not None else None
        if retry_after_raw:
            try:
                retry_after = float(retry_after_raw)
            except (TypeError, ValueError):
                retry_after = 0.0
            else:
                return max(0.5, min(retry_after, 5.0))
        return float(min(2**(attempt - 1), 5))


class FutuDailyHistoryProvider(CachedRemoteDailyHistoryProvider):
    def _fetch_remote_daily_history(self, code: str, bars: int) -> pd.DataFrame:
        if self._remote_daily_fetcher is not None:
            return self._remote_daily_fetcher(code, bars)

        futu = _load_futu_api()
        if not self._config.host or self._config.port is None:
            raise ValueError("futu history broker requires host and port")
        expected_latest_trade_date = self._expected_latest_trade_date()
        request_bars = min(bars + 1, 1000) if expected_latest_trade_date is not None else bars
        quote_ctx = futu["OpenQuoteContext"](host=self._config.host, port=self._config.port)
        try:
            ret, data = quote_ctx.get_cur_kline(code, request_bars, ktype=futu["KLType"].K_DAY)
        finally:
            quote_ctx.close()
        if ret != futu["RET_OK"]:
            self._logger.warning("get_cur_kline failed for %s: %s", code, data)
            return pd.DataFrame(columns=HISTORY_COLUMNS)

        history = data.copy()
        history["time_key"] = pd.to_datetime(history["time_key"])
        history = history.sort_values("time_key").drop_duplicates(subset=["time_key"], keep="last").reset_index(drop=True)
        history = history[HISTORY_COLUMNS]
        if expected_latest_trade_date is not None:
            trimmed = history.loc[history["time_key"].dt.date <= expected_latest_trade_date].reset_index(drop=True)
            if len(trimmed) != len(history):
                self._logger.info(
                    "trimmed in-progress futu daily bar code=%s expected_latest=%s returned_rows=%d kept_rows=%d",
                    code,
                    expected_latest_trade_date,
                    len(history),
                    len(trimmed),
                )
            history = trimmed
        return history.tail(bars).reset_index(drop=True)


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
        """连接 Futu 交易上下文，启动后台轮询并立即同步账户/持仓。"""
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
        """拉取账户资金快照并回调给事件接收方。"""
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
        """拉取当前持仓快照并回调给事件接收方。"""
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
    """按配置选择 realtime quote client 实现。"""
    if config.type == "futu":
        return FutuRealtimeQuoteClient(config, event_sink, logger)
    if config.type == "mock":
        return MockRealtimeQuoteClient(config, event_sink, logger)
    raise ValueError(f"unsupported broker type: {config.type}")


def create_daily_history_provider(
    config: HistoryBrokerConfig,
    logger: logging.Logger,
) -> DailyHistoryProvider:
    """按配置选择 warm-up 日线 provider 实现。"""
    if config.type == "polygon":
        return PolygonCacheDailyHistoryProvider(config, logger)
    if config.type == "futu":
        return FutuDailyHistoryProvider(config, logger)
    raise ValueError(f"unsupported broker type: {config.type}")


def create_trade_account_client(
    config: TradeAccountConfig,
    event_sink: TradeAccountEventSink,
    logger: logging.Logger,
) -> TradeAccountClient:
    """按配置选择交易账户 client 实现。"""
    if config.broker.type == "futu":
        return FutuTradeAccountClient(config, event_sink, logger)
    raise ValueError(f"unsupported broker type: {config.broker.type}")
