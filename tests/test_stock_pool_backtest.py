from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.backtest_common import resolve_codes
from scripts.backtest_rsi_reversion import run_portfolio_backtest


class ResolveCodesTests(unittest.TestCase):
    def test_resolve_codes_raises_when_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            (data_root / "US.MSFT").mkdir()

            with self.assertRaises(FileNotFoundError):
                resolve_codes(data_root, ["US.MSFT", "US.NVDA"])


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
            flat_at_close=False,
            max_open_positions=2,
        )

        self.assertIn("codes", summary)
        self.assertEqual(summary["codes"], ["US.A", "US.B"])
        self.assertTrue((trades["code"].isin(["US.A", "US.B"])).all())
        self.assertGreater(summary["trade_count"], 0)


if __name__ == "__main__":
    unittest.main()
