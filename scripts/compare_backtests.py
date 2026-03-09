#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import backtest_ema_cross as ema_cross
import backtest_ema_rsi_bull_range as ema_rsi_bull_range
import backtest_ema_rsi_combo as ema_rsi_combo
import backtest_rsi_reversion as rsi_reversion


DEFAULT_DATA_ROOT = Path("data")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the default backtests for one or more symbols and print a Markdown comparison report."
    )
    parser.add_argument(
        "--code",
        action="append",
        required=True,
        help="Symbol directory under --data-root. Repeat this flag to compare multiple symbols.",
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    return parser.parse_args()


def run_all(codes: list[str], data_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    data_rows: list[dict] = []
    result_rows: list[dict] = []

    for code in codes:
        history = rsi_reversion.load_history(data_root / code)
        data_row = {
            "code": code,
            "rows": len(history),
            "days": int(history["trade_date"].nunique()),
            "start": str(history.iloc[0]["time_key"]),
            "end": str(history.iloc[-1]["time_key"]),
        }
        data_rows.append(data_row)

        rsi_summary, _ = rsi_reversion.run_backtest(
            history=history,
            initial_cash=rsi_reversion.DEFAULT_INITIAL_CASH,
            rsi_period=rsi_reversion.DEFAULT_RSI_PERIOD,
            buy_threshold=rsi_reversion.DEFAULT_BUY_THRESHOLD,
            sell_threshold=rsi_reversion.DEFAULT_SELL_THRESHOLD,
            position_ratio=rsi_reversion.DEFAULT_POSITION_RATIO,
            flat_at_close=False,
        )
        result_rows.append(
            {
                **data_row,
                "strategy": "RSI reversion",
                "final_value": rsi_summary["final_value"],
                "return_pct": rsi_summary["total_return_pct"],
                "max_drawdown_pct": rsi_summary["max_drawdown_pct"],
                "trade_count": rsi_summary["trade_count"],
            }
        )

        ema_summary, _ = ema_cross.run_backtest(
            history=history,
            initial_cash=ema_cross.DEFAULT_INITIAL_CASH,
            fast_span=ema_cross.DEFAULT_FAST_SPAN,
            slow_span=ema_cross.DEFAULT_SLOW_SPAN,
            position_ratio=ema_cross.DEFAULT_POSITION_RATIO,
            flat_at_close=True,
        )
        result_rows.append(
            {
                **data_row,
                "strategy": "EMA cross",
                "final_value": ema_summary["final_value"],
                "return_pct": ema_summary["total_return_pct"],
                "max_drawdown_pct": ema_summary["max_drawdown_pct"],
                "trade_count": ema_summary["trade_count"],
            }
        )

        combo_summary, _ = ema_rsi_combo.run_backtest(
            history=history,
            initial_cash=ema_rsi_combo.DEFAULT_INITIAL_CASH,
            fast_span=ema_rsi_combo.DEFAULT_FAST_SPAN,
            slow_span=ema_rsi_combo.DEFAULT_SLOW_SPAN,
            rsi_period=ema_rsi_combo.DEFAULT_RSI_PERIOD,
            buy_threshold=ema_rsi_combo.DEFAULT_BUY_THRESHOLD,
            sell_threshold=ema_rsi_combo.DEFAULT_SELL_THRESHOLD,
            position_ratio=ema_rsi_combo.DEFAULT_POSITION_RATIO,
            flat_at_close=False,
        )
        result_rows.append(
            {
                **data_row,
                "strategy": "EMA + RSI",
                "final_value": combo_summary["final_value"],
                "return_pct": combo_summary["total_return_pct"],
                "max_drawdown_pct": combo_summary["max_drawdown_pct"],
                "trade_count": combo_summary["trade_count"],
            }
        )

        bull_summary, _ = ema_rsi_bull_range.run_backtest(
            history=history,
            initial_cash=ema_rsi_bull_range.DEFAULT_INITIAL_CASH,
            fast_span=ema_rsi_bull_range.DEFAULT_FAST_SPAN,
            slow_span=ema_rsi_bull_range.DEFAULT_SLOW_SPAN,
            rsi_period=ema_rsi_bull_range.DEFAULT_RSI_PERIOD,
            buy_threshold=ema_rsi_bull_range.DEFAULT_BUY_THRESHOLD,
            sell_threshold=ema_rsi_bull_range.DEFAULT_SELL_THRESHOLD,
            position_ratio=ema_rsi_bull_range.DEFAULT_POSITION_RATIO,
            flat_at_close=False,
        )
        result_rows.append(
            {
                **data_row,
                "strategy": "EMA + RSI bull range",
                "final_value": bull_summary["final_value"],
                "return_pct": bull_summary["total_return_pct"],
                "max_drawdown_pct": bull_summary["max_drawdown_pct"],
                "trade_count": bull_summary["trade_count"],
            }
        )

    return pd.DataFrame(data_rows), pd.DataFrame(result_rows)


def format_cell(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| " + " | ".join(format_cell(row[column]) for column in columns) + " |"
        for _, row in frame.loc[:, columns].iterrows()
    ]
    return "\n".join([header, divider, *rows])


def build_report(data_summary: pd.DataFrame, results: pd.DataFrame) -> str:
    best = (
        results.sort_values(["code", "final_value"], ascending=[True, False])
        .groupby("code", as_index=False)
        .first()
        .loc[:, ["code", "strategy", "final_value", "return_pct", "max_drawdown_pct"]]
    )

    return "\n\n".join(
        [
            "## 数据概览\n\n"
            + markdown_table(data_summary, ["code", "rows", "days", "start", "end"]),
            "## 回测对比\n\n"
            + markdown_table(
                results,
                ["code", "strategy", "final_value", "return_pct", "max_drawdown_pct", "trade_count"],
            ),
            "## 每个标的的最佳结果\n\n"
            + markdown_table(best, ["code", "strategy", "final_value", "return_pct", "max_drawdown_pct"]),
        ]
    )


def main() -> int:
    args = parse_args()
    data_summary, results = run_all(args.code, args.data_root)
    print(build_report(data_summary, results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
