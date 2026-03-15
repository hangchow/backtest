#!/usr/bin/env python3
from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.backtest_common import (
    add_data_source_args,
    load_histories,
    load_history,
    resolve_codes,
    resolve_data_dir,
)
from backtest.backtest_rsi_reversion import compute_rsi


DEFAULT_INITIAL_CASH = 100_000.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Search strategy grids on minute-level K-line data for a single symbol "
            "or a stock pool."
        )
    )
    add_data_source_args(parser)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    return parser.parse_args()


def simulate_strategy(
    history: pd.DataFrame,
    buy_signal: pd.Series,
    sell_signal: pd.Series,
    initial_cash: float,
    position_ratio: float,
    flat_at_close: bool,
) -> dict:
    cash = initial_cash
    shares = 0
    trade_count = 0
    peak = initial_cash
    max_drawdown_pct = 0.0

    for row, should_buy, should_sell in zip(history.itertuples(index=False), buy_signal, sell_signal):
        price = float(row.close)

        if shares == 0 and bool(should_buy):
            budget = cash * position_ratio
            qty = int(budget // price)
            if qty > 0:
                cash -= qty * price
                shares = qty
                trade_count += 1
        elif shares > 0 and (bool(should_sell) or (flat_at_close and bool(row.is_day_end))):
            cash += shares * price
            shares = 0
            trade_count += 1

        equity = cash + shares * price
        if equity > peak:
            peak = equity
        drawdown_pct = (equity - peak) / peak * 100
        if drawdown_pct < max_drawdown_pct:
            max_drawdown_pct = drawdown_pct

    last_price = float(history.iloc[-1]["close"])
    final_value = cash + shares * last_price
    return {
        "final_value": final_value,
        "total_return_pct": (final_value / initial_cash - 1) * 100,
        "trade_count": trade_count,
        "max_drawdown_pct": max_drawdown_pct,
    }


def run_buy_and_hold(history: pd.DataFrame, initial_cash: float) -> dict:
    first_price = float(history.iloc[0]["close"])
    qty = int(initial_cash // first_price)
    cash = initial_cash - qty * first_price
    last_price = float(history.iloc[-1]["close"])
    final_value = cash + qty * last_price
    return {
        "strategy": "buy_and_hold",
        "params": f"buy at {first_price:.2f}",
        "position_ratio": 1.0,
        "flat_at_close": False,
        "final_value": final_value,
        "total_return_pct": (final_value / initial_cash - 1) * 100,
        "trade_count": 1,
        "max_drawdown_pct": (last_price - first_price) / first_price * 100,
    }


def search_ema_cross(history: pd.DataFrame, initial_cash: float) -> list[dict]:
    results = []
    ema_cache = {span: history["close"].ewm(span=span, adjust=False).mean() for span in [10, 20, 30, 60, 120, 240]}
    for fast_span, slow_span, position_ratio, flat_at_close in product(
        [10, 20, 30], [120, 240], [0.25, 0.5, 0.75, 1.0], [False, True]
    ):
        fast_ema = ema_cache[fast_span]
        slow_ema = ema_cache[slow_span]
        buy_signal = (fast_ema > slow_ema) & (fast_ema.shift(1) <= slow_ema.shift(1))
        sell_signal = (fast_ema < slow_ema) & (fast_ema.shift(1) >= slow_ema.shift(1))
        summary = simulate_strategy(history, buy_signal, sell_signal, initial_cash, position_ratio, flat_at_close)
        results.append(
            {
                "strategy": "ema_cross",
                "params": f"fast={fast_span}, slow={slow_span}",
                "position_ratio": position_ratio,
                "flat_at_close": flat_at_close,
                **summary,
            }
        )
    return results


def search_rsi_reversion(history: pd.DataFrame, initial_cash: float) -> list[dict]:
    results = []
    rsi_cache = {period: compute_rsi(history["close"], period) for period in [6, 14]}
    for period, buy_threshold, sell_threshold, position_ratio, flat_at_close in product(
        [6, 14], [20, 25, 30], [60, 70], [0.25, 0.5, 0.75, 1.0], [False, True]
    ):
        rsi = rsi_cache[period]
        buy_signal = (rsi < buy_threshold) & (rsi.shift(1) >= buy_threshold)
        sell_signal = (rsi > sell_threshold) & (rsi.shift(1) <= sell_threshold)
        summary = simulate_strategy(history, buy_signal, sell_signal, initial_cash, position_ratio, flat_at_close)
        results.append(
            {
                "strategy": "rsi_reversion",
                "params": f"period={period}, buy<{buy_threshold}, sell>{sell_threshold}",
                "position_ratio": position_ratio,
                "flat_at_close": flat_at_close,
                **summary,
            }
        )
    return results


def search_breakout(history: pd.DataFrame, initial_cash: float) -> list[dict]:
    results = []
    high_cache = {window: history["close"].rolling(window).max().shift(1) for window in [60, 120, 240]}
    low_cache = {window: history["close"].rolling(window).min().shift(1) for window in [15, 30, 60]}
    for entry_window, exit_window, position_ratio, flat_at_close in product(
        [60, 120, 240], [15, 30, 60], [0.25, 0.5, 0.75, 1.0], [False, True]
    ):
        if exit_window >= entry_window:
            continue
        rolling_high = high_cache[entry_window]
        rolling_low = low_cache[exit_window]
        buy_signal = history["close"] > rolling_high
        sell_signal = history["close"] < rolling_low
        summary = simulate_strategy(history, buy_signal, sell_signal, initial_cash, position_ratio, flat_at_close)
        results.append(
            {
                "strategy": "breakout",
                "params": f"entry={entry_window}, exit={exit_window}",
                "position_ratio": position_ratio,
                "flat_at_close": flat_at_close,
                **summary,
            }
        )
    return results


def search_bollinger_reversion(history: pd.DataFrame, initial_cash: float) -> list[dict]:
    results = []
    for window, std_mult, position_ratio, flat_at_close in product(
        [20, 30, 60], [1.5, 2.0, 2.5], [0.25, 0.5, 0.75, 1.0], [False, True]
    ):
        mean = history["close"].rolling(window).mean()
        std = history["close"].rolling(window).std()
        lower = mean - std_mult * std
        upper = mean + std_mult * std
        buy_signal = (history["close"] < lower) & (history["close"].shift(1) >= lower.shift(1))
        sell_signal = (history["close"] > upper) & (history["close"].shift(1) <= upper.shift(1))
        summary = simulate_strategy(history, buy_signal, sell_signal, initial_cash, position_ratio, flat_at_close)
        results.append(
            {
                "strategy": "bollinger_band_reversion",
                "params": f"window={window}, std={std_mult}",
                "position_ratio": position_ratio,
                "flat_at_close": flat_at_close,
                **summary,
            }
        )
    return results


def search_macd_trend(history: pd.DataFrame, initial_cash: float) -> list[dict]:
    results = []
    for fast, slow, signal_span, position_ratio, flat_at_close in product(
        [8, 12], [21, 26, 34], [5, 9], [0.25, 0.5, 0.75, 1.0], [False, True]
    ):
        if fast >= slow:
            continue
        fast_ema = history["close"].ewm(span=fast, adjust=False).mean()
        slow_ema = history["close"].ewm(span=slow, adjust=False).mean()
        macd = fast_ema - slow_ema
        signal = macd.ewm(span=signal_span, adjust=False).mean()
        buy_signal = (macd > signal) & (macd.shift(1) <= signal.shift(1))
        sell_signal = (macd < signal) & (macd.shift(1) >= signal.shift(1))
        summary = simulate_strategy(history, buy_signal, sell_signal, initial_cash, position_ratio, flat_at_close)
        results.append(
            {
                "strategy": "macd_signal_crossover",
                "params": f"fast={fast}, slow={slow}, signal={signal_span}",
                "position_ratio": position_ratio,
                "flat_at_close": flat_at_close,
                **summary,
            }
        )
    return results


def evaluate_history(history: pd.DataFrame, initial_cash: float) -> pd.DataFrame:
    results = [run_buy_and_hold(history, initial_cash)]
    results.extend(search_ema_cross(history, initial_cash))
    results.extend(search_rsi_reversion(history, initial_cash))
    results.extend(search_breakout(history, initial_cash))
    results.extend(search_bollinger_reversion(history, initial_cash))
    results.extend(search_macd_trend(history, initial_cash))
    return pd.DataFrame(results)


def main() -> int:
    args = parse_args()
    codes = resolve_codes(args.data_root, args.codes)

    if codes:
        histories = load_histories(args.data_root, codes)
        result_tables = []
        for code, history in histories.items():
            table = evaluate_history(history, args.initial_cash)
            table["code"] = code
            result_tables.append(table)
            best = table.sort_values("final_value", ascending=False).iloc[0]
            print(f"[{code}] best: {best['strategy']} | {best['params']} | return {best['total_return_pct']:.2f}%")

        pool_table = pd.concat(result_tables, ignore_index=True)
        grouped = (
            pool_table.groupby(["strategy", "params", "position_ratio", "flat_at_close"], as_index=False)
            .agg(
                avg_final_value=("final_value", "mean"),
                avg_return_pct=("total_return_pct", "mean"),
                avg_drawdown_pct=("max_drawdown_pct", "mean"),
                total_trades=("trade_count", "sum"),
            )
            .sort_values("avg_final_value", ascending=False)
            .reset_index(drop=True)
        )
        print("\nStock pool aggregated top 10:")
        print(
            grouped.head(10).to_string(
                index=False,
                formatters={
                    "position_ratio": "{:.0%}".format,
                    "avg_final_value": "{:.2f}".format,
                    "avg_return_pct": "{:.2f}".format,
                    "avg_drawdown_pct": "{:.2f}".format,
                },
            )
        )
        return 0

    history = load_history(resolve_data_dir(args.data_dir))
    table = evaluate_history(history, args.initial_cash).sort_values("final_value", ascending=False).reset_index(drop=True)
    best = table.iloc[0]

    print(f"Data range: {history.iloc[0]['time_key']} -> {history.iloc[-1]['time_key']}")
    print(f"Initial cash: {args.initial_cash:.2f}")
    print(f"Strategies tested: {len(table)}")
    print("\nTop 10 results:")
    print(
        table.head(10).to_string(
            index=False,
            columns=[
                "strategy",
                "params",
                "position_ratio",
                "flat_at_close",
                "final_value",
                "total_return_pct",
                "max_drawdown_pct",
                "trade_count",
            ],
            formatters={
                "position_ratio": "{:.0%}".format,
                "final_value": "{:.2f}".format,
                "total_return_pct": "{:.2f}".format,
                "max_drawdown_pct": "{:.2f}".format,
            },
        )
    )
    print("\nBest result:")
    print(
        f"{best['strategy']} | {best['params']} | "
        f"position {best['position_ratio']:.0%} | "
        f"flat_at_close={bool(best['flat_at_close'])} | "
        f"final value {best['final_value']:.2f} | "
        f"return {best['total_return_pct']:.2f}% | "
        f"max drawdown {best['max_drawdown_pct']:.2f}% | "
        f"trades {int(best['trade_count'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
