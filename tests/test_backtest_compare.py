from __future__ import annotations

import sys
import unittest
from unittest import mock
from pathlib import Path

import pandas as pd

from backtest import backtest_dual_momentum_ema_rsi_hybrid as hybrid_backtest
from backtest.backtest_compare import (
    ALL_STRATEGY_KEYS,
    DEFAULT_EVAL_END,
    DEFAULT_EVAL_START,
    MINUTE_STRATEGY_KEYS,
    build_report,
    markdown_table,
    parse_args,
    resolve_report_scope,
    resolve_requested_strategies,
    run_all,
)
from backtest.reporting import (
    build_data_coverage_table,
    build_strategy_summary_row,
    build_strategy_summary_table,
    render_single_strategy_report,
)


class MarkdownTableTests(unittest.TestCase):
    def test_markdown_table_formats_floats(self) -> None:
        # 验证 Markdown 表格会按预期格式化浮点数。
        frame = pd.DataFrame([{"code": "US.TEST", "return_pct": 12.3456}])

        table = markdown_table(frame, ["code", "return_pct"])

        self.assertIn("| code    | return_pct |", table)
        self.assertIn("| US.TEST |      12.35 |", table)

    def test_markdown_table_aligns_numeric_columns_right(self) -> None:
        # 验证 Markdown 表格中的数值列会右对齐。
        frame = pd.DataFrame(
            [
                {"strategy": "EMA cross", "final_value": 101000.0, "trade_count": 10},
                {"strategy": "RSI reversion", "final_value": 9.5, "trade_count": 2},
            ]
        )

        table = markdown_table(frame, ["strategy", "final_value", "trade_count"])

        self.assertIn("| strategy      | final_value | trade_count |", table)
        self.assertIn("| EMA cross     |   101000.00 |          10 |", table)
        self.assertIn("| RSI reversion |        9.50 |           2 |", table)

    def test_build_strategy_summary_table_uses_shared_backtest_columns(self) -> None:
        row = build_strategy_summary_row(
            "dual_momentum",
            {
                "final_value": 110000.0,
                "total_return_pct": 10.0,
                "max_drawdown_pct": -5.0,
                "trade_count": 8,
                "total_fees": 12.5,
            },
            1.234,
        )

        table = build_strategy_summary_table([row])

        self.assertIn("| strategy      | frequency | final_value | return_pct | max_drawdown_pct | trade_count | total_fees | strategy_time_sec |", table)
        self.assertIn("| Dual momentum | daily     |   110000.00 |      10.00 |            -5.00 |           8 |      12.50 |              1.23 |", table)

    def test_build_data_coverage_table_marks_incomplete_codes_as_error(self) -> None:
        table = build_data_coverage_table(
            {
                "US.AAPL": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-03")],
                "US.META": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-03")],
            }
        )

        self.assertIn("| code    | start      | end        | status", table)
        self.assertIn("full_start", table)
        self.assertIn("full_end", table)
        self.assertIn("full_status", table)
        self.assertIn("| US.AAPL | 2026-01-01 | 2026-01-03 | ok", table)
        self.assertIn("| 2026-01-01 | 2026-01-03 | ok", table)
        self.assertIn("US.META", table)
        self.assertIn("error: missing 1 session(s) inside shared span, first 2026-01-02", table)

    def test_render_single_strategy_report_includes_table_and_per_code_coverage(self) -> None:
        report = render_single_strategy_report(
            "momentum_monthly",
            {
                "start_time": pd.Timestamp("2026-01-01"),
                "end_time": pd.Timestamp("2026-03-06 23:59:59.999999"),
                "final_value": 101000.0,
                "total_return_pct": 1.0,
                "max_drawdown_pct": -2.0,
                "trade_count": 3,
                "total_fees": 5.5,
            },
            0.456,
            total_time_sec=0.789,
            coverage_sections=[
                (
                    "Daily data coverage",
                    {
                        "US.AAPL": [
                            pd.Timestamp("2026-01-02"),
                            pd.Timestamp("2026-01-03"),
                            pd.Timestamp("2026-03-05"),
                        ],
                        "US.META": [pd.Timestamp("2026-01-03"), pd.Timestamp("2026-03-05")],
                    },
                )
            ],
        )

        self.assertIn("| Momentum monthly | daily", report)
        self.assertIn("Backtest total time: 0.79s", report)
        self.assertIn("Evaluation window: 2026-01-01 00:00:00 -> 2026-03-06 23:59:59.999999", report)
        self.assertIn("Daily data coverage", report)
        self.assertIn("| US.AAPL | 2026-01-02 | 2026-03-05 | ok", report)
        self.assertIn("| 2026-01-02 | 2026-03-05 | ok", report)
        self.assertIn("US.META", report)
        self.assertIn("error: late start (1 missing before start)", report)


