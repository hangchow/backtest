from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backtest.backtest_common import (
    compute_relative_volume,
    compute_volume_scale,
    extract_market_from_symbol,
    normalize_max_open_positions,
    parse_eval_end,
    resolve_eval_window,
    resolve_codes,
    validate_market_for_symbol,
    validate_market_for_symbols,
)
from backtest.backtest_ema_cross import run_portfolio_backtest as run_ema_cross_portfolio_backtest
from backtest.backtest_ema_rsi_combo import run_portfolio_backtest as run_ema_rsi_portfolio_backtest
from backtest.backtest_ema_cross import DEFAULT_MAX_OPEN_POSITIONS as EMA_CROSS_DEFAULT_MAX_OPEN_POSITIONS
from backtest.backtest_ema_rsi_combo import DEFAULT_MAX_OPEN_POSITIONS as EMA_RSI_DEFAULT_MAX_OPEN_POSITIONS
from backtest.backtest_dual_momentum import (
    compute_volume_boost,
    load_daily_data,
    run_backtest as run_dual_momentum_backtest,
)
from backtest.backtest_rsi_reversion import (
    DEFAULT_MAX_OPEN_POSITIONS as RSI_REVERSION_DEFAULT_MAX_OPEN_POSITIONS,
    run_portfolio_backtest,
)
from backtest.minute_pool_cache import MinutePoolFeatureCache
from strategy.dual_momentum import DualMomentumParams, build_dual_momentum_signal, build_dual_momentum_signal_history


class ResolveCodesTests(unittest.TestCase):
    def test_resolve_codes_raises_when_missing_directory(self) -> None:
        # 验证缺少目录时解析代码会抛出异常。
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            (data_root / "US.MSFT").mkdir()

            with self.assertRaises(FileNotFoundError):
                resolve_codes(data_root, ["US.MSFT", "US.NVDA"])


class NormalizeMaxOpenPositionsTests(unittest.TestCase):
    def test_default_max_open_positions_is_unlimited_for_minute_stock_pool_scripts(self) -> None:
        # 验证分钟级股票池脚本默认允许无限开仓数。
        self.assertEqual(RSI_REVERSION_DEFAULT_MAX_OPEN_POSITIONS, -1)
        self.assertEqual(EMA_CROSS_DEFAULT_MAX_OPEN_POSITIONS, -1)
        self.assertEqual(EMA_RSI_DEFAULT_MAX_OPEN_POSITIONS, -1)

    def test_normalize_max_open_positions_supports_unlimited(self) -> None:
        # 验证最大开仓数标准化支持 unlimited。
        self.assertEqual(normalize_max_open_positions(-1, 4), 4)

    def test_normalize_max_open_positions_rejects_zero(self) -> None:
        # 验证最大开仓数标准化会拒绝 0。
        with self.assertRaises(ValueError):
            normalize_max_open_positions(0, 4)


class MarketValidationTests(unittest.TestCase):
    def test_extract_market_from_symbol_returns_none_for_unknown_prefix(self) -> None:
        # 验证未知代码前缀会返回空市场信息。
        self.assertIsNone(extract_market_from_symbol("TEST.00001"))

    def test_validate_market_for_symbols_rejects_mixed_code_markets(self) -> None:
        # 验证混合市场代码会被拒绝。
        with self.assertRaises(ValueError):
            validate_market_for_symbols(["HK.00700", "US.MSFT"], "US", label="--codes")

    def test_validate_market_for_symbols_rejects_mismatched_market_argument(self) -> None:
        # 验证 market 参数与代码市场不匹配时会被拒绝。
        with self.assertRaises(ValueError):
            validate_market_for_symbols(["US.MSFT", "US.NVDA"], "HK", label="--codes")

    def test_validate_market_for_symbol_rejects_mismatched_data_dir_market(self) -> None:
        # 验证数据目录市场与代码市场不匹配时会被拒绝。
        with self.assertRaises(ValueError):
            validate_market_for_symbol("US.MSFT", "HK", label="--data-dir")


