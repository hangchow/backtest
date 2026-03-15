from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.compare_backtests import build_report, markdown_table


class MarkdownTableTests(unittest.TestCase):
    def test_markdown_table_formats_floats(self) -> None:
        frame = pd.DataFrame([{"code": "US.TEST", "return_pct": 12.3456}])

        table = markdown_table(frame, ["code", "return_pct"])

        self.assertIn("| code | return_pct |", table)
        self.assertIn("| US.TEST | 12.35 |", table)


class BuildReportTests(unittest.TestCase):
    def test_build_report_selects_best_strategy_per_code(self) -> None:
        data_summary = pd.DataFrame(
            [
                {"code": "A", "rows": 10, "days": 1, "start": "2025-01-01 09:30:00", "end": "2025-01-01 16:00:00"}
            ]
        )
        results = pd.DataFrame(
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
                },
                {
                    "code": "A",
                    "rows": 10,
                    "days": 1,
                    "start": "2025-01-01 09:30:00",
                    "end": "2025-01-01 16:00:00",
                    "strategy": "RSI reversion",
                    "final_value": 120000.0,
                    "return_pct": 20.0,
                    "max_drawdown_pct": -5.0,
                    "trade_count": 20,
                },
            ]
        )

        report = build_report(data_summary, results)

        self.assertIn("## 数据概览", report)
        self.assertIn("## 回测对比", report)
        self.assertIn("## 每个标的的最佳结果", report)
        self.assertIn("| A | RSI reversion | 120000.00 | 20.00 | -5.00 |", report)


if __name__ == "__main__":
    unittest.main()