class BuildReportTests(unittest.TestCase):
    def test_build_report_sorts_single_by_code_and_return_pct_and_pool_by_return_pct(self) -> None:
        # 验证报告会在 single 结果中按代码和收益率排序，并在 pool 结果中按收益率排序。
        dataset_summary = pd.DataFrame(
            [
                {
                    "dataset": "kline_minute",
                    "strategies": "EMA cross, RSI reversion",
                    "code": "A",
                    "rows": 10,
                    "days": 1,
                    "start": "2025-01-01 09:30:00",
                    "end": "2025-01-01 16:00:00",
                }
            ]
        )
        minute_results = pd.DataFrame(
            [
                {
                    "code": "A",
                    "rows": 10,
                    "days": 1,
                    "start": "2025-01-01 09:30:00",
                    "end": "2025-01-01 16:00:00",
                    "strategy": "EMA cross",
                    "final_value": 101000.0,
                    "return_pct": 1.0,
                    "max_drawdown_pct": -2.0,
                    "trade_count": 10,
                    "duration": "0:02",
                },
                {
                    "code": "A",
                    "strategy": "RSI reversion",
                    "final_value": 120000.0,
                    "return_pct": 20.0,
                    "max_drawdown_pct": -5.0,
                    "trade_count": 20,
                    "duration": "0:03",
                },
            ]
        )
        pool_results = pd.DataFrame(
            [
                {
                    "pool": "US pool (2)",
                    "strategy": "Dual momentum",
                    "final_value": 110000.0,
                    "return_pct": 10.0,
                    "max_drawdown_pct": -6.0,
                    "trade_count": 8,
                    "duration": "0:03",
                },
                {
                    "pool": "US pool (2)",
                    "strategy": "Momentum monthly",
                    "final_value": 125000.0,
                    "return_pct": 25.0,
                    "max_drawdown_pct": -8.0,
                    "trade_count": 6,
                    "duration": "0:01",
                },
            ]
        )

        report = build_report(dataset_summary, minute_results, pd.DataFrame(), pool_results)

        self.assertIn("## 回测数据集", report)
        self.assertIn("### kline_minute（EMA cross, RSI reversion）", report)
        self.assertIn("## 单标策略对比", report)
        self.assertIn("## 股票池策略对比", report)
        self.assertNotIn("## 股票池最佳结果", report)
        self.assertNotIn("## 每个标的的最佳分钟策略", report)
        self.assertIn("| A    | RSI reversion |   120000.00 |      20.00 |            -5.00 |          20 | 0:03     |", report)
        self.assertIn("| US pool (2) | Momentum monthly |   125000.00 |      25.00 |            -8.00 |           6 | 0:01     |", report)
        self.assertLess(
            report.find("| A    | RSI reversion |   120000.00 |      20.00 |            -5.00 |          20 | 0:03     |"),
            report.find("| A    | EMA cross     |   101000.00 |       1.00 |            -2.00 |          10 | 0:02     |"),
        )
        self.assertLess(report.find("Momentum monthly"), report.find("Dual momentum"))

    def test_build_report_uses_pool_dataset_summary_when_single_summary_is_empty(self) -> None:
        # 验证 single 汇总为空时会回退使用 pool 数据集汇总。
        pool_data_summary = pd.DataFrame(
            [
                {
                    "dataset": "kline_minute",
                    "strategies": "Dual momentum + EMA + RSI hybrid",
                    "code": "HK.00700",
                    "rows": 100,
                    "days": 3,
                    "start": "2025-01-01 09:30:00",
                    "end": "2025-01-03 16:00:00",
                },
                {
                    "dataset": "kline_day",
                    "strategies": "Dual momentum",
                    "code": "HK.00700",
                    "rows": 3,
                    "days": 3,
                    "start": "2025-01-01",
                    "end": "2025-01-03",
                },
            ]
        )
        pool_results = pd.DataFrame(
            [
                {
                    "pool": "HK pool (1)",
                    "strategy": "Dual momentum",
                    "final_value": 110000.0,
                    "return_pct": 10.0,
                    "max_drawdown_pct": -6.0,
                    "trade_count": 8,
                    "duration": "0:02",
                }
            ]
        )

        report = build_report(pd.DataFrame(), pd.DataFrame(), pool_data_summary, pool_results)

        self.assertIn("## 回测数据集", report)
        self.assertIn("### kline_minute（Dual momentum + EMA + RSI hybrid）", report)
        self.assertIn("### kline_day（Dual momentum）", report)
        self.assertIn("| HK.00700 |  100 |    3 | 2025-01-01 09:30:00 | 2025-01-03 16:00:00 |", report)
        self.assertIn("| HK.00700 |    3 |    3 | 2025-01-01 | 2025-01-03 |", report)
        self.assertIn("## 股票池策略对比", report)

    def test_build_report_defaults_bare_single_dataset_to_kline_minute(self) -> None:
        # 验证裸 single 数据集会默认识别为 kline_minute。
        dataset_summary = pd.DataFrame(
            [
                {"code": "US.MSFT", "rows": 10, "days": 1, "start": "2025-01-01 09:30:00", "end": "2025-01-01 16:00:00"}
            ]
        )
        minute_results = pd.DataFrame(
            [
                {
                    "code": "US.MSFT",
                    "strategy": "EMA cross",
                    "final_value": 101000.0,
                    "return_pct": 1.0,
                    "max_drawdown_pct": -2.0,
                    "trade_count": 10,
                }
            ]
        )

        report = build_report(dataset_summary, minute_results, pd.DataFrame(), pd.DataFrame())

        self.assertIn("### kline_minute", report)
        self.assertIn("## 单标策略对比", report)


