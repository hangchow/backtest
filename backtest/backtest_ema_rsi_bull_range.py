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
from time import perf_counter

from backtest import backtest_ema_rsi_combo as combo
from backtest.backtest_common import (
    add_data_source_args,
    add_eval_end_arg,
    add_eval_start_arg,
    add_fee_args,
    add_market_arg,
    FilesystemLoadTracker,
    load_histories,
    load_history,
    parse_eval_end,
    parse_eval_start,
    resolve_codes,
    resolve_data_dir,
    validate_market_for_symbol,
    validate_market_for_symbols,
)
from backtest.reporting import observations_by_code_from_histories, render_single_strategy_report
from backtest.strategy_config import add_strategy_config_arg, resolve_single_strategy_defaults


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
    config_defaults = resolve_single_strategy_defaults(
        "ema_rsi_bull_range",
        {
            "fast_span": DEFAULT_FAST_SPAN,
            "slow_span": DEFAULT_SLOW_SPAN,
            "rsi_period": DEFAULT_RSI_PERIOD,
            "buy_threshold": DEFAULT_BUY_THRESHOLD,
            "sell_threshold": DEFAULT_SELL_THRESHOLD,
            "position_ratio": DEFAULT_POSITION_RATIO,
            "max_open_positions": DEFAULT_MAX_OPEN_POSITIONS,
            "volume_window": DEFAULT_VOLUME_WINDOW,
            "min_volume_ratio": DEFAULT_MIN_VOLUME_RATIO,
            "flat_at_close": False,
        },
        argv=argv,
    )
    parser = argparse.ArgumentParser(
        description="Backtest an optimized EMA + RSI bull-range pullback strategy."
    )
    add_strategy_config_arg(parser)
    add_data_source_args(parser)
    add_fee_args(parser)
    add_market_arg(parser)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--fast-span", type=int, default=config_defaults["fast_span"])
    parser.add_argument("--slow-span", type=int, default=config_defaults["slow_span"])
    parser.add_argument("--rsi-period", type=int, default=config_defaults["rsi_period"])
    parser.add_argument("--buy-threshold", type=float, default=config_defaults["buy_threshold"])
    parser.add_argument("--sell-threshold", type=float, default=config_defaults["sell_threshold"])
    parser.add_argument("--position-ratio", type=float, default=config_defaults["position_ratio"])
    parser.add_argument("--max-open-positions", type=int, default=config_defaults["max_open_positions"])
    add_eval_start_arg(parser)
    add_eval_end_arg(parser)
    parser.add_argument("--volume-window", type=int, default=config_defaults["volume_window"])
    parser.add_argument("--min-volume-ratio", type=float, default=config_defaults["min_volume_ratio"])
    parser.add_argument(
        "--flat-at-close",
        dest="flat_at_close",
        action="store_true",
        help="Force close any open position on the last minute of each trading day.",
    )
    parser.add_argument(
        "--no-flat-at-close",
        dest="flat_at_close",
        action="store_false",
        help="Keep positions open across trading-day boundaries.",
    )
    parser.set_defaults(flat_at_close=bool(config_defaults["flat_at_close"]))
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
    total_started_at = perf_counter()
    args = parse_args()
    eval_start = parse_eval_start(args.eval_start)
    eval_end = parse_eval_end(args.eval_end)
    if args.codes:
        if args.data_dir is not None:
            raise ValueError("--codes cannot be used with --data-dir")
        codes = resolve_codes(args.data_root, args.codes)
        market = validate_market_for_symbols(codes, args.market, label="--codes")
        load_tracker = FilesystemLoadTracker()
        histories = load_histories(args.data_root, codes, load_tracker=load_tracker)
        coverage_sections = [("Minute data coverage", observations_by_code_from_histories(histories))]
        strategy_started_at = perf_counter()
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
        load_tracker = FilesystemLoadTracker()
        history = load_history(data_dir, load_tracker=load_tracker)
        coverage_sections = [("Minute data coverage", observations_by_code_from_histories({data_dir.name: history}))]
        strategy_started_at = perf_counter()
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

    strategy_elapsed = perf_counter() - strategy_started_at
    total_elapsed = perf_counter() - total_started_at
    print(
        render_single_strategy_report(
            "ema_rsi_bull_range",
            summary,
            strategy_elapsed,
            total_time_sec=total_elapsed,
            load_stats=load_tracker.snapshot(),
            coverage_sections=coverage_sections,
        )
    )

    if args.show_trades > 0 and not trades.empty:
        sample = min(args.show_trades, len(trades))
        print(f"\nFirst {sample} trades:")
        print(trades.head(sample).to_string(index=False))
        print(f"\nLast {sample} trades:")
        print(trades.tail(sample).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
