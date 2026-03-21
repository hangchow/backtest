from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta
from functools import lru_cache
import logging
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from ..config import HistoryBrokerConfig
from .base import DailyHistoryProvider


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
