#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


DEFAULT_DATA_DIR = Path("data/HK.00700")
DEFAULT_INITIAL_CASH = 10_000.0
DEFAULT_POSITION_RATIO = 0.5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest a simple 3-minute up-buy / 3-minute down-sell strategy."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--position-ratio", type=float, default=DEFAULT_POSITION_RATIO)
    parser.add_argument(
        "--ratio-grid",
        default=None,
        help="Comma-separated position ratios to sweep, for example 0.1,0.2,0.5,1.0.",
    )
    return parser.parse_args()


def load_history(data_dir: Path) -> pd.DataFrame:
    files = sorted(data_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")

    frames = [pd.read_csv(path) for path in files]
    history = pd.concat(frames, ignore_index=True)
    history["time_key"] = pd.to_datetime(history["time_key"])
    history = history.sort_values("time_key").reset_index(drop=True)
    return history


def run_backtest(history: pd.DataFrame, initial_cash: float, position_ratio: float) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    cash = initial_cash
    shares = 0
    trades: list[dict] = []
    equity_points: list[dict] = []

    close_diff = history["close"].diff()
    up3 = (close_diff > 0) & (close_diff.shift(1) > 0) & (close_diff.shift(2) > 0)
    down3 = (close_diff < 0) & (close_diff.shift(1) < 0) & (close_diff.shift(2) < 0)

    for row, buy_signal, sell_signal in zip(history.itertuples(index=False), up3, down3):
        price = float(row.close)
        timestamp = row.time_key

        if bool(buy_signal) and shares == 0:
            budget = cash * position_ratio
            qty = int(budget // price)
            if qty > 0:
                cost = qty * price
                cash -= cost
                shares = qty
                trades.append(
                    {
                        "time_key": timestamp,
                        "action": "BUY",
                        "price": price,
                        "shares": qty,
                        "cash_after": cash,
                    }
                )
        elif bool(sell_signal) and shares > 0:
            proceeds = shares * price
            cash += proceeds
            trades.append(
                {
                    "time_key": timestamp,
                    "action": "SELL",
                    "price": price,
                    "shares": shares,
                    "cash_after": cash,
                }
            )
            shares = 0

        equity = cash + shares * price
        equity_points.append(
            {
                "time_key": timestamp,
                "equity": equity,
                "cash": cash,
                "shares": shares,
                "price": price,
            }
        )

    last_price = float(history.iloc[-1]["close"])
    final_value = cash + shares * last_price
    equity_curve = pd.DataFrame(equity_points)
    equity_curve["rolling_peak"] = equity_curve["equity"].cummax()
    equity_curve["drawdown_pct"] = (
        (equity_curve["equity"] - equity_curve["rolling_peak"]) / equity_curve["rolling_peak"] * 100
    )
    summary = {
        "initial_cash": initial_cash,
        "position_ratio": position_ratio,
        "ending_cash": cash,
        "ending_shares": shares,
        "last_price": last_price,
        "final_value": final_value,
        "total_return_pct": (final_value / initial_cash - 1) * 100,
        "trade_count": len(trades),
        "buy_count": sum(1 for trade in trades if trade["action"] == "BUY"),
        "sell_count": sum(1 for trade in trades if trade["action"] == "SELL"),
        "start_time": history.iloc[0]["time_key"],
        "end_time": history.iloc[-1]["time_key"],
        "max_drawdown_pct": equity_curve["drawdown_pct"].min(),
    }
    return summary, pd.DataFrame(trades), equity_curve


def parse_ratio_grid(raw: str) -> list[float]:
    ratios = [float(value.strip()) for value in raw.split(",") if value.strip()]
    if not ratios:
        raise ValueError("ratio grid must include at least one numeric value")
    for ratio in ratios:
        if ratio <= 0 or ratio > 1:
            raise ValueError("each position ratio must be in the range (0, 1]")
    return ratios


def print_single_result(summary: dict, trades: pd.DataFrame) -> None:
    print(f"Data range: {summary['start_time']} -> {summary['end_time']}")
    print(f"Initial cash: {summary['initial_cash']:.2f}")
    print(f"Position ratio per buy: {summary['position_ratio']:.0%}")
    print(f"Trades: {summary['trade_count']} (BUY {summary['buy_count']}, SELL {summary['sell_count']})")
    print(f"Ending cash: {summary['ending_cash']:.2f}")
    print(f"Ending shares: {summary['ending_shares']}")
    print(f"Last price: {summary['last_price']:.2f}")
    print(f"Final value: {summary['final_value']:.2f}")
    print(f"Total return: {summary['total_return_pct']:.2f}%")
    print(f"Max drawdown: {summary['max_drawdown_pct']:.2f}%")

    if not trades.empty:
        print("\nFirst 5 trades:")
        print(trades.head(5).to_string(index=False))
        print("\nLast 5 trades:")
        print(trades.tail(5).to_string(index=False))


def print_sweep_result(history: pd.DataFrame, initial_cash: float, ratios: list[float]) -> None:
    rows = []
    for ratio in ratios:
        summary, _, _ = run_backtest(history, initial_cash, ratio)
        rows.append(
            {
                "position_ratio": ratio,
                "final_value": summary["final_value"],
                "total_return_pct": summary["total_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "trade_count": summary["trade_count"],
            }
        )

    results = pd.DataFrame(rows).sort_values("position_ratio").reset_index(drop=True)
    best_by_final = results.sort_values("final_value", ascending=False).iloc[0]
    best_by_drawdown = results.sort_values("max_drawdown_pct", ascending=False).iloc[0]

    print(f"Data range: {history.iloc[0]['time_key']} -> {history.iloc[-1]['time_key']}")
    print(f"Initial cash: {initial_cash:.2f}")
    print("\nSweep results:")
    print(results.to_string(index=False, formatters={
        "position_ratio": "{:.0%}".format,
        "final_value": "{:.2f}".format,
        "total_return_pct": "{:.2f}".format,
        "max_drawdown_pct": "{:.2f}".format,
    }))
    print("\nBest final value:")
    print(
        f"Position ratio {best_by_final['position_ratio']:.0%}, "
        f"final value {best_by_final['final_value']:.2f}, "
        f"return {best_by_final['total_return_pct']:.2f}%, "
        f"max drawdown {best_by_final['max_drawdown_pct']:.2f}%"
    )
    print("\nSmallest drawdown:")
    print(
        f"Position ratio {best_by_drawdown['position_ratio']:.0%}, "
        f"final value {best_by_drawdown['final_value']:.2f}, "
        f"return {best_by_drawdown['total_return_pct']:.2f}%, "
        f"max drawdown {best_by_drawdown['max_drawdown_pct']:.2f}%"
    )


def main() -> int:
    args = parse_args()
    history = load_history(args.data_dir)
    if args.ratio_grid:
        ratios = parse_ratio_grid(args.ratio_grid)
        print_sweep_result(history, args.initial_cash, ratios)
        return 0

    summary, trades, _ = run_backtest(history, args.initial_cash, args.position_ratio)
    print_single_result(summary, trades)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
