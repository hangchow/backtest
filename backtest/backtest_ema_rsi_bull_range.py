#!/usr/bin/env python3
"""Minute-level bull-range EMA + RSI pullback strategy with volume confirmation.

Research references consulted while shaping this implementation:

1. Fidelity, "Exponential Moving Average (EMA)"
   https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/ema
   Used for the trend filter and the idea of buying pullbacks within a rising average structure.

2. Fidelity, "Relative Strength Index (RSI)"
   https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI
   Used for the observation that, in strong uptrends, RSI often operates in higher bands and
   the 40-50 area can behave like support.

3. Fidelity, "Average Volume"
   https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/average-volume
   Used as background for requiring at least normal participation before accepting a pullback entry.

This script is a tuned local wrapper around the repository's EMA + RSI combo implementation.
It is not a line-by-line reproduction of any published trading system.
"""

from __future__ import annotations

import argparse

try:
    from . import backtest_ema_rsi_combo as combo
except ImportError:
    import backtest_ema_rsi_combo as combo

try:
    from .backtest_common import (
        add_data_source_args,
        add_eval_end_arg,
        add_eval_start_arg,
        add_fee_args,
        add_market_arg,
        load_histories,
        load_history,
        parse_eval_end,
        parse_eval_start,
        resolve_codes,
        resolve_data_dir,
        validate_market_for_symbol,
        validate_market_for_symbols,
    )
except ImportError:
    from backtest_common import (
        add_data_source_args,
        add_eval_end_arg,
        add_eval_start_arg,
        add_fee_args,
        add_market_arg,
        load_histories,
        load_history,
        parse_eval_end,
        parse_eval_start,
        resolve_codes,
        resolve_data_dir,
        validate_market_for_symbol,
        validate_market_for_symbols,
    )


DEFAULT_INITIAL_CASH = combo.DEFAULT_INITIAL_CASH
DEFAULT_FAST_SPAN = 15
DEFAULT_SLOW_SPAN = 180
DEFAULT_RSI_PERIOD = 4
DEFAULT_BUY_THRESHOLD = 46.0
DEFAULT_SELL_THRESHOLD = 52.0
DEFAULT_POSITION_RATIO = combo.DEFAULT_POSITION_RATIO
DEFAULT_MAX_OPEN_POSITIONS = combo.DEFAULT_MAX_OPEN_POSITIONS
DEFAULT_VOLUME_WINDOW = combo.DEFAULT_VOLUME_WINDOW
DEFAULT_MIN_VOLUME_RATIO = combo.DEFAULT_MIN_VOLUME_RATIO


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest an optimized EMA + RSI bull-range pullback strategy."
    )
    add_data_source_args(parser)
    add_fee_args(parser)
    add_market_arg(parser)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--fast-span", type=int, default=DEFAULT_FAST_SPAN)
    parser.add_argument("--slow-span", type=int, default=DEFAULT_SLOW_SPAN)
    parser.add_argument("--rsi-period", type=int, default=DEFAULT_RSI_PERIOD)
    parser.add_argument("--buy-threshold", type=float, default=DEFAULT_BUY_THRESHOLD)
    parser.add_argument("--sell-threshold", type=float, default=DEFAULT_SELL_THRESHOLD)
    parser.add_argument("--position-ratio", type=float, default=DEFAULT_POSITION_RATIO)
    parser.add_argument("--max-open-positions", type=int, default=DEFAULT_MAX_OPEN_POSITIONS)
    add_eval_start_arg(parser)
    add_eval_end_arg(parser)
    parser.add_argument("--volume-window", type=int, default=DEFAULT_VOLUME_WINDOW)
    parser.add_argument("--min-volume-ratio", type=float, default=DEFAULT_MIN_VOLUME_RATIO)
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
    volume_window: int,
    min_volume_ratio: float,
    flat_at_close: bool,
    eval_start=None,
    eval_end=None,
    fee_account: str | None = None,
    *,
    market: str,
    security_type: str = "stock",
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
        volume_window=volume_window,
        min_volume_ratio=min_volume_ratio,
        flat_at_close=flat_at_close,
        eval_start=eval_start,
        eval_end=eval_end,
        fee_account=fee_account,
        market=market,
        security_type=security_type,
    )


def main() -> int:
    args = parse_args()
    eval_start = parse_eval_start(args.eval_start)
    eval_end = parse_eval_end(args.eval_end)
    if args.codes:
        if args.data_dir is not None:
            raise ValueError("--codes cannot be used with --data-dir")
        codes = resolve_codes(args.data_root, args.codes)
        market = validate_market_for_symbols(codes, args.market, label="--codes")
        histories = load_histories(args.data_root, codes)
        summary, trades = combo.run_portfolio_backtest(
            histories=histories,
            initial_cash=args.initial_cash,
            fast_span=args.fast_span,
            slow_span=args.slow_span,
            rsi_period=args.rsi_period,
            buy_threshold=args.buy_threshold,
            sell_threshold=args.sell_threshold,
            position_ratio=args.position_ratio,
            volume_window=args.volume_window,
            min_volume_ratio=args.min_volume_ratio,
            flat_at_close=args.flat_at_close,
            max_open_positions=args.max_open_positions,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=args.fee_account,
            market=market,
            security_type=args.security_type,
        )
    else:
        data_dir = resolve_data_dir(args.data_dir)
        market = validate_market_for_symbol(data_dir.name, args.market, label="--data-dir")
        history = load_history(data_dir)
        summary, trades = run_backtest(
            history=history,
            initial_cash=args.initial_cash,
            fast_span=args.fast_span,
            slow_span=args.slow_span,
            rsi_period=args.rsi_period,
            buy_threshold=args.buy_threshold,
            sell_threshold=args.sell_threshold,
            position_ratio=args.position_ratio,
            volume_window=args.volume_window,
            min_volume_ratio=args.min_volume_ratio,
            flat_at_close=args.flat_at_close,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=args.fee_account,
            market=market,
            security_type=args.security_type,
        )

    data_end_time = summary.get("data_end_time", summary["end_time"])
    print(f"Data range: {summary['warmup_start_time']} -> {data_end_time}")
    if summary["warmup_start_time"] != summary["start_time"] or data_end_time != summary["end_time"]:
        print(f"Evaluation range: {summary['start_time']} -> {summary['end_time']}")
    print(f"Initial cash: {summary['initial_cash']:.2f}")
    print(
        "Strategy: "
        f"EMA({summary['fast_span']}) > EMA({summary['slow_span']}) bull-range pullback + "
        f"RSI({summary['rsi_period']}) buy<{summary['buy_threshold']:.0f} "
        f"sell>{summary['sell_threshold']:.0f}"
    )
    print(f"Position ratio per buy: {summary['position_ratio']:.0%}")
    print(
        f"Volume confirmation: current volume >= {summary['min_volume_ratio']:.2f}x "
        f"avg({summary['volume_window']})"
    )
    print(f"Flat at close: {summary['flat_at_close']}")
    print(f"Fee account: {summary['fee_account']}")
    print(f"Market/Security: {summary['market']} / {summary['security_type']}")
    print(f"Trades: {summary['trade_count']} (BUY {summary['buy_count']}, SELL {summary['sell_count']})")
    print(f"Ending cash: {summary['ending_cash']:.2f}")
    if "ending_shares" in summary:
        print(f"Ending shares: {summary['ending_shares']}")
        print(f"Last price: {summary['last_price']:.2f}")
    else:
        print(f"Stock pool: {', '.join(summary['codes'])}")
        print(f"Max open positions: {summary['max_open_positions']}")
        print(f"Ending positions: {summary['ending_positions']}")
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
