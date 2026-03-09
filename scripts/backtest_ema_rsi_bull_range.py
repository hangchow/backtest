#!/usr/bin/env python3
from __future__ import annotations

import argparse

import backtest_ema_rsi_combo as combo
try:
    from .backtest_common import add_data_source_args, load_history, resolve_data_dir
except ImportError:
    from backtest_common import add_data_source_args, load_history, resolve_data_dir


DEFAULT_INITIAL_CASH = combo.DEFAULT_INITIAL_CASH
DEFAULT_FAST_SPAN = 15
DEFAULT_SLOW_SPAN = 180
DEFAULT_RSI_PERIOD = 4
DEFAULT_BUY_THRESHOLD = 46.0
DEFAULT_SELL_THRESHOLD = 52.0
DEFAULT_POSITION_RATIO = combo.DEFAULT_POSITION_RATIO


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest an optimized EMA + RSI bull-range pullback strategy."
    )
    add_data_source_args(parser)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--fast-span", type=int, default=DEFAULT_FAST_SPAN)
    parser.add_argument("--slow-span", type=int, default=DEFAULT_SLOW_SPAN)
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
    return parser.parse_args(argv)


def run_backtest(
    history,
    initial_cash: float,
    fast_span: int,
    slow_span: int,
    rsi_period: int,
    buy_threshold: float,
    sell_threshold: float,
    position_ratio: float,
    flat_at_close: bool,
):
    return combo.run_backtest(
        history=history,
        initial_cash=initial_cash,
        fast_span=fast_span,
        slow_span=slow_span,
        rsi_period=rsi_period,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        position_ratio=position_ratio,
        flat_at_close=flat_at_close,
    )


def main() -> int:
    args = parse_args()
    history = load_history(resolve_data_dir(args.data_dir, args.code, args.data_root))
    summary, trades = run_backtest(
        history=history,
        initial_cash=args.initial_cash,
        fast_span=args.fast_span,
        slow_span=args.slow_span,
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
        f"EMA({summary['fast_span']}) > EMA({summary['slow_span']}) bull-range pullback + "
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
