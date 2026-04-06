from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from strategy.kline_lru_adapter import LocalKlineDataCache
from strategy.kline_reader import LocalKlineReader
from strategy.memory_lru_cache import MemorySizedLruCache


class MemorySizedLruCacheTests(unittest.TestCase):
    def test_evicts_least_recently_used_item_when_capacity_exceeded(self) -> None:
        cache = MemorySizedLruCache[str, str](max_bytes=8, sizeof=len)
        cache.put("a", "1111")
        cache.put("b", "2222")

        self.assertEqual(cache.get("a"), "1111")
        cache.put("c", "3333")

        self.assertEqual(cache.get("b"), None)
        self.assertEqual(cache.get("a"), "1111")
        self.assertEqual(cache.get("c"), "3333")
        snapshot = cache.snapshot()
        self.assertEqual(snapshot.eviction_count, 1)
        self.assertEqual(snapshot.current_bytes, 8)
        self.assertEqual(snapshot.max_bytes, 8)
        self.assertEqual(snapshot.item_count, 2)

    def test_skips_caching_single_item_larger_than_capacity(self) -> None:
        cache = MemorySizedLruCache[str, str](max_bytes=4, sizeof=len)

        cached = cache.put("a", "12345")

        self.assertFalse(cached)
        self.assertEqual(cache.get("a"), None)
        snapshot = cache.snapshot()
        self.assertEqual(snapshot.current_bytes, 0)
        self.assertEqual(snapshot.item_count, 0)


