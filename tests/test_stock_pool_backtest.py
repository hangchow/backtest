from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.backtest_common import (
    compute_relative_volume,
    compute_volume_scale,
    normalize_max_open_positions,
    resolve_codes,
)
from scripts.backtest_dual_momentum import run_backtest as run_dual_momentum_backtest
from scripts.backtest_rsi_reversion import run_portfolio_backtest


class ResolveCodesTests(unittest.TestCase):
    def test_resolve_codes_raises_when_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            (data_root / "US.MSFT").mkdir()

            with self.assertRaises(FileNotFoundError):
                resolve_codes(data_root, ["US.MSFT", "US.NVDA"])


class NormalizeMaxOpenPositionsTests(unittest.TestCase):
    def test_normalize_max_open_positions_supports_unlimited(self) -> None:
        self.assertEqual(normalize_max_open_positions(-1, 4), 4)

    def test_normalize_max_open_positions_rejects_zero(self) -> None:
        with self.assertRaises(ValueError):
            normalize_max_open_positions(0, 4)


class RelativeVolumeTests(unittest.TestCase):
    def test_compute_relative_volume_uses_shifted_rolling_average(self) -> None:
        volume = pd.Series([100.0, 200.0, 150.0])

        result = compute_relative_volume(volume, 2)

        self.assertEqual(list(result.round(2)), [1.0, 2.0, 1.0])

    def test_compute_volume_scale_clamps_relative_volume(self) -> None:
        self.assertEqual(compute_volume_scale(0.2, 0.8), 0.5)
        self.assertEqual(compute_volume_scale(0.8, 0.8), 1.0)
        self.assertEqual(compute_volume_scale(2.0, 0.8), 1.25)


class PortfolioBacktestTests(unittest.TestCase):
    def build_history(self, closes: list[float]) -> pd.DataFrame:
        times = pd.date_range("2025-01-02 09:30:00", periods=len(closes), freq="min")
        trade_dates = [ts.date() for ts in times]
        is_day_end = [False] * len(closes)
        is_day_end[-1] = True
        return pd.DataFrame(
            {
                "time_key": times,
                "open": closes,
                "close": closes,
                "high": closes,
                "low": closes,
                "volume": [100] * len(closes),
                "trade_date": trade_dates,
                "is_day_end": is_day_end,
            }
        )

    def test_portfolio_backtest_generates_cross_code_trades(self) -> None:
        histories = {
            "US.A": self.build_history([100, 90, 80, 90, 100, 110]),
            "US.B": self.build_history([200, 180, 160, 180, 200, 220]),
        }

        summary, trades = run_portfolio_backtest(
            histories=histories,
            initial_cash=10000.0,
            rsi_period=2,
            buy_threshold=45,
            sell_threshold=55,
            position_ratio=1.0,
            volume_window=2,
            min_volume_ratio=1.0,
            flat_at_close=False,
            max_open_positions=2,
        )

        self.assertIn("codes", summary)
        self.assertEqual(summary["codes"], ["US.A", "US.B"])
        self.assertTrue((trades["code"].isin(["US.A", "US.B"])).all())
        self.assertGreater(summary["trade_count"], 0)

    def test_portfolio_backtest_accepts_unlimited_positions(self) -> None:
        histories = {
            "US.A": self.build_history([100, 90, 80, 90, 100, 110]),
            "US.B": self.build_history([200, 180, 160, 180, 200, 220]),
        }

        summary, _ = run_portfolio_backtest(
            histories=histories,
            initial_cash=10000.0,
            rsi_period=2,
            buy_threshold=45,
            sell_threshold=55,
            position_ratio=1.0,
            volume_window=2,
            min_volume_ratio=1.0,
            flat_at_close=False,
            max_open_positions=-1,
        )

        self.assertEqual(summary["max_open_positions"], 2)


class DualMomentumBacktestTests(unittest.TestCase):
    def test_dual_momentum_prefers_stronger_positive_trend(self) -> None:
        prices = pd.DataFrame(
            {
                "US.A": [100, 101, 102, 103, 104],
                "US.B": [100, 100, 110, 120, 130],
            },
            index=pd.to_datetime(
                ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"]
            ).date,
        )

        summary, trades = run_dual_momentum_backtest(
            prices=prices,
            volumes=pd.DataFrame(
                {
                    "US.A": [100, 100, 100, 100, 100],
                    "US.B": [100, 100, 200, 200, 200],
                },
                index=prices.index,
            ),
            initial_cash=10000.0,
            lookback_days=2,
            top_n=1,
            volume_window=2,
            min_volume_ratio=1.0,
        )

        self.assertGreater(summary["trade_count"], 0)
        self.assertEqual(trades.iloc[0]["code"], "US.B")


if __name__ == "__main__":
    unittest.main()
