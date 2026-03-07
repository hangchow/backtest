from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

# Resolve imports relative to this repository so the tests work under both
# `python tests/test_backtest_scripts.py` and `python -m unittest ...`.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backtest_rsi_reversion import compute_rsi
from scripts.fetch_history_1m import remove_stale_daily_files, save_daily_files


class ComputeRsiTests(unittest.TestCase):
    def test_monotonic_rise_converges_to_100(self) -> None:
        prices = pd.Series([100, 101, 102, 103, 104, 105], dtype=float)

        rsi = compute_rsi(prices, period=3)

        self.assertEqual(float(rsi.iloc[0]), 50.0)
        self.assertTrue((rsi.iloc[1:] == 100.0).all())

    def test_monotonic_drop_converges_to_0(self) -> None:
        prices = pd.Series([105, 104, 103, 102, 101, 100], dtype=float)

        rsi = compute_rsi(prices, period=3)

        self.assertEqual(float(rsi.iloc[0]), 50.0)
        self.assertTrue((rsi.iloc[1:] == 0.0).all())

    def test_flat_series_stays_neutral(self) -> None:
        prices = pd.Series([100, 100, 100, 100], dtype=float)

        rsi = compute_rsi(prices, period=3)

        self.assertTrue((rsi == 50.0).all())


class SaveDailyFilesTests(unittest.TestCase):
    def test_save_daily_files_removes_stale_csvs_by_default(self) -> None:
        history = pd.DataFrame(
            {
                "code": ["HK.00700", "HK.00700"],
                "time_key": ["2026-03-02 09:30:00", "2026-03-03 09:30:00"],
                "open": [1.0, 2.0],
                "close": [1.5, 2.5],
                "high": [1.6, 2.6],
                "low": [0.9, 1.9],
                "volume": [100, 200],
                "turnover": [150.0, 500.0],
                "last_close": [1.0, 1.5],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "HK.00700"
            output_root.mkdir(parents=True, exist_ok=True)
            stale_path = output_root / "HK.00700_2026-02-27.csv"
            stale_path.write_text("time_key,open,close\n", encoding="ascii")

            written_count, removed_count = save_daily_files(history, output_root, keep_existing=False)

            self.assertEqual(written_count, 2)
            self.assertEqual(removed_count, 1)
            self.assertFalse(stale_path.exists())

    def test_remove_stale_daily_files_skips_expected_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            keep_path = output_root / "HK.00700_2026-03-02.csv"
            stale_path = output_root / "HK.00700_2026-02-27.csv"
            keep_path.write_text("", encoding="ascii")
            stale_path.write_text("", encoding="ascii")

            removed_count = remove_stale_daily_files(output_root, {keep_path.name})

            self.assertEqual(removed_count, 1)
            self.assertTrue(keep_path.exists())
            self.assertFalse(stale_path.exists())


if __name__ == "__main__":
    unittest.main()