class LocalKlineDataCacheTests(unittest.TestCase):
    def _write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(path, index=False)

    def test_get_daily_csv_frame_uses_file_level_cache_and_evicts_by_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily_root = Path(tmp) / "kline_day"
            code_dir = daily_root / "US.TEST"
            file_a = code_dir / "US.TEST_2025-01-06.csv"
            file_b = code_dir / "US.TEST_2025-01-13.csv"
            rows_a = [
                {"time_key": "2025-01-06 00:00:00", "open": 1, "close": 1, "high": 1, "low": 1, "volume": 10},
                {"time_key": "2025-01-07 00:00:00", "open": 2, "close": 2, "high": 2, "low": 2, "volume": 20},
            ]
            rows_b = [
                {"time_key": "2025-01-13 00:00:00", "open": 3, "close": 3, "high": 3, "low": 3, "volume": 30},
                {"time_key": "2025-01-14 00:00:00", "open": 4, "close": 4, "high": 4, "low": 4, "volume": 40},
            ]
            self._write_csv(file_a, rows_a)
            self._write_csv(file_b, rows_b)

            sample_a = pd.read_csv(file_a)
            sample_a["time_key"] = pd.to_datetime(sample_a["time_key"])
            sample_b = pd.read_csv(file_b)
            sample_b["time_key"] = pd.to_datetime(sample_b["time_key"])
            max_bytes = max(
                int(sample_a.memory_usage(index=True, deep=True).sum()),
                int(sample_b.memory_usage(index=True, deep=True).sum()),
            )

            cache = LocalKlineDataCache(kline_day_root=daily_root, max_cache_bytes=max_bytes)
            daily = cache.get_daily_csv_frame("US.TEST")
            stats = cache.snapshot()

            self.assertEqual(len(daily), 4)
            self.assertLessEqual(stats.current_bytes, max_bytes)
            self.assertGreaterEqual(stats.eviction_count, 1)
            self.assertEqual(stats.files_loaded, 2)
            self.assertEqual(stats.cached_files, 1)

    def test_set_history_frame_repartitions_daily_payload_into_week_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily_root = Path(tmp) / "kline_day"
            code_dir = daily_root / "US.TEST"
            code_dir.mkdir(parents=True, exist_ok=True)
            self._write_csv(
                code_dir / "US.TEST_2025-01-06.csv",
                [
                    {"time_key": "2025-01-06 00:00:00", "open": 2, "close": 2, "high": 2, "low": 2, "volume": 20},
                    {"time_key": "2025-01-07 00:00:00", "open": 3, "close": 3, "high": 3, "low": 3, "volume": 30},
                ],
            )
            self._write_csv(
                code_dir / "US.TEST_2025-01-13.csv",
                [{"time_key": "2025-01-13 00:00:00", "open": 4, "close": 4, "high": 4, "low": 4, "volume": 40}],
            )

            cache = LocalKlineDataCache(kline_day_root=daily_root, max_cache_bytes=1024 * 1024)
            frame = pd.DataFrame(
                [
                    {"code": "US.TEST", "time_key": "2025-01-06 00:00:00", "open": 2, "close": 2, "high": 2, "low": 2, "volume": 20},
                    {"code": "US.TEST", "time_key": "2025-01-07 00:00:00", "open": 3, "close": 3, "high": 3, "low": 3, "volume": 30},
                    {"code": "US.TEST", "time_key": "2025-01-13 00:00:00", "open": 4, "close": 4, "high": 4, "low": 4, "volume": 40},
                ]
            )
            cache.set_history_frame("day", "US.TEST", frame)
            primed = cache.snapshot()
            daily = cache.get_daily_history_frame("US.TEST")

            self.assertEqual(list(daily["time_key"]), list(pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-13"])))
            self.assertEqual(list(daily["code"].unique()), ["US.TEST"])
            self.assertEqual(primed.cached_files, 2)
            self.assertEqual(primed.files_loaded, 0)
            self.assertEqual(cache.snapshot().hit_count - primed.hit_count, 2)

    def test_disabled_file_cache_reads_from_disk_without_retaining_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily_root = Path(tmp) / "kline_day"
            code_dir = daily_root / "US.TEST"
            self._write_csv(
                code_dir / "US.TEST_2025-01-06.csv",
                [
                    {"time_key": "2025-01-06 00:00:00", "open": 2, "close": 2, "high": 2, "low": 2, "volume": 20},
                    {"time_key": "2025-01-07 00:00:00", "open": 3, "close": 3, "high": 3, "low": 3, "volume": 30},
                ],
            )

            cache = LocalKlineDataCache(kline_day_root=daily_root, enable_file_cache=False)

            first = cache.get_daily_csv_frame("US.TEST")
            stats_after_first = cache.snapshot()
            second = cache.get_daily_csv_frame("US.TEST")
            stats_after_second = cache.snapshot()

            pd.testing.assert_frame_equal(first, second)
            self.assertEqual(stats_after_first.files_loaded, 1)
            self.assertEqual(stats_after_first.cached_files, 0)
            self.assertEqual(stats_after_first.current_bytes, 0)
            self.assertEqual(stats_after_first.max_bytes, 0)
            self.assertEqual(stats_after_second.files_loaded, 2)
            self.assertEqual(stats_after_second.hit_count, 0)
            self.assertEqual(stats_after_second.miss_count, 0)

    def test_get_daily_history_tail_frame_only_loads_latest_needed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily_root = Path(tmp) / "kline_day"
            code_dir = daily_root / "US.TEST"
            self._write_csv(
                code_dir / "US.TEST_2025-01-06.csv",
                [
                    {"time_key": "2025-01-06 00:00:00", "open": 1, "close": 1, "high": 1, "low": 1, "volume": 10},
                    {"time_key": "2025-01-07 00:00:00", "open": 2, "close": 2, "high": 2, "low": 2, "volume": 20},
                ],
            )
            self._write_csv(
                code_dir / "US.TEST_2025-01-13.csv",
                [
                    {"time_key": "2025-01-13 00:00:00", "open": 3, "close": 3, "high": 3, "low": 3, "volume": 30},
                    {"time_key": "2025-01-14 00:00:00", "open": 4, "close": 4, "high": 4, "low": 4, "volume": 40},
                ],
            )

            cache = LocalKlineReader(kline_day_root=daily_root)

            tail = cache.get_daily_history_tail_frame("US.TEST", 2)
            stats = cache.snapshot()

            self.assertEqual(list(tail["close"]), [3.0, 4.0])
            self.assertEqual(stats.files_loaded, 1)
            self.assertEqual(stats.load_operations, 1)

    def test_set_history_frame_rejects_oversized_payload_without_clearing_existing_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily_root = Path(tmp) / "kline_day"
            code_dir = daily_root / "US.TEST"
            original_rows = [
                {"time_key": "2025-01-06 00:00:00", "open": 2, "close": 2, "high": 2, "low": 2, "volume": 20},
                {"time_key": "2025-01-07 00:00:00", "open": 3, "close": 3, "high": 3, "low": 3, "volume": 30},
            ]
            self._write_csv(code_dir / "US.TEST_2025-01-06.csv", original_rows)

            sample = pd.DataFrame(original_rows)
            sample["time_key"] = pd.to_datetime(sample["time_key"])
            max_bytes = int(sample.memory_usage(index=True, deep=True).sum())
            cache = LocalKlineDataCache(kline_day_root=daily_root, max_cache_bytes=max_bytes)

            baseline = cache.get_daily_history_frame("US.TEST")
            before = cache.snapshot()

            oversized = pd.DataFrame(
                [
                    {"code": "US.TEST", "time_key": "2025-01-06 00:00:00", "open": 10, "close": 10, "high": 10, "low": 10, "volume": 100},
                    {"code": "US.TEST", "time_key": "2025-01-07 00:00:00", "open": 11, "close": 11, "high": 11, "low": 11, "volume": 110},
                    {"code": "US.TEST", "time_key": "2025-01-08 00:00:00", "open": 12, "close": 12, "high": 12, "low": 12, "volume": 120},
                ]
            )

            with self.assertRaisesRegex(ValueError, "exceeds cache capacity"):
                cache.set_history_frame("day", "US.TEST", oversized)

            after = cache.snapshot()
            current = cache.get_daily_history_frame("US.TEST")

            self.assertEqual(before.cached_files, after.cached_files)
            self.assertEqual(before.current_bytes, after.current_bytes)
            pd.testing.assert_frame_equal(current.reset_index(drop=True), baseline.reset_index(drop=True))

    def test_set_history_frame_rejected_when_file_cache_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily_root = Path(tmp) / "kline_day"
            cache = LocalKlineDataCache(kline_day_root=daily_root, enable_file_cache=False)
            frame = pd.DataFrame(
                [
                    {"code": "US.TEST", "time_key": "2025-01-06 00:00:00", "open": 2, "close": 2, "high": 2, "low": 2, "volume": 20},
                ]
            )

            with self.assertRaisesRegex(RuntimeError, "enable_file_cache=True"):
                cache.set_history_frame("day", "US.TEST", frame)