class RequestedStrategiesTests(unittest.TestCase):
    def test_defaults_to_minute_strategies_for_single_symbol(self) -> None:
        # 验证单标的场景会默认选择分钟级策略。
        self.assertEqual(resolve_requested_strategies(None, 1), list(MINUTE_STRATEGY_KEYS))

    def test_defaults_to_minute_strategies_for_multiple_symbols(self) -> None:
        # 验证多标的场景会默认选择分钟级策略。
        self.assertEqual(resolve_requested_strategies(None, 2), list(MINUTE_STRATEGY_KEYS))

    def test_deduplicates_explicit_strategy_selection(self) -> None:
        # 验证显式传入的策略列表会被去重。
        self.assertEqual(
            resolve_requested_strategies(["ema_cross", "ema_cross", "dual_momentum"], 3),
            ["ema_cross", "dual_momentum"],
        )

    def test_pool_scope_defaults_to_native_pool_strategies_for_single_symbol(self) -> None:
        # 验证单标的 pool 范围会默认选择原生股票池策略。
        self.assertEqual(
            resolve_requested_strategies(None, 1, scope="pool"),
            ["dual_momentum", "momentum_monthly", "dual_momentum_ema_rsi_hybrid"],
        )

    def test_pool_scope_defaults_to_all_pool_strategies_for_multiple_symbols(self) -> None:
        # 验证多标的 pool 范围会默认选择全部股票池策略。
        self.assertEqual(
            resolve_requested_strategies(None, 2, scope="pool"),
            [
                "rsi_reversion",
                "ema_cross",
                "ema_rsi_combo",
                "ema_rsi_bull_range",
                "dual_momentum",
                "momentum_monthly",
                "dual_momentum_ema_rsi_hybrid",
            ],
        )


class ParseArgsTests(unittest.TestCase):
    def test_eval_window_and_scope_default_to_repo_baseline_range(self) -> None:
        # 验证评估窗口和 scope 会默认使用仓库基线区间。
        with mock.patch.object(sys, "argv", ["backtest_compare.py", "--market", "US", "--code", "US.MSFT"]):
            args = parse_args()

        self.assertEqual(args.eval_start, DEFAULT_EVAL_START)
        self.assertEqual(args.eval_end, DEFAULT_EVAL_END)
        self.assertEqual(args.scope, "single")
        self.assertIsNone(args.fee_account)
        self.assertEqual(args.security_type, "stock")


class ScopeResolutionTests(unittest.TestCase):
    def test_explicit_scope_modes(self) -> None:
        # 验证显式传入的 scope 模式会被正确解析。
        self.assertEqual(resolve_report_scope("single", 3), (True, False))
        self.assertEqual(resolve_report_scope("pool", 1), (False, True))
        self.assertEqual(resolve_report_scope("single", 1), (True, False))


