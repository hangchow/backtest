from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

import pandas as pd

from .kline_reader import FrameType, LocalKlineReader
from .memory_lru_cache import MemorySizedLruCache


DEFAULT_MAX_CACHE_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class CacheStatsSnapshot:
    total_load_seconds: float
    files_loaded: int
    load_operations: int
    current_bytes: int
    peak_bytes: int
    max_bytes: int
    cached_files: int
    hit_count: int
    miss_count: int
    eviction_count: int


class LocalKlineDataCache(LocalKlineReader):
    def __init__(
        self,
        *,
        kline_day_root: Path | str = "kline_day",
        kline_minute_root: Path | str = "kline_minute",
        max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES,
        enable_file_cache: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(
            kline_day_root=kline_day_root,
            kline_minute_root=kline_minute_root,
            logger=logger,
        )
        self._enable_file_cache = bool(enable_file_cache)
        self._max_cache_bytes = int(max_cache_bytes)
        self._file_cache: MemorySizedLruCache[tuple[FrameType, str, Path], pd.DataFrame] | None = None
        if self._enable_file_cache:
            self._file_cache = MemorySizedLruCache(
                max_bytes=self._max_cache_bytes,
                sizeof=self._frame_memory_bytes,
            )

    def snapshot(self) -> CacheStatsSnapshot:
        reader_snapshot = super().snapshot()
        if self._file_cache is None:
            return CacheStatsSnapshot(
                total_load_seconds=reader_snapshot.total_load_seconds,
                files_loaded=reader_snapshot.files_loaded,
                load_operations=reader_snapshot.load_operations,
                current_bytes=0,
                peak_bytes=0,
                max_bytes=0,
                cached_files=0,
                hit_count=0,
                miss_count=0,
                eviction_count=0,
            )

        cache_snapshot = self._file_cache.snapshot()
        return CacheStatsSnapshot(
            total_load_seconds=reader_snapshot.total_load_seconds,
            files_loaded=reader_snapshot.files_loaded,
            load_operations=reader_snapshot.load_operations,
            current_bytes=cache_snapshot.current_bytes,
            peak_bytes=cache_snapshot.peak_bytes,
            max_bytes=cache_snapshot.max_bytes,
            cached_files=cache_snapshot.item_count,
            hit_count=cache_snapshot.hit_count,
            miss_count=cache_snapshot.miss_count,
            eviction_count=cache_snapshot.eviction_count,
        )

    def set_csv_frame(self, frame_type: FrameType, code: str, frame: pd.DataFrame) -> None:
        if self._file_cache is None:
            raise RuntimeError("set_csv_frame requires enable_file_cache=True")
        normalized_frame_type = self._normalize_frame_type(frame_type)
        normalized_code = self._normalize_code(code)
        normalized = self._normalize_csv_frame(frame, code=normalized_code)
        payloads = self._split_frame_into_file_frames(normalized_frame_type, normalized_code, normalized)
        self._validate_write_payloads(normalized_frame_type, normalized_code, payloads)
        self._evict_code_files(normalized_frame_type, normalized_code)
        for path, payload in payloads:
            inserted = self._file_cache.put((normalized_frame_type, normalized_code, path), payload)
            if not inserted:
                raise RuntimeError(
                    f"cache insert unexpectedly failed after validation frame_type={normalized_frame_type} code={normalized_code} path={path}"
                )

    def set_history_frame(self, frame_type: FrameType, code: str, frame: pd.DataFrame) -> None:
        normalized = frame.copy()
        if "code" in normalized.columns:
            normalized = normalized.drop(columns=["code"])
        self.set_csv_frame(frame_type, code, normalized)

    def _get_or_load_file_frame(self, frame_type: FrameType, code: str, path: Path) -> pd.DataFrame | None:
        if self._file_cache is None:
            return super()._get_or_load_file_frame(frame_type, code, path)
        key = (frame_type, code, path)
        cached = self._file_cache.get(key)
        if cached is not None:
            return cached
        loaded = self._load_csv_frame_from_filesystem(frame_type, code, path)
        if loaded is None:
            return None
        self._file_cache.put(key, loaded)
        return loaded

    def _validate_write_payloads(
        self,
        frame_type: FrameType,
        code: str,
        payloads: list[tuple[Path, pd.DataFrame]],
    ) -> None:
        for path, payload in payloads:
            size = self._frame_memory_bytes(payload)
            if size > self._max_cache_bytes:
                raise ValueError(
                    f"{frame_type} cache payload exceeds cache capacity code={code} path={path} bytes={size} max_bytes={self._max_cache_bytes}"
                )

    def _evict_code_files(self, frame_type: FrameType, code: str) -> None:
        if self._file_cache is None:
            return
        for key in self._file_cache.keys():
            cached_frame_type, cached_code, _ = key
            if cached_frame_type == frame_type and cached_code == code:
                self._file_cache.pop(key)


__all__ = [
    "CacheStatsSnapshot",
    "DEFAULT_MAX_CACHE_BYTES",
    "LocalKlineDataCache",
]
