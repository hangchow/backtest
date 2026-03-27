from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import perf_counter
from typing import Literal

import pandas as pd


CSV_COLUMNS = ["time_key", "open", "close", "high", "low", "volume"]
HISTORY_COLUMNS = ["code", *CSV_COLUMNS]
FrameType = Literal["day", "minute"]


@dataclass(frozen=True)
class CacheStatsSnapshot:
    total_load_seconds: float
    files_loaded: int
    load_operations: int
    current_bytes: int
    peak_bytes: int


class LocalKlineDataCache:
    def __init__(
        self,
        *,
        kline_day_root: Path | str = "kline_day",
        kline_minute_root: Path | str = "kline_minute",
        logger: logging.Logger | None = None,
    ) -> None:
        self._kline_day_root = Path(kline_day_root)
        self._kline_minute_root = Path(kline_minute_root)
        self._logger = logger
        self._frames: dict[tuple[FrameType, str], pd.DataFrame] = {}
        self._frame_bytes: dict[tuple[FrameType, str], int] = {}
        self._total_load_seconds = 0.0
        self._files_loaded = 0
        self._load_operations = 0
        self._current_bytes = 0
        self._peak_bytes = 0

    def snapshot(self) -> CacheStatsSnapshot:
        return CacheStatsSnapshot(
            total_load_seconds=self._total_load_seconds,
            files_loaded=self._files_loaded,
            load_operations=self._load_operations,
            current_bytes=self._current_bytes,
            peak_bytes=self._peak_bytes,
        )

    def get_csv_frame(self, frame_type: FrameType, code: str) -> pd.DataFrame:
        key = (self._normalize_frame_type(frame_type), self._normalize_code(code))
        frame = self._frames.get(key)
        if frame is not None:
            return frame
        frame = self._load_csv_frame_from_filesystem(*key)
        self._store_frame(key, frame)
        return frame

    def get_history_frame(self, frame_type: FrameType, code: str) -> pd.DataFrame:
        normalized_code = self._normalize_code(code)
        frame = self.get_csv_frame(frame_type, normalized_code)
        result = frame.copy()
        result.insert(0, "code", normalized_code)
        return result.loc[:, HISTORY_COLUMNS]

    def get_daily_csv_frame(self, code: str) -> pd.DataFrame:
        return self.get_csv_frame("day", code)

    def get_minute_csv_frame(self, code: str) -> pd.DataFrame:
        return self.get_csv_frame("minute", code)

    def get_daily_history_frame(self, code: str) -> pd.DataFrame:
        return self.get_history_frame("day", code)

    def get_minute_history_frame(self, code: str) -> pd.DataFrame:
        return self.get_history_frame("minute", code)

    def set_csv_frame(self, frame_type: FrameType, code: str, frame: pd.DataFrame) -> None:
        key = (self._normalize_frame_type(frame_type), self._normalize_code(code))
        normalized = self._normalize_csv_frame(frame, code=key[1])
        self._store_frame(key, normalized)

    def set_history_frame(self, frame_type: FrameType, code: str, frame: pd.DataFrame) -> None:
        normalized = frame.copy()
        if "code" in normalized.columns:
            normalized = normalized.drop(columns=["code"])
        self.set_csv_frame(frame_type, code, normalized)

    def _load_csv_frame_from_filesystem(self, frame_type: FrameType, code: str) -> pd.DataFrame:
        code_dir = self._root_for_frame_type(frame_type) / code
        if not code_dir.is_dir():
            raise FileNotFoundError(f"Missing {frame_type} directory for {code}: {code_dir}")

        csv_files = sorted(code_dir.glob("*.csv"))
        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in {code_dir}")

        started_at = perf_counter()
        frames: list[pd.DataFrame] = []
        required = set(CSV_COLUMNS)
        for path in csv_files:
            chunk = pd.read_csv(path, usecols=lambda column: column in required)
            if set(chunk.columns) != required:
                missing = ", ".join(sorted(required - set(chunk.columns)))
                if self._logger is not None:
                    self._logger.warning(
                        "local %s file missing columns code=%s path=%s missing=%s",
                        frame_type,
                        code,
                        path,
                        missing,
                    )
                continue
            chunk = chunk.loc[:, CSV_COLUMNS].copy()
            chunk["time_key"] = pd.to_datetime(chunk["time_key"])
            frames.append(chunk)

        if not frames:
            raise FileNotFoundError(f"No readable CSV payload found in {code_dir}")

        merged = pd.concat(frames, ignore_index=True)
        merged = (
            merged.sort_values("time_key")
            .drop_duplicates(subset=["time_key"], keep="last")
            .reset_index(drop=True)
        )

        elapsed = perf_counter() - started_at
        self._total_load_seconds += elapsed
        self._files_loaded += len(csv_files)
        self._load_operations += 1
        return merged.loc[:, CSV_COLUMNS]

    def _store_frame(self, key: tuple[FrameType, str], frame: pd.DataFrame) -> None:
        normalized = self._normalize_csv_frame(frame, code=key[1])
        next_bytes = self._frame_memory_bytes(normalized)
        previous_bytes = self._frame_bytes.get(key, 0)
        self._frames[key] = normalized
        self._frame_bytes[key] = next_bytes
        self._current_bytes += next_bytes - previous_bytes
        self._peak_bytes = max(self._peak_bytes, self._current_bytes)

    def _normalize_csv_frame(self, frame: pd.DataFrame, *, code: str) -> pd.DataFrame:
        if frame.empty:
            empty = pd.DataFrame(columns=CSV_COLUMNS)
            empty["time_key"] = pd.to_datetime(empty["time_key"])
            return empty

        normalized = frame.copy()
        missing = [column for column in CSV_COLUMNS if column not in normalized.columns]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"frame for {code} missing columns: {missing_text}")
        normalized = normalized.loc[:, CSV_COLUMNS]
        normalized["time_key"] = pd.to_datetime(normalized["time_key"])
        normalized = (
            normalized.sort_values("time_key")
            .drop_duplicates(subset=["time_key"], keep="last")
            .reset_index(drop=True)
        )
        return normalized

    def _root_for_frame_type(self, frame_type: FrameType) -> Path:
        if frame_type == "day":
            return self._kline_day_root
        if frame_type == "minute":
            return self._kline_minute_root
        raise ValueError(f"unsupported frame type: {frame_type}")

    def _normalize_code(self, code: str) -> str:
        normalized = str(code).strip().upper()
        if not normalized:
            raise ValueError("code must not be empty")
        return normalized

    def _normalize_frame_type(self, frame_type: FrameType) -> FrameType:
        normalized = str(frame_type).strip().lower()
        if normalized not in {"day", "minute"}:
            raise ValueError(f"unsupported frame type: {frame_type}")
        return normalized  # type: ignore[return-value]

    def _frame_memory_bytes(self, frame: pd.DataFrame) -> int:
        return int(frame.memory_usage(index=True, deep=True).sum())