class RelativeVolumeTests(unittest.TestCase):
    def test_compute_relative_volume_uses_shifted_rolling_average(self) -> None:
        # 验证相对成交量计算会使用错位滚动均值。
        volume = pd.Series([100.0, 200.0, 150.0])

        result = compute_relative_volume(volume, 2)

        self.assertEqual(list(result.round(2)), [1.0, 2.0, 1.0])

    def test_compute_volume_scale_clamps_relative_volume(self) -> None:
        # 验证成交量缩放会对相对成交量进行截断。
        self.assertEqual(compute_volume_scale(0.2, 0.8), 0.5)
        self.assertEqual(compute_volume_scale(0.8, 0.8), 1.0)
        self.assertEqual(compute_volume_scale(2.0, 0.8), 1.25)

    def test_compute_relative_volume_preserves_missing_rows(self) -> None:
        # 验证相对成交量计算会保留缺失行。
        volume = pd.Series([100.0, None, 150.0])

        result = compute_relative_volume(volume, 2)

        self.assertEqual(result.iloc[0], 1.0)
        self.assertTrue(pd.isna(result.iloc[1]))
        self.assertEqual(round(float(result.iloc[2]), 2), 1.5)


class EvalWindowTests(unittest.TestCase):
    def test_parse_eval_end_makes_date_only_inputs_inclusive(self) -> None:
        # 验证纯日期的评估结束时间会按包含当天处理。
        result = parse_eval_end("2025-01-03")

        self.assertEqual(result, pd.Timestamp("2025-01-03 23:59:59.999999"))

    def test_resolve_eval_window_preserves_original_value_types(self) -> None:
        # 验证评估窗口解析会保留原始值类型。
        values = pd.to_datetime(["2025-01-02 09:30:00", "2025-01-02 09:31:00", "2025-01-02 09:32:00"])

        mask, warmup_start, start_time, end_time = resolve_eval_window(
            values,
            eval_start=pd.Timestamp("2025-01-02 09:31:00"),
            eval_end=pd.Timestamp("2025-01-02 09:32:00"),
        )

        self.assertEqual(mask, [False, True, True])
        self.assertEqual(warmup_start, pd.Timestamp("2025-01-02 09:30:00"))
        self.assertEqual(start_time, pd.Timestamp("2025-01-02 09:31:00"))
        self.assertEqual(end_time, pd.Timestamp("2025-01-02 09:32:00"))

    def test_resolve_eval_window_accepts_date_index(self) -> None:
        # 验证评估窗口解析支持日期索引。
        values = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]).date

        mask, warmup_start, start_time, end_time = resolve_eval_window(
            values,
            eval_start=pd.Timestamp("2025-01-03"),
            eval_end=pd.Timestamp("2025-01-03"),
        )

        self.assertEqual(mask, [False, True, False])
        self.assertEqual(warmup_start, pd.Timestamp("2025-01-02").date())
        self.assertEqual(start_time, pd.Timestamp("2025-01-03").date())
        self.assertEqual(end_time, pd.Timestamp("2025-01-03").date())


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
        # 验证组合回测会生成跨标的交易记录。
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
            market="US",
        )

        self.assertIn("codes", summary)
        self.assertEqual(summary["codes"], ["US.A", "US.B"])
        self.assertTrue((trades["code"].isin(["US.A", "US.B"])).all())
        self.assertGreater(summary["trade_count"], 0)

    def test_portfolio_backtest_accepts_unlimited_positions(self) -> None:
        # 验证组合回测支持无限持仓。
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
            market="US",
        )

        self.assertEqual(summary["max_open_positions"], 2)

    def test_portfolio_backtest_uses_pre_eval_bars_for_warmup_only(self) -> None:
        # 验证组合回测只会把评估前 bar 用于预热。
        histories = {
            "US.A": self.build_history([100, 90, 80, 90, 100, 90, 80, 90, 100]),
        }
        eval_start = pd.Timestamp("2025-01-02 09:35:00")
        eval_end = pd.Timestamp("2025-01-02 09:38:00")

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
            max_open_positions=1,
            eval_start=eval_start,
            eval_end=eval_end,
            market="US",
        )

        self.assertEqual(summary["warmup_start_time"], pd.Timestamp("2025-01-02 09:30:00"))
        self.assertEqual(summary["start_time"], eval_start)
        self.assertEqual(summary["end_time"], eval_end)
        self.assertEqual(summary["trade_count"], 2)
        self.assertTrue((trades["time_key"] >= eval_start).all())
        self.assertTrue((trades["time_key"] <= eval_end).all())
        self.assertAlmostEqual(float(summary["final_value"]), 10000.0)

    def test_ema_cross_portfolio_cache_matches_uncached_results(self) -> None:
        histories = {
            "US.A": self.build_history([100, 101, 102, 100, 98, 103, 106, 104]),
            "US.B": self.build_history([200, 198, 197, 199, 201, 205, 203, 206]),
        }
        pool_cache = MinutePoolFeatureCache(histories)

        summary_a, trades_a = run_ema_cross_portfolio_backtest(
            histories=histories,
            initial_cash=10000.0,
            fast_span=2,
            slow_span=4,
            position_ratio=0.5,
            volume_window=2,
            min_volume_ratio=1.0,
            flat_at_close=False,
            max_open_positions=1,
            market="US",
        )
        summary_b, trades_b = run_ema_cross_portfolio_backtest(
            histories=histories,
            pool_cache=pool_cache,
            initial_cash=10000.0,
            fast_span=2,
            slow_span=4,
            position_ratio=0.5,
            volume_window=2,
            min_volume_ratio=1.0,
            flat_at_close=False,
            max_open_positions=1,
            market="US",
        )

        self.assertEqual(summary_a["final_value"], summary_b["final_value"])
        self.assertEqual(summary_a["trade_count"], summary_b["trade_count"])
        pd.testing.assert_frame_equal(trades_a.reset_index(drop=True), trades_b.reset_index(drop=True), check_dtype=False)

    def test_ema_rsi_portfolio_cache_matches_uncached_results(self) -> None:
        histories = {
            "US.A": self.build_history([100, 98, 96, 97, 101, 103, 100, 104, 107]),
            "US.B": self.build_history([200, 199, 198, 197, 199, 202, 201, 204, 206]),
        }
        pool_cache = MinutePoolFeatureCache(histories)

        summary_a, trades_a = run_ema_rsi_portfolio_backtest(
            histories=histories,
            initial_cash=10000.0,
            fast_span=2,
            slow_span=5,
            rsi_period=2,
            buy_threshold=45,
            sell_threshold=60,
            position_ratio=1.0,
            volume_window=2,
            min_volume_ratio=1.0,
            flat_at_close=False,
            max_open_positions=1,
            market="US",
        )
        summary_b, trades_b = run_ema_rsi_portfolio_backtest(
            histories=histories,
            pool_cache=pool_cache,
            initial_cash=10000.0,
            fast_span=2,
            slow_span=5,
            rsi_period=2,
            buy_threshold=45,
            sell_threshold=60,
            position_ratio=1.0,
            volume_window=2,
            min_volume_ratio=1.0,
            flat_at_close=False,
            max_open_positions=1,
            market="US",
        )

        self.assertEqual(summary_a["final_value"], summary_b["final_value"])
        self.assertEqual(summary_a["trade_count"], summary_b["trade_count"])
        pd.testing.assert_frame_equal(trades_a.reset_index(drop=True), trades_b.reset_index(drop=True), check_dtype=False)


