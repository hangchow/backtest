from __future__ import annotations

from datetime import datetime, timedelta
import logging
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.error import HTTPError

import pandas as pd

from ..config import DEFAULT_MARKET, HistoryBrokerConfig
from .common import CSV_COLUMNS, HISTORY_COLUMNS, _market_calendar
from .local import LocalDataDailyHistoryProvider


class CachedRemoteDailyHistoryProvider(LocalDataDailyHistoryProvider):
    """先读本地缓存，不足时再回源远端的 warm-up provider 基类。"""

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
        try:
            daily = self._local_cache.get_daily_history_frame(code)
        except FileNotFoundError:
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
        self._local_cache.set_history_frame("day", code, daily)

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
        calendar = _market_calendar(DEFAULT_MARKET)
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
