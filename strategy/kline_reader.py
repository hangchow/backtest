from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import perf_counter
from typing import Literal, Protocol

import pandas as pd


CSV_COLUMNS = ["time_key", "open", "close", "high", "low", "volume"]
HISTORY_COLUMNS = ["code", *CSV_COLUMNS]
FrameType = Literal["day", "minute"]


@dataclass(frozen=True)
class KlineReaderStatsSnapshot:
    total_load_seconds: float
    files_loaded: int
    load_operations: int


class KlineReader(Protocol):
    def snapshot(self) -> KlineReaderStatsSnapshot: ...

    def get_csv_frame(self, frame_type: FrameType, code: str) -> pd.DataFrame: ...

    def get_history_frame(self, frame_type: FrameType, code: str) -> pd.DataFrame: ...

    def get_csv_tail_frame(self, frame_type: FrameType, code: str, rows: int) -> pd.DataFrame: ...

    def get_history_tail_frame(self, frame_type: FrameType, code: str, rows: int) -> pd.DataFrame: ...

    def get_daily_csv_frame(self, code: str) -> pd.DataFrame: ...

    def get_minute_csv_frame(self, code: str) -> pd.DataFrame: ...

    def get_daily_history_frame(self, code: str) -> pd.DataFrame: ...

    def get_minute_history_frame(self, code: str) -> pd.DataFrame: ...

    def get_daily_csv_tail_frame(self, code: str, rows: int) -> pd.DataFrame: ...

    def get_minute_csv_tail_frame(self, code: str, rows: int) -> pd.DataFrame: ...

    def get_daily_history_tail_frame(self, code: str, rows: int) -> pd.DataFrame: ...

    def get_minute_history_tail_frame(self, code: str, rows: int) -> pd.DataFrame: ...


class MutableKlineReader(KlineReader, Protocol):
    def set_csv_frame(self, frame_type: FrameType, code: str, frame: pd.DataFrame) -> None: ...

    def set_history_frame(self, frame_type: FrameType, code: str, frame: pd.DataFrame) -> None: ...