class DualMomentumBacktestTests(unittest.TestCase):
    def test_dual_momentum_params_from_mapping_coerces_numeric_values(self) -> None:
        # 验证双动量参数从映射构建时会自动转换数值类型。
        params = DualMomentumParams.from_mapping(
            {
                "lookback_days": "2",
                "top_n": "3",
                "min_volume_ratio": "1.5",
                "target_annual_vol": "0.4",
            }
        )

        self.assertEqual(params.lookback_days, 2)
        self.assertEqual(params.top_n, 3)
        self.assertEqual(params.min_volume_ratio, 1.5)
        self.assertEqual(params.target_annual_vol, 0.4)
        self.assertEqual(params.long_lookback_days, 180)

    def test_build_dual_momentum_signal_accepts_params_object(self) -> None:
        # 验证双动量信号构建支持直接传入参数对象。
        prices = pd.DataFrame(
            {
                "US.A": [100.0, 105.0, 110.0],
                "US.B": [100.0, 101.0, 102.0],
            },
            index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]).date,
        )
        volumes = pd.DataFrame(
            {
                "US.A": [100.0, 150.0, 200.0],
                "US.B": [100.0, 100.0, 100.0],
            },
            index=prices.index,
        )

        signal = build_dual_momentum_signal(
            prices,
            volumes,
            params=DualMomentumParams(
                lookback_days=1,
                long_lookback_days=1,
                long_lookback_weight=0.0,
                top_n=1,
                volume_window=1,
                min_volume_ratio=1.0,
                market_filter_window=1,
                volatility_window=2,
                target_annual_vol=10.0,
                max_gross_exposure=1.0,
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.target_codes, ("US.A",))

    def test_build_dual_momentum_signal_waits_until_all_windows_are_ready(self) -> None:
        # 验证双动量信号会等到所有窗口就绪后再触发。
        prices = pd.DataFrame(
            {
                "US.A": [100.0, 101.0, 102.0],
                "US.B": [100.0, 102.0, 104.0],
            },
            index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]).date,
        )
        volumes = pd.DataFrame(
            {
                "US.A": [100.0, 110.0, 120.0],
                "US.B": [100.0, 120.0, 140.0],
            },
            index=prices.index,
        )

        signal = build_dual_momentum_signal(
            prices,
            volumes,
            params=DualMomentumParams(
                lookback_days=1,
                long_lookback_days=3,
                long_lookback_weight=1.0,
                top_n=1,
                volume_window=1,
                min_volume_ratio=1.0,
                market_filter_window=4,
                volatility_window=2,
                target_annual_vol=10.0,
                max_gross_exposure=1.0,
            ),
        )

        self.assertIsNone(signal)

    def test_build_dual_momentum_signal_history_matches_single_day_builder(self) -> None:
        # 验证历史预计算信号与逐日截断重算的结果完全一致。
        prices = pd.DataFrame(
            {
                "US.A": [100.0, 101.0, 103.0, 104.0, 108.0, 109.0],
                "US.B": [100.0, 102.0, 101.0, 105.0, 107.0, 106.0],
                "US.C": [100.0, 99.0, 101.0, 100.0, 98.0, 97.0],
            },
            index=pd.to_datetime(
                ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09"]
            ).date,
        )
        volumes = pd.DataFrame(
            {
                "US.A": [100.0, 120.0, 140.0, 160.0, 180.0, 175.0],
                "US.B": [100.0, 100.0, 90.0, 110.0, 130.0, 120.0],
                "US.C": [100.0, 105.0, 95.0, 90.0, 85.0, 80.0],
            },
            index=prices.index,
        )
        params = DualMomentumParams(
            lookback_days=2,
            long_lookback_days=3,
            long_lookback_weight=0.25,
            top_n=2,
            volume_window=2,
            min_volume_ratio=1.0,
            market_filter_window=2,
            volatility_window=2,
            target_annual_vol=10.0,
            max_gross_exposure=1.0,
        )

        history_signals = build_dual_momentum_signal_history(prices, volumes, params=params)

        self.assertEqual(list(history_signals.index), list(prices.index))
        for offset, trade_date in enumerate(prices.index, start=1):
            expected = build_dual_momentum_signal(prices.iloc[:offset], volumes.iloc[:offset], params=params)
            actual = history_signals.loc[trade_date]
            if expected is None:
                self.assertIsNone(actual)
                continue

            self.assertIsNotNone(actual)
            assert actual is not None
            self.assertEqual(actual.completed_trade_date, expected.completed_trade_date)
            self.assertEqual(actual.target_codes, expected.target_codes)
            self.assertEqual(actual.target_weights, expected.target_weights)
            self.assertEqual(actual.gross_exposure, expected.gross_exposure)
            self.assertEqual(actual.market_is_risk_on, expected.market_is_risk_on)
            self.assertEqual(actual.candidate_codes, expected.candidate_codes)

    def test_load_daily_data_keeps_missing_sessions_unfilled(self) -> None:
        # 验证加载日线数据时不会填补缺失交易日。
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            (data_root / "US.A").mkdir()
            (data_root / "US.B").mkdir()

            pd.DataFrame(
                {
                    "time_key": ["2025-01-02 00:00:00", "2025-01-03 00:00:00"],
                    "close": [100.0, 101.0],
                    "volume": [1000.0, 1100.0],
                }
            ).to_csv(data_root / "US.A" / "US.A_2024-12-30.csv", index=False)
            pd.DataFrame(
                {
                    "time_key": ["2025-01-02 00:00:00"],
                    "close": [50.0],
                    "volume": [500.0],
                }
            ).to_csv(data_root / "US.B" / "US.B_2024-12-30.csv", index=False)

            prices, volumes = load_daily_data(data_root, ["US.A", "US.B"])

        self.assertTrue(pd.isna(prices.loc[pd.Timestamp("2025-01-03").date(), "US.B"]))
        self.assertTrue(pd.isna(volumes.loc[pd.Timestamp("2025-01-03").date(), "US.B"]))

    def test_load_daily_data_reads_and_deduplicates_weekly_daily_files(self) -> None:
        # 验证加载日线数据时会读取并去重按周拆分的文件。
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            (data_root / "US.A").mkdir()

            pd.DataFrame(
                {
                    "time_key": ["2025-01-06 00:00:00", "2025-01-07 00:00:00"],
                    "close": [100.0, 101.0],
                    "volume": [1000.0, 1100.0],
                }
            ).to_csv(data_root / "US.A" / "US.A_2025-01-06.csv", index=False)
            pd.DataFrame(
                {
                    "time_key": ["2025-01-07 00:00:00", "2025-01-08 00:00:00"],
                    "close": [102.0, 103.0],
                    "volume": [1200.0, 1300.0],
                }
            ).to_csv(data_root / "US.A" / "US.A_2025-01-06_extra.csv", index=False)

            prices, volumes = load_daily_data(data_root, ["US.A"])

        self.assertEqual(list(prices.index), list(pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08"]).date))
        self.assertEqual(float(prices.loc[pd.Timestamp("2025-01-07").date(), "US.A"]), 102.0)
        self.assertEqual(float(volumes.loc[pd.Timestamp("2025-01-07").date(), "US.A"]), 1200.0)

    def test_dual_momentum_prefers_stronger_positive_trend(self) -> None:
        # 验证双动量策略会优先选择更强的正向趋势。
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
            long_lookback_days=2,
            long_lookback_weight=0.0,
            top_n=1,
            volume_window=2,
            min_volume_ratio=1.0,
            market_filter_window=1,
            rebalance_band_pct=0.0,
            volatility_window=2,
            target_annual_vol=10.0,
            max_gross_exposure=1.0,
            market="US",
        )

        self.assertGreater(summary["trade_count"], 0)
        self.assertEqual(trades.iloc[0]["code"], "US.B")

    def test_dual_momentum_rebalances_existing_positions_for_top_n_baskets(self) -> None:
        # 验证双动量策略会对 top N 篮子中的已有仓位执行再平衡。
        dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]).date
        prices = pd.DataFrame(
            {
                "US.A": [100.0, 110.0, 121.0, 115.0],
                "US.B": [100.0, 100.0, 95.0, 110.0],
                "US.C": [100.0, 90.0, 99.0, 100.0],
            },
            index=dates,
        )
        volumes = pd.DataFrame(
            {
                "US.A": [100.0, 100.0, 100.0, 100.0],
                "US.B": [100.0, 100.0, 100.0, 100.0],
                "US.C": [100.0, 100.0, 100.0, 100.0],
            },
            index=dates,
        )

        _, trades = run_dual_momentum_backtest(
            prices=prices,
            volumes=volumes,
            initial_cash=10_000.0,
            lookback_days=1,
            long_lookback_days=1,
            long_lookback_weight=0.0,
            top_n=2,
            volume_window=2,
            min_volume_ratio=1.0,
            market_filter_window=1,
            rebalance_band_pct=0.0,
            volatility_window=2,
            target_annual_vol=10.0,
            max_gross_exposure=1.0,
            market="US",
        )

        rebalance_day = trades[trades["time_key"] == pd.Timestamp("2025-01-07").date()]
        self.assertIn("SELL", set(rebalance_day["action"]))
        self.assertIn("BUY", set(rebalance_day["action"]))
        self.assertIn("US.A", set(rebalance_day[rebalance_day["action"] == "SELL"]["code"]))
        self.assertIn("US.B", set(rebalance_day[rebalance_day["action"] == "BUY"]["code"]))

    def test_dual_momentum_volume_boost_does_not_penalize_high_thresholds(self) -> None:
        # 验证成交量增强不会错误惩罚高阈值场景。
        boost = compute_volume_boost(pd.Series({"US.A": 1.0, "US.B": 1.4}), 2.0)

        self.assertEqual(boost.to_dict(), {"US.A": 1.0, "US.B": 1.0})

    def test_dual_momentum_uses_pre_eval_days_for_warmup_only(self) -> None:
        # 验证双动量策略只把评估前交易日用于预热。
        prices = pd.DataFrame(
            {
                "US.A": [100, 101, 102, 103, 104],
                "US.B": [100, 100, 110, 120, 130],
            },
            index=pd.to_datetime(
                ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"]
            ).date,
        )
        volumes = pd.DataFrame(
            {
                "US.A": [100, 100, 100, 100, 100],
                "US.B": [100, 100, 200, 200, 200],
            },
            index=prices.index,
        )

        summary, trades = run_dual_momentum_backtest(
            prices=prices,
            volumes=volumes,
            initial_cash=10000.0,
            lookback_days=2,
            long_lookback_days=2,
            long_lookback_weight=0.0,
            top_n=1,
            volume_window=2,
            min_volume_ratio=1.0,
            market_filter_window=1,
            rebalance_band_pct=0.0,
            volatility_window=2,
            target_annual_vol=10.0,
            max_gross_exposure=1.0,
            eval_start=pd.Timestamp("2025-01-07"),
            market="US",
        )

        self.assertEqual(summary["warmup_start_time"], pd.Timestamp("2025-01-02").date())
        self.assertEqual(summary["start_time"], pd.Timestamp("2025-01-07").date())
        self.assertGreater(summary["trade_count"], 0)
        self.assertTrue((trades["time_key"] >= pd.Timestamp("2025-01-07").date()).all())

    def test_dual_momentum_respects_eval_end(self) -> None:
        # 验证双动量策略会遵守评估结束时间。
        prices = pd.DataFrame(
            {
                "US.A": [100, 101, 102, 103, 104],
                "US.B": [100, 100, 110, 120, 130],
            },
            index=pd.to_datetime(
                ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"]
            ).date,
        )
        volumes = pd.DataFrame(
            {
                "US.A": [100, 100, 100, 100, 100],
                "US.B": [100, 100, 200, 200, 200],
            },
            index=prices.index,
        )

        summary, trades = run_dual_momentum_backtest(
            prices=prices,
            volumes=volumes,
            initial_cash=10000.0,
            lookback_days=2,
            long_lookback_days=2,
            long_lookback_weight=0.0,
            top_n=1,
            volume_window=2,
            min_volume_ratio=1.0,
            market_filter_window=1,
            rebalance_band_pct=0.0,
            volatility_window=2,
            target_annual_vol=10.0,
            max_gross_exposure=1.0,
            eval_start=pd.Timestamp("2025-01-06"),
            eval_end=pd.Timestamp("2025-01-07"),
            market="US",
        )

        self.assertEqual(summary["start_time"], pd.Timestamp("2025-01-06").date())
        self.assertEqual(summary["end_time"], pd.Timestamp("2025-01-07").date())
        self.assertTrue((trades["time_key"] <= pd.Timestamp("2025-01-07").date()).all())


if __name__ == "__main__":
    unittest.main()
