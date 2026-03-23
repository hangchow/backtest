from __future__ import annotations

from datetime import date, datetime
import logging
from pathlib import Path
from typing import Callable, Iterable, Mapping

import pandas as pd

from ..config import DEFAULT_MARKET, HistoryBrokerConfig
from .base import DailyHistoryProvider
from .common import CSV_COLUMNS, HISTORY_COLUMNS, _default_now_provider_for_market


class LocalDataDailyHistoryProvider(DailyHistoryProvider):
    """只从本地目录读取 warm-up 日线，不回源任何外部服务。"""

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
        self._now_provider = now_provider or _default_now_provider_for_market(DEFAULT_MARKET)

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
        from .common import _expected_latest_trade_date_for_market

        return _expected_latest_trade_date_for_market(DEFAULT_MARKET, self._now_provider())

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
