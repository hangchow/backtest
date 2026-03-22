from __future__ import annotations

import unittest

import pandas as pd

from backtest.backtest_ema_rsi_bull_range import (
    DEFAULT_BUY_THRESHOLD,
    DEFAULT_FAST_SPAN,
    DEFAULT_MAX_OPEN_POSITIONS,
    DEFAULT_MIN_VOLUME_RATIO,
    DEFAULT_RSI_PERIOD,
    DEFAULT_SELL_THRESHOLD,
    DEFAULT_SLOW_SPAN,
    DEFAULT_VOLUME_WINDOW,
    parse_args,
    run_backtest,
)


class ParseArgsTests(unittest.TestCase):
    def test_defaults_match_optimized_profile(self) -> None:
        # 验证默认参数与优化后的参数模板保持一致。
        args = parse_args(["--data-dir", "kline_minute/TEST.00001", "--market", "HK"])

        self.assertEqual(args.fast_span, DEFAULT_FAST_SPAN)
        self.assertEqual(args.slow_span, DEFAULT_SLOW_SPAN)
        self.assertEqual(args.rsi_period, DEFAULT_RSI_PERIOD)
        self.assertEqual(args.buy_threshold, DEFAULT_BUY_THRESHOLD)
        self.assertEqual(args.sell_threshold, DEFAULT_SELL_THRESHOLD)
        self.assertEqual(args.volume_window, DEFAULT_VOLUME_WINDOW)
        self.assertEqual(args.min_volume_ratio, DEFAULT_MIN_VOLUME_RATIO)
        self.assertEqual(args.max_open_positions, DEFAULT_MAX_OPEN_POSITIONS)
        self.assertFalse(args.flat_at_close)
        self.assertEqual(args.market, "HK")

    def test_market_is_required(self) -> None:
        # 验证 market 参数是必填项。
        with self.assertRaises(SystemExit):
            parse_args(["--data-dir", "kline_minute/TEST.00001"])


class RunBacktestTests(unittest.TestCase):
    def test_run_backtest_rejects_invalid_thresholds(self) -> None:
        # 验证回测会拒绝非法阈值配置。
        history = pd.DataFrame(
            {
                "time_key": pd.to_datetime(["2025-03-07 09:30:00", "2025-03-07 09:31:00"]),
                "open": [10.0, 10.2],
                "close": [10.0, 10.1],
                "high": [10.1, 10.3],
                "low": [9.9, 10.0],
                "volume": [100, 100],
                "trade_date": [pd.Timestamp("2025-03-07").date(), pd.Timestamp("2025-03-07").date()],
                "is_day_end": [False, True],
            }
        )

        with self.assertRaises(ValueError):
            run_backtest(
                history=history,
                initial_cash=100_000.0,
                fast_span=15,
                slow_span=180,
                rsi_period=4,
                buy_threshold=52.0,
                sell_threshold=46.0,
                position_ratio=1.0,
                volume_window=10,
                min_volume_ratio=1.0,
                flat_at_close=True,
                market="HK",
            )


if __name__ == "__main__":
    unittest.main()