class LocalKlineReader:
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
        self._total_load_seconds = 0.0
        self._files_loaded = 0
        self._load_operations = 0

    def snapshot(self) -> KlineReaderStatsSnapshot:
        return KlineReaderStatsSnapshot(
            total_load_seconds=self._total_load_seconds,
            files_loaded=self._files_loaded,
            load_operations=self._load_operations,
        )

    def get_csv_frame(self, frame_type: FrameType, code: str) -> pd.DataFrame:
        normalized_frame_type = self._normalize_frame_type(frame_type)
        normalized_code = self._normalize_code(code)
        csv_files = self._list_csv_files(normalized_frame_type, normalized_code)
        frames: list[pd.DataFrame] = []
        for path in csv_files:
            frame = self._get_or_load_file_frame(normalized_frame_type, normalized_code, path)
            if frame is not None:
                frames.append(frame)
        if not frames:
            code_dir = self._root_for_frame_type(normalized_frame_type) / normalized_code
            raise FileNotFoundError(f"No readable CSV payload found in {code_dir}")
        return self._merge_csv_frames(normalized_frame_type, normalized_code, frames)

    def get_history_frame(self, frame_type: FrameType, code: str) -> pd.DataFrame:
        normalized_code = self._normalize_code(code)
        frame = self.get_csv_frame(frame_type, normalized_code)
        result = frame.copy()
        result.insert(0, "code", normalized_code)
        return result.loc[:, HISTORY_COLUMNS]

    def get_csv_tail_frame(self, frame_type: FrameType, code: str, rows: int) -> pd.DataFrame:
        normalized_frame_type = self._normalize_frame_type(frame_type)
        normalized_code = self._normalize_code(code)
        requested_rows = int(rows)
        if requested_rows <= 0:
            raise ValueError("rows must be positive")
        csv_files = self._list_csv_files(normalized_frame_type, normalized_code)
        selected_frames: list[pd.DataFrame] = []
        selected_row_count = 0
        for path in reversed(csv_files):
            frame = self._get_or_load_file_frame(normalized_frame_type, normalized_code, path)
            if frame is None:
                continue
            selected_frames.append(frame)
            selected_row_count += len(frame)
            if selected_row_count < requested_rows:
                continue
            merged = self._merge_csv_frames(
                normalized_frame_type,
                normalized_code,
                list(reversed(selected_frames)),
                log_duplicates=False,
            )
            if len(merged) >= requested_rows:
                merged = self._merge_csv_frames(normalized_frame_type, normalized_code, list(reversed(selected_frames)))
                return merged.tail(requested_rows).reset_index(drop=True)
        if not selected_frames:
            code_dir = self._root_for_frame_type(normalized_frame_type) / normalized_code
            raise FileNotFoundError(f"No readable CSV payload found in {code_dir}")
        merged = self._merge_csv_frames(normalized_frame_type, normalized_code, list(reversed(selected_frames)))
        return merged.tail(requested_rows).reset_index(drop=True)

    def get_history_tail_frame(self, frame_type: FrameType, code: str, rows: int) -> pd.DataFrame:
        normalized_code = self._normalize_code(code)
        frame = self.get_csv_tail_frame(frame_type, normalized_code, rows)
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

    def get_daily_csv_tail_frame(self, code: str, rows: int) -> pd.DataFrame:
        return self.get_csv_tail_frame("day", code, rows)

    def get_minute_csv_tail_frame(self, code: str, rows: int) -> pd.DataFrame:
        return self.get_csv_tail_frame("minute", code, rows)

    def get_daily_history_tail_frame(self, code: str, rows: int) -> pd.DataFrame:
        return self.get_history_tail_frame("day", code, rows)

    def get_minute_history_tail_frame(self, code: str, rows: int) -> pd.DataFrame:
        return self.get_history_tail_frame("minute", code, rows)

    def _get_or_load_file_frame(self, frame_type: FrameType, code: str, path: Path) -> pd.DataFrame | None:
        return self._load_csv_frame_from_filesystem(frame_type, code, path)

    def _load_csv_frame_from_filesystem(self, frame_type: FrameType, code: str, path: Path) -> pd.DataFrame | None:
        started_at = perf_counter()
        required = set(CSV_COLUMNS)
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
            return None
        chunk = chunk.loc[:, CSV_COLUMNS].copy()
        chunk["time_key"] = pd.to_datetime(chunk["time_key"])
        elapsed = perf_counter() - started_at
        self._total_load_seconds += elapsed
        self._files_loaded += 1
        self._load_operations += 1
        return self._normalize_csv_frame(chunk, code=code)

    def _list_csv_files(self, frame_type: FrameType, code: str) -> list[Path]:
        code_dir = self._root_for_frame_type(frame_type) / code
        if not code_dir.is_dir():
            raise FileNotFoundError(f"Missing {frame_type} directory for {code}: {code_dir}")
        csv_files = sorted(code_dir.glob("*.csv"))
        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in {code_dir}")
        return csv_files

    def _merge_csv_frames(
        self,
        frame_type: FrameType,
        code: str,
        frames: list[pd.DataFrame],
        *,
        log_duplicates: bool = True,
    ) -> pd.DataFrame:
        merged = pd.concat(frames, ignore_index=True)
        duplicate_time_keys = merged.loc[merged.duplicated(subset=["time_key"], keep=False), "time_key"].drop_duplicates()
        if log_duplicates and not duplicate_time_keys.empty and self._logger is not None:
            label = "daily" if frame_type == "day" else "minute"
            duplicates = ",".join(pd.to_datetime(duplicate_time_keys).dt.strftime("%Y-%m-%d %H:%M:%S").tolist())
            self._logger.error("duplicate %s time_key detected code=%s values=%s", label, code, duplicates)
        merged = (
            merged.sort_values("time_key")
            .drop_duplicates(subset=["time_key"], keep="last")
            .reset_index(drop=True)
        )
        return merged.loc[:, CSV_COLUMNS]

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

    def _split_frame_into_file_frames(
        self,
        frame_type: FrameType,
        code: str,
        frame: pd.DataFrame,
    ) -> list[tuple[Path, pd.DataFrame]]:
        if frame.empty:
            return []

        normalized = frame.copy()
        if frame_type == "day":
            normalized["bucket_start"] = normalized["time_key"].dt.normalize() - pd.to_timedelta(
                normalized["time_key"].dt.weekday,
                unit="D",
            )
        elif frame_type == "minute":
            normalized["bucket_start"] = normalized["time_key"].dt.normalize()
        else:
            raise ValueError(f"unsupported frame type: {frame_type}")

        code_dir = self._root_for_frame_type(frame_type) / code
        result: list[tuple[Path, pd.DataFrame]] = []
        for bucket_start, bucket in normalized.groupby("bucket_start", sort=True):
            file_path = code_dir / f"{code}_{pd.Timestamp(bucket_start).date().isoformat()}.csv"
            payload = bucket.loc[:, CSV_COLUMNS].reset_index(drop=True)
            result.append((file_path, payload))
        return result

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


__all__ = [
    "CSV_COLUMNS",
    "FrameType",
    "HISTORY_COLUMNS",
    "KlineReader",
    "KlineReaderStatsSnapshot",
    "LocalKlineReader",
    "MutableKlineReader",
]