class RunAllTests(unittest.TestCase):
    def test_run_all_rejects_pool_only_strategy_in_single_scope(self) -> None:
        # 验证 single 范围下会拒绝仅支持 pool 的策略。
        with self.assertRaisesRegex(ValueError, "single scope does not support strategies"):
            run_all(
                codes=["US.AAPL", "US.MSFT"],
                minute_data_root=Path("kline_minute"),
                daily_data_root=Path("kline_day"),
                market="US",
                scope="single",
                strategy_keys=["ema_cross", "dual_momentum"],
            )

    @mock.patch("backtest.backtest_compare.rsi_reversion.load_history")
    @mock.patch("backtest.backtest_compare.rsi_reversion.run_backtest")
    @mock.patch("backtest.backtest_compare.ema_cross.run_backtest")
    def test_run_all_scope_single_adds_dataset_metadata_and_duration(
        self,
        ema_cross_run_backtest: mock.Mock,
        rsi_run_backtest: mock.Mock,
        load_history: mock.Mock,
    ) -> None:
        # 验证 single 范围执行时会补充数据集元信息和持续时间。
        load_history.return_value = pd.DataFrame(
            {
                "time_key": pd.to_datetime(["2025-01-01 09:30:00", "2025-01-01 16:00:00"]),
                "trade_date": pd.to_datetime(["2025-01-01", "2025-01-01"]).date,
            }
        )
        rsi_run_backtest.return_value = (
            {"final_value": 101000.0, "total_return_pct": 1.0, "max_drawdown_pct": -2.0, "trade_count": 10},
            pd.DataFrame(),
        )
        ema_cross_run_backtest.return_value = (
            {"final_value": 99000.0, "total_return_pct": -1.0, "max_drawdown_pct": -3.0, "trade_count": 6},
            pd.DataFrame(),
        )

        minute_data_summary, minute_results, pool_data_summary, pool_results = run_all(
            codes=["US.AAPL", "US.MSFT"],
            minute_data_root=Path("kline_minute"),
            daily_data_root=Path("kline_day"),
            market="US",
            scope="single",
            strategy_keys=["rsi_reversion", "ema_cross"],
            fee_account="futu_alt",
        )

        self.assertTrue(pool_data_summary.empty)
        self.assertTrue(pool_results.empty)
        self.assertEqual(set(minute_data_summary["dataset"]), {"kline_minute"})
        self.assertEqual(
            minute_data_summary["strategies"].iloc[0],
            "RSI reversion, EMA cross",
        )
        self.assertIn("duration", minute_results.columns)
        self.assertEqual(list(minute_results["strategy"]), ["RSI reversion", "EMA cross", "RSI reversion", "EMA cross"])
        self.assertEqual(rsi_run_backtest.call_args.kwargs["fee_account"], "futu_alt")
        self.assertEqual(ema_cross_run_backtest.call_args.kwargs["fee_account"], "futu_alt")
        self.assertEqual(rsi_run_backtest.call_args.kwargs["security_type"], "stock")

    @mock.patch("backtest.backtest_compare.run_stock_pool_strategies")
    @mock.patch("backtest.backtest_compare.run_single_symbol_strategies")
    def test_run_all_scope_single_skips_pool(
        self,
        run_single_symbol_strategies: mock.Mock,
        run_stock_pool_strategies: mock.Mock,
    ) -> None:
        # 验证 single 范围执行时会跳过 pool 结果。
        run_single_symbol_strategies.return_value = (pd.DataFrame([{"code": "US.AAPL"}]), pd.DataFrame([{"code": "US.AAPL"}]))
        eval_start = pd.Timestamp("2025-03-07")
        eval_end = pd.Timestamp("2026-03-06")

        minute_data_summary, minute_results, pool_data_summary, pool_results = run_all(
            codes=["US.AAPL", "US.MSFT"],
            minute_data_root=Path("kline_minute"),
            daily_data_root=Path("kline_day"),
            market="US",
            scope="single",
            eval_start=eval_start,
            eval_end=eval_end,
        )

        self.assertFalse(minute_data_summary.empty)
        self.assertFalse(minute_results.empty)
        self.assertTrue(pool_data_summary.empty)
        self.assertTrue(pool_results.empty)
        run_stock_pool_strategies.assert_not_called()
        self.assertEqual(run_single_symbol_strategies.call_args.args[-4:], (eval_start, eval_end, None, "stock"))

    @mock.patch("backtest.backtest_compare.run_stock_pool_strategies")
    @mock.patch("backtest.backtest_compare.run_single_symbol_strategies")
    def test_run_all_scope_pool_skips_single(
        self,
        run_single_symbol_strategies: mock.Mock,
        run_stock_pool_strategies: mock.Mock,
    ) -> None:
        # 验证 pool 范围执行时会跳过 single 结果。
        run_stock_pool_strategies.return_value = (
            pd.DataFrame([{"code": "US.AAPL"}]),
            pd.DataFrame([{"pool": "US pool (2)"}]),
        )
        eval_start = pd.Timestamp("2025-03-07")
        eval_end = pd.Timestamp("2026-03-06")

        minute_data_summary, minute_results, pool_data_summary, pool_results = run_all(
            codes=["US.AAPL", "US.MSFT"],
            minute_data_root=Path("kline_minute"),
            daily_data_root=Path("kline_day"),
            market="US",
            scope="pool",
            eval_start=eval_start,
            eval_end=eval_end,
        )

        self.assertTrue(minute_data_summary.empty)
        self.assertTrue(minute_results.empty)
        self.assertFalse(pool_data_summary.empty)
        self.assertFalse(pool_results.empty)
        run_single_symbol_strategies.assert_not_called()
        self.assertEqual(run_stock_pool_strategies.call_args.args[-4:], (eval_start, eval_end, None, "stock"))

    @mock.patch("backtest.backtest_compare.hybrid.run_backtest")
    @mock.patch("backtest.backtest_compare.hybrid.load_day_end_minute_indicators")
    @mock.patch("backtest.backtest_compare.momentum_monthly.run_monthly_momentum")
    @mock.patch("backtest.backtest_compare.dual_momentum.run_backtest")
    @mock.patch("backtest.backtest_compare.dual_momentum.load_daily_data")
    @mock.patch("backtest.backtest_compare.ema_rsi_combo.run_portfolio_backtest")
    @mock.patch("backtest.backtest_compare.ema_cross.run_portfolio_backtest")
    @mock.patch("backtest.backtest_compare.rsi_reversion.run_portfolio_backtest")
    @mock.patch("backtest.backtest_compare.load_histories")
    def test_run_all_includes_minute_strategies_in_stock_pool_results(
        self,
        load_histories: mock.Mock,
        rsi_portfolio_run: mock.Mock,
        ema_cross_portfolio_run: mock.Mock,
        ema_rsi_combo_portfolio_run: mock.Mock,
        load_daily_data: mock.Mock,
        dual_run: mock.Mock,
        monthly_run: mock.Mock,
        load_day_end_minute_indicators: mock.Mock,
        hybrid_run: mock.Mock,
    ) -> None:
        # 验证 run_all 会把分钟级策略纳入股票池结果。
        minute_histories = {
            "US.AAPL": pd.DataFrame(
                {
                    "time_key": pd.to_datetime(["2025-01-01 09:30:00", "2025-01-02 09:30:00"]),
                    "trade_date": pd.to_datetime(["2025-01-01", "2025-01-02"]).date,
                }
            ),
            "US.MSFT": pd.DataFrame(
                {
                    "time_key": pd.to_datetime(["2025-01-01 09:31:00", "2025-01-02 09:31:00"]),
                    "trade_date": pd.to_datetime(["2025-01-01", "2025-01-02"]).date,
                }
            ),
        }
        load_histories.return_value = minute_histories
        rsi_portfolio_run.return_value = (
            {"final_value": 101000.0, "total_return_pct": 1.0, "max_drawdown_pct": -2.0, "trade_count": 10},
            pd.DataFrame(),
        )
        ema_cross_portfolio_run.return_value = (
            {"final_value": 102000.0, "total_return_pct": 2.0, "max_drawdown_pct": -3.0, "trade_count": 11},
            pd.DataFrame(),
        )
        ema_rsi_combo_portfolio_run.side_effect = [
            (
                {"final_value": 103000.0, "total_return_pct": 3.0, "max_drawdown_pct": -4.0, "trade_count": 12},
                pd.DataFrame(),
            ),
            (
                {"final_value": 104000.0, "total_return_pct": 4.0, "max_drawdown_pct": -5.0, "trade_count": 13},
                pd.DataFrame(),
            ),
        ]

        prices = pd.DataFrame(
            {
                "US.AAPL": [100.0, 101.0],
                "US.MSFT": [100.0, 102.0],
            },
            index=pd.Index([pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-02").date()]),
        )
        volumes = pd.DataFrame(
            {
                "US.AAPL": [1000.0, 1100.0],
                "US.MSFT": [1000.0, 1200.0],
            },
            index=prices.index,
        )
        load_daily_data.return_value = (prices, volumes)
        dual_run.return_value = (
            {"final_value": 110000.0, "total_return_pct": 10.0, "max_drawdown_pct": -5.0, "trade_count": 8},
            pd.DataFrame(),
        )
        monthly_run.return_value = (
            {"final_value": 120000.0, "total_return_pct": 20.0, "max_drawdown_pct": -7.0, "trade_count": 6},
            pd.DataFrame(),
        )
        load_day_end_minute_indicators.return_value = {"US.AAPL": pd.DataFrame(), "US.MSFT": pd.DataFrame()}
        hybrid_run.return_value = (
            {"final_value": 130000.0, "total_return_pct": 30.0, "max_drawdown_pct": -9.0, "trade_count": 10},
            pd.DataFrame(),
        )

        _, _, pool_data_summary, pool_results = run_all(
            codes=["US.AAPL", "US.MSFT"],
            minute_data_root=Path("kline_minute"),
            daily_data_root=Path("kline_day"),
            market="US",
            strategy_keys=list(ALL_STRATEGY_KEYS),
            scope="pool",
            fee_account="futu_alt",
        )

        self.assertEqual(
            list(pool_results["strategy"]),
            [
                "RSI reversion",
                "EMA cross",
                "EMA + RSI",
                "EMA + RSI bull range",
                "Dual momentum",
                "Momentum monthly",
                "Dual momentum + EMA + RSI hybrid",
            ],
        )
        self.assertIn("duration", pool_results.columns)
        self.assertEqual(
            list(pool_data_summary["dataset"]),
            ["kline_day", "kline_day", "kline_minute", "kline_minute"],
        )
        self.assertEqual(
            pool_data_summary[pool_data_summary["dataset"] == "kline_day"]["strategies"].iloc[0],
            "Dual momentum, Momentum monthly, Dual momentum + EMA + RSI hybrid",
        )
        self.assertEqual(
            pool_data_summary[pool_data_summary["dataset"] == "kline_minute"]["strategies"].iloc[0],
            "RSI reversion, EMA cross, EMA + RSI, EMA + RSI bull range, Dual momentum + EMA + RSI hybrid",
        )
        self.assertEqual(list(pool_data_summary[pool_data_summary["dataset"] == "kline_day"]["code"]), ["US.AAPL", "US.MSFT"])
        self.assertEqual(list(pool_data_summary[pool_data_summary["dataset"] == "kline_minute"]["code"]), ["US.AAPL", "US.MSFT"])
        self.assertEqual(load_histories.call_args.kwargs, {})
        self.assertEqual(load_histories.call_args.args, (Path("kline_minute"), ["US.AAPL", "US.MSFT"]))
        self.assertEqual(rsi_portfolio_run.call_args.kwargs["fee_account"], "futu_alt")
        self.assertEqual(ema_cross_portfolio_run.call_args.kwargs["fee_account"], "futu_alt")
        self.assertEqual(ema_rsi_combo_portfolio_run.call_args_list[0].kwargs["fee_account"], "futu_alt")
        self.assertEqual(dual_run.call_args.kwargs["fee_account"], "futu_alt")
        self.assertEqual(monthly_run.call_args.kwargs["fee_account"], "futu_alt")
        self.assertEqual(hybrid_run.call_args.kwargs["fee_account"], "futu_alt")

    @mock.patch("backtest.backtest_compare.hybrid.run_backtest")
    @mock.patch("backtest.backtest_compare.hybrid.load_day_end_minute_indicators")
    @mock.patch("backtest.backtest_compare.momentum_monthly.run_monthly_momentum")
    @mock.patch("backtest.backtest_compare.dual_momentum.run_backtest")
    @mock.patch("backtest.backtest_compare.dual_momentum.load_daily_data")
    @mock.patch("backtest.backtest_compare.load_histories")
    def test_run_all_supports_stock_pool_strategies(
        self,
        load_histories: mock.Mock,
        load_daily_data: mock.Mock,
        dual_run: mock.Mock,
        monthly_run: mock.Mock,
        load_day_end_minute_indicators: mock.Mock,
        hybrid_run: mock.Mock,
    ) -> None:
        # 验证 run_all 支持执行股票池策略。
        prices = pd.DataFrame(
            {
                "US.AAPL": [100.0, 101.0],
                "US.MSFT": [100.0, 102.0],
            },
            index=pd.Index([pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-02").date()]),
        )
        volumes = pd.DataFrame(
            {
                "US.AAPL": [1000.0, 1100.0],
                "US.MSFT": [1000.0, 1200.0],
            },
            index=prices.index,
        )
        load_daily_data.return_value = (prices, volumes)
        load_histories.return_value = {
            "US.AAPL": pd.DataFrame(
                {
                    "time_key": pd.to_datetime(["2025-01-01", "2025-01-02"]),
                    "trade_date": pd.to_datetime(["2025-01-01", "2025-01-02"]).date,
                }
            ),
            "US.MSFT": pd.DataFrame(
                {
                    "time_key": pd.to_datetime(["2025-01-01", "2025-01-02"]),
                    "trade_date": pd.to_datetime(["2025-01-01", "2025-01-02"]).date,
                }
            ),
        }
        load_day_end_minute_indicators.return_value = {"US.AAPL": pd.DataFrame(), "US.MSFT": pd.DataFrame()}
        dual_run.return_value = (
            {"final_value": 110000.0, "total_return_pct": 10.0, "max_drawdown_pct": -5.0, "trade_count": 8},
            pd.DataFrame(),
        )
        monthly_run.return_value = (
            {"final_value": 120000.0, "total_return_pct": 20.0, "max_drawdown_pct": -7.0, "trade_count": 6},
            pd.DataFrame(),
        )
        hybrid_run.return_value = (
            {"final_value": 130000.0, "total_return_pct": 30.0, "max_drawdown_pct": -9.0, "trade_count": 10},
            pd.DataFrame(),
        )

        minute_data_summary, minute_results, pool_data_summary, pool_results = run_all(
            codes=["US.AAPL", "US.MSFT"],
            minute_data_root=Path("kline_minute"),
            daily_data_root=Path("kline_day"),
            market="US",
            scope="pool",
            strategy_keys=["dual_momentum", "momentum_monthly", "dual_momentum_ema_rsi_hybrid"],
            fee_account="futu_alt",
        )

        self.assertTrue(minute_data_summary.empty)
        self.assertTrue(minute_results.empty)
        self.assertEqual(set(pool_data_summary["dataset"]), {"kline_minute", "kline_day"})
        self.assertEqual(
            pool_data_summary[pool_data_summary["dataset"] == "kline_day"]["strategies"].iloc[0],
            "Dual momentum, Momentum monthly, Dual momentum + EMA + RSI hybrid",
        )
        self.assertEqual(
            pool_data_summary[pool_data_summary["dataset"] == "kline_minute"]["strategies"].iloc[0],
            "Dual momentum + EMA + RSI hybrid",
        )
        self.assertEqual(
            list(pool_results["strategy"]),
            ["Dual momentum", "Momentum monthly", "Dual momentum + EMA + RSI hybrid"],
        )
        self.assertIn("duration", pool_results.columns)
        self.assertEqual(dual_run.call_args.kwargs["initial_cash"], 100000.0)
        self.assertEqual(monthly_run.call_args.kwargs["initial_cash"], 100000.0)
        self.assertEqual(hybrid_run.call_args.kwargs["initial_cash"], 100000.0)
        self.assertEqual(dual_run.call_args.kwargs["fee_account"], "futu_alt")
        self.assertEqual(monthly_run.call_args.kwargs["fee_account"], "futu_alt")
        self.assertEqual(hybrid_run.call_args.kwargs["fee_account"], "futu_alt")
        self.assertEqual(load_histories.call_args.args, (Path("kline_minute"), ["US.AAPL", "US.MSFT"]))

    @mock.patch("backtest.backtest_compare.hybrid.run_backtest")
    @mock.patch("backtest.backtest_compare.hybrid.load_day_end_minute_indicators")
    @mock.patch("backtest.backtest_compare.hybrid.load_daily_closes")
    @mock.patch("backtest.backtest_compare.dual_momentum.load_daily_data")
    @mock.patch("backtest.backtest_compare.load_histories")
    def test_run_all_hybrid_only_uses_close_only_daily_loader(
        self,
        load_histories: mock.Mock,
        load_daily_data: mock.Mock,
        load_daily_closes: mock.Mock,
        load_day_end_minute_indicators: mock.Mock,
        hybrid_run: mock.Mock,
    ) -> None:
        # 验证 hybrid 模式只会使用 close-only 的日线加载器。
        load_histories.return_value = {
            "US.AAPL": pd.DataFrame(
                {
                    "time_key": pd.to_datetime(["2025-01-01 09:30:00", "2025-01-02 09:30:00"]),
                    "trade_date": pd.to_datetime(["2025-01-01", "2025-01-02"]).date,
                }
            ),
            "US.MSFT": pd.DataFrame(
                {
                    "time_key": pd.to_datetime(["2025-01-01 09:30:00", "2025-01-02 09:30:00"]),
                    "trade_date": pd.to_datetime(["2025-01-01", "2025-01-02"]).date,
                }
            ),
        }
        closes = pd.DataFrame(
            {
                "US.AAPL": [100.0, 101.0],
                "US.MSFT": [200.0, 201.0],
            },
            index=pd.Index([pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-02").date()]),
        )
        load_daily_closes.return_value = closes
        load_day_end_minute_indicators.return_value = {"US.AAPL": pd.DataFrame(), "US.MSFT": pd.DataFrame()}
        hybrid_run.return_value = (
            {"final_value": 130000.0, "total_return_pct": 30.0, "max_drawdown_pct": -9.0, "trade_count": 10},
            pd.DataFrame(),
        )

        _, _, pool_data_summary, pool_results = run_all(
            codes=["US.AAPL", "US.MSFT"],
            minute_data_root=Path("kline_minute"),
            daily_data_root=Path("kline_day"),
            market="US",
            scope="pool",
            strategy_keys=["dual_momentum_ema_rsi_hybrid"],
        )

        load_daily_data.assert_not_called()
        load_daily_closes.assert_called_once_with(Path("kline_day"), ["US.AAPL", "US.MSFT"])
        self.assertEqual(set(pool_data_summary["dataset"]), {"kline_minute", "kline_day"})
        self.assertEqual(
            pool_data_summary[pool_data_summary["dataset"] == "kline_day"]["strategies"].iloc[0],
            "Dual momentum + EMA + RSI hybrid",
        )
        self.assertEqual(
            pool_data_summary[pool_data_summary["dataset"] == "kline_minute"]["strategies"].iloc[0],
            "Dual momentum + EMA + RSI hybrid",
        )
        self.assertEqual(list(pool_results["strategy"]), ["Dual momentum + EMA + RSI hybrid"])

    def test_run_all_rejects_single_code_pool_minute_strategy(self) -> None:
        # 验证单代码场景会拒绝 pool 分钟级策略。
        with self.assertRaisesRegex(ValueError, "require at least 2 codes"):
            run_all(
                codes=["US.AAPL"],
                minute_data_root=Path("kline_minute"),
                daily_data_root=Path("kline_day"),
                market="US",
                scope="pool",
                strategy_keys=["ema_cross"],
            )


class HybridBacktestTests(unittest.TestCase):
    def test_liquidation_uses_last_bar_within_eval_window(self) -> None:
        # 验证清仓价格会使用评估窗口内最后一根 bar。
        closes = pd.DataFrame(
            {"US.AAPL": [100.0, 110.0, 120.0, 1000.0]},
            index=[
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-03").date(),
                pd.Timestamp("2025-01-04").date(),
            ],
        )
        minute_indicators = {
            "US.AAPL": pd.DataFrame(
                {
                    "close": [100.0, 110.0, 120.0, 1000.0],
                    "ema_fast": [90.0, 100.0, 130.0, 150.0],
                    "ema_slow": [100.0, 105.0, 120.0, 140.0],
                    "rsi": [40.0, 45.0, 60.0, 65.0],
                },
                index=pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]),
            )
        }

        summary, trades = hybrid_backtest.run_backtest(
            closes=closes,
            minute_indicators=minute_indicators,
            initial_cash=1000.0,
            lookback_days=1,
            long_lookback_days=1,
            long_lookback_weight=0.0,
            market_filter_window=2,
            daily_vol_window=2,
            min_momentum_score=-1.0,
            rebalance_days=1,
            switch_score_buffer=0.0,
            min_hold_days=0,
            timing_score_weight=0.0,
            entry_rsi_min=50.0,
            entry_rsi_max=70.0,
            exit_rsi_min=45.0,
            stop_loss_pct=1.0,
            take_profit_pct=10.0,
            position_ratio=1.0,
            eval_start=pd.Timestamp("2025-01-01"),
            eval_end=pd.Timestamp("2025-01-03"),
            fee_account=None,
            market="US",
        )

        self.assertEqual(summary["trade_count"], 2)
        self.assertAlmostEqual(summary["final_value"], 1000.0)
        self.assertEqual(list(trades["action"]), ["BUY", "SELL"])
        self.assertEqual(pd.Timestamp(trades.iloc[-1]["time_key"]), pd.Timestamp("2025-01-03"))
        self.assertAlmostEqual(float(trades.iloc[-1]["price"]), 120.0)


if __name__ == "__main__":
    unittest.main()
