#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pandas as pd

try:
    from .backtest_common import add_data_source_args, load_history, resolve_data_dir
except ImportError:
    from backtest_common import add_data_source_args, load_history, resolve_data_dir


DEFAULT_INITIAL_CASH = 100_000.0
DEFAULT_RSI_PERIOD = 6
DEFAULT_BUY_THRESHOLD = 30.0
DEFAULT_SELL_THRESHOLD = 60.0
DEFAULT_POSITION_RATIO = 1.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest an RSI reversion strategy on minute-level K-line data."
    )
    add_data_source_args(parser)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--rsi-period", type=int, default=DEFAULT_RSI_PERIOD)
    parser.add_argument("--buy-threshold", type=float, default=DEFAULT_BUY_THRESHOLD)
    parser.add_argument("--sell-threshold", type=float, default=DEFAULT_SELL_THRESHOLD)
    parser.add_argument("--position-ratio", type=float, default=DEFAULT_POSITION_RATIO)
    parser.add_argument(
        "--flat-at-close",
        action="store_true",
        help="Force close any open position on the last minute of each trading day.",
    )
    parser.add_argument(
        "--show-trades",
        type=int,
        default=5,
        help="How many head/tail trades to print. Use 0 to suppress trade samples.",
    )
    return parser.parse_args()


def compute_rsi(series: pd.Series, period: int) -> pd.Series:
    if period <= 0:
        raise ValueError("period must be positive")

    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    no_losses = avg_loss == 0
    no_gains = avg_gain == 0
    rsi = rsi.mask(no_losses, 100.0)
    rsi = rsi.mask(no_gains, 0.0)
    rsi = rsi.mask(no_losses & no_gains, 50.0)
    return rsi.fillna(50.0)


def run_backtest(
    history: pd.DataFrame,
    initial_cash: float,
    rsi_period: int,
    buy_threshold: float,
    sell_threshold: float,
    position_ratio: float,
    flat_at_close: bool,
) -> tuple[dict, pd.DataFrame]:
    if rsi_period <= 0:
        raise ValueError("rsi-period must be positive")
    if not 0 < position_ratio <= 1:
        raise ValueError("position-ratio must be in the range (0, 1]")
    if buy_threshold >= sell_threshold:
        raise ValueError("buy-threshold must be smaller than sell-threshold")

    rsi = compute_rsi(history["close"], rsi_period)
    buy_signal = (rsi < buy_threshold) & (rsi.shift(1) >= buy_threshold)
    sell_signal = (rsi > sell_threshold) & (rsi.shift(1) <= sell_threshold)

    cash = initial_cash
    shares = 0
    trades: list[dict] = []
    equity_points: list[dict] = []

    for row, should_buy, should_sell, rsi_value in zip(history.itertuples(index=False), buy_signal, sell_signal, rsi):
        price = float(row.close)
        timestamp = row.time_key

        if shares == 0 and bool(should_buy):
            budget = cash * position_ratio
            qty = int(budget // price)
            if qty > 0:
                cash -= qty * price
                shares = qty
                trades.append(
                    {
                        "time_key": timestamp,
                        "action": "BUY",
                        "price": price,
                        "shares": qty,
                        "rsi": float(rsi_value),
                        "cash_after": cash,
                    }
                )
        elif shares > 0 and (bool(should_sell) or (flat_at_close and bool(row.is_day_end))):
            cash += shares * price
            trades.append(
                {
                    "time_key": timestamp,
                    "action": "SELL",
                    "price": price,
                    "shares": shares,
                    "rsi": float(rsi_value),
                    "cash_after": cash,
                }
            )
            shares = 0

        equity = cash + shares * price
        equity_points.append({"time_key": timestamp, "equity": equity})

    last_price = float(history.iloc[-1]["close"])
    final_value = cash + shares * last_price
    equity_curve = pd.DataFrame(equity_points)
    equity_curve["rolling_peak"] = equity_curve["equity"].cummax()
    equity_curve["drawdown_pct"] = (
        (equity_curve["equity"] - equity_curve["rolling_peak"]) / equity_curve["rolling_peak"] * 100
    )

    summary = {
        "start_time": history.iloc[0]["time_key"],
        "end_time": history.iloc[-1]["time_key"],
        "initial_cash": initial_cash,
        "rsi_period": rsi_period,
        "buy_threshold": buy_threshold,
        "sell_threshold": sell_threshold,
        "position_ratio": position_ratio,
        "flat_at_close": flat_at_close,
        "trade_count": len(trades),
        "buy_count": sum(1 for trade in trades if trade["action"] == "BUY"),
        "sell_count": sum(1 for trade in trades if trade["action"] == "SELL"),
        "ending_cash": cash,
        "ending_shares": shares,
        "last_price": last_price,
        "final_value": final_value,
        "total_return_pct": (final_value / initial_cash - 1) * 100,
        "max_drawdown_pct": equity_curve["drawdown_pct"].min(),
    }
    return summary, pd.DataFrame(trades)


def main() -> int:
    args = parse_args()
    history = load_history(resolve_data_dir(args.data_dir, args.code, args.data_root))
    summary, trades = run_backtest(
        history=history,
        initial_cash=args.initial_cash,
        rsi_period=args.rsi_period,
        buy_threshold=args.buy_threshold,
        sell_threshold=args.sell_threshold,
        position_ratio=args.position_ratio,
        flat_at_close=args.flat_at_close,
    )

    print(f"Data range: {summary['start_time']} -> {summary['end_time']}")
    print(f"Initial cash: {summary['initial_cash']:.2f}")
    print(
        "Strategy: "
        f"RSI({summary['rsi_period']}) buy<{summary['buy_threshold']:.0f} "
        f"sell>{summary['sell_threshold']:.0f}"
    )
    print(f"Position ratio per buy: {summary['position_ratio']:.0%}")
    print(f"Flat at close: {summary['flat_at_close']}")
    print(f"Trades: {summary['trade_count']} (BUY {summary['buy_count']}, SELL {summary['sell_count']})")
    print(f"Ending cash: {summary['ending_cash']:.2f}")
    print(f"Ending shares: {summary['ending_shares']}")
    print(f"Last price: {summary['last_price']:.2f}")
    print(f"Final value: {summary['final_value']:.2f}")
    print(f"Total return: {summary['total_return_pct']:.2f}%")
    print(f"Max drawdown: {summary['max_drawdown_pct']:.2f}%")

    if args.show_trades > 0 and not trades.empty:
        sample = min(args.show_trades, len(trades))
        print(f"\nFirst {sample} trades:")
        print(trades.head(sample).to_string(index=False))
        print(f"\nLast {sample} trades:")
        print(trades.tail(sample).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
