#!/usr/bin/env python3
"""Minute-level EMA crossover strategy with volume-aware ranking and sizing.

Research references consulted while shaping this implementation:

1. Fidelity, "Exponential Moving Average (EMA)"
   https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/ema
   Used for the trend-following logic behind EMA direction and crossover-style signals.

2. Fidelity, "Average Volume"
   https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/average-volume
   Used as background for treating higher-than-average volume as confirmation that a move
   is stronger than a similar move on weak volume.

3. Fidelity, "Volume Oscillator (VO)"
   https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/volume-oscillator
   Used as background for measuring volume expansion relative to recent history.

This script is a simplified local implementation for the repository's minute-level datasets.
It is not a line-by-line reproduction of any published trading system.
"""

from __future__ import annotations

import argparse
from time import perf_counter

import numpy as np
import pandas as pd

from backtest.backtest_common import (
    add_data_source_args,
    add_eval_end_arg,
    add_eval_start_arg,
    add_fee_args,
    add_market_arg,
    compute_buy_quantity_with_fees,
    compute_order_fees,
    compute_relative_volume,
    compute_volume_scale,
    FilesystemLoadTracker,
    load_histories,
    load_history,
    normalize_max_open_positions,
    normalize_market,
    parse_eval_end,
    parse_eval_start,
    resolve_codes,
    resolve_data_dir,
    resolve_eval_window,
    sum_trade_fees,
    validate_market_for_symbol,
    validate_market_for_symbols,
    validate_volume_filter,
)
from backtest.minute_pool_cache import MinutePoolFeatureCache
from backtest.reporting import observations_by_code_from_histories, render_single_strategy_report
from backtest.strategy_config import add_strategy_config_arg, resolve_single_strategy_defaults


DEFAULT_INITIAL_CASH = 100_000.0
DEFAULT_FAST_SPAN = 30
DEFAULT_SLOW_SPAN = 120
DEFAULT_POSITION_RATIO = 0.5
DEFAULT_MAX_OPEN_POSITIONS = -1
DEFAULT_VOLUME_WINDOW = 5
DEFAULT_MIN_VOLUME_RATIO = 0.6


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    config_defaults = resolve_single_strategy_defaults(
        "ema_cross",
        {
            "fast_span": DEFAULT_FAST_SPAN,
            "slow_span": DEFAULT_SLOW_SPAN,
            "position_ratio": DEFAULT_POSITION_RATIO,
            "max_open_positions": DEFAULT_MAX_OPEN_POSITIONS,
            "volume_window": DEFAULT_VOLUME_WINDOW,
            "min_volume_ratio": DEFAULT_MIN_VOLUME_RATIO,
            "flat_at_close": False,
        },
        argv=argv,
    )
    parser = argparse.ArgumentParser(
        description="Backtest an EMA cross strategy on minute-level K-line data."
    )
    add_strategy_config_arg(parser)
    add_data_source_args(parser)
    add_fee_args(parser)
    add_market_arg(parser)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--fast-span", type=int, default=config_defaults["fast_span"])
    parser.add_argument("--slow-span", type=int, default=config_defaults["slow_span"])
    parser.add_argument("--position-ratio", type=float, default=config_defaults["position_ratio"])
    parser.add_argument("--max-open-positions", type=int, default=config_defaults["max_open_positions"])
    add_eval_start_arg(parser)
    add_eval_end_arg(parser)
    parser.add_argument(
        "--volume-window",
        type=int,
        default=config_defaults["volume_window"],
        help="Rolling window used to compare current volume against recent average volume.",
    )
    parser.add_argument(
        "--min-volume-ratio",
        type=float,
        default=config_defaults["min_volume_ratio"],
        help="Relative-volume level above which crossover entries can scale above the base position size.",
    )
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
    history: pd.DataFrame,
    initial_cash: float,
    fast_span: int,
    slow_span: int,
    position_ratio: float,
    volume_window: int,
    min_volume_ratio: float,
    flat_at_close: bool,
    eval_start: pd.Timestamp | None = None,
    eval_end: pd.Timestamp | None = None,
    fee_account: str | None = None,
    *,
    market: str,
    security_type: str = "stock",
) -> tuple[dict, pd.DataFrame]:
    market = normalize_market(market)
    if fast_span <= 0 or slow_span <= 0:
        raise ValueError("fast-span and slow-span must be positive")
    if fast_span >= slow_span:
        raise ValueError("fast-span must be smaller than slow-span")
    if not 0 < position_ratio <= 1:
        raise ValueError("position-ratio must be in the range (0, 1]")
    validate_volume_filter(volume_window, min_volume_ratio)

    fast_ema = history["close"].ewm(span=fast_span, adjust=False).mean()
    slow_ema = history["close"].ewm(span=slow_span, adjust=False).mean()
    relative_volume = compute_relative_volume(history["volume"], volume_window)
    buy_signal = (fast_ema > slow_ema) & (fast_ema.shift(1) <= slow_ema.shift(1))
    sell_signal = (fast_ema < slow_ema) & (fast_ema.shift(1) >= slow_ema.shift(1))
    eval_mask, warmup_start_time, start_time, end_time = resolve_eval_window(history["time_key"], eval_start, eval_end)
    eval_history = history.loc[eval_mask].reset_index(drop=True)
    eval_buy_signal = buy_signal.loc[eval_mask].reset_index(drop=True)
    eval_sell_signal = sell_signal.loc[eval_mask].reset_index(drop=True)
    eval_fast_ema = fast_ema.loc[eval_mask].reset_index(drop=True)
    eval_slow_ema = slow_ema.loc[eval_mask].reset_index(drop=True)
    eval_relative_volume = relative_volume.loc[eval_mask].reset_index(drop=True)

    cash = initial_cash
    shares = 0
    trades: list[dict] = []
    equity_points: list[dict] = []

    for row, should_buy, should_sell, fast_value, slow_value, volume_ratio in zip(
        eval_history.itertuples(index=False),
        eval_buy_signal,
        eval_sell_signal,
        eval_fast_ema,
        eval_slow_ema,
        eval_relative_volume,
    ):
        price = float(row.close)
        timestamp = row.time_key

        if shares == 0 and bool(should_buy):
            volume_scale = compute_volume_scale(float(volume_ratio), min_volume_ratio, min_scale=1.0, max_scale=1.25)
            budget = min(cash, cash * position_ratio * volume_scale)
            qty, fee_total, fee_breakdown = compute_buy_quantity_with_fees(
                budget=budget,
                price=price,
                fee_account=fee_account,
                market=market,
                security_type=security_type,
            )
            if qty > 0:
                cash -= qty * price + fee_total
                shares = qty
                trades.append(
                    {
                        "time_key": timestamp,
                        "action": "BUY",
                        "price": price,
                        "shares": qty,
                        "fast_ema": float(fast_value),
                        "slow_ema": float(slow_value),
                        "volume_ratio": float(volume_ratio),
                        "fee": fee_total,
                        "fee_breakdown": fee_breakdown,
                        "cash_after": cash,
                    }
                )
        elif shares > 0 and (bool(should_sell) or (flat_at_close and bool(row.is_day_end))):
            fee_total, fee_breakdown = compute_order_fees(
                fee_account=fee_account,
                market=market,
                side="sell",
                price=price,
                shares=shares,
                security_type=security_type,
            )
            cash += shares * price - fee_total
            trades.append(
                {
                    "time_key": timestamp,
                    "action": "SELL",
                    "price": price,
                        "shares": shares,
                        "fast_ema": float(fast_value),
                        "slow_ema": float(slow_value),
                        "volume_ratio": float(volume_ratio),
                        "fee": fee_total,
                        "fee_breakdown": fee_breakdown,
                        "cash_after": cash,
                    }
                )
            shares = 0

        equity = cash + shares * price
        equity_points.append({"time_key": timestamp, "equity": equity})

    last_price = float(eval_history.iloc[-1]["close"])
    final_value = cash + shares * last_price
    equity_curve = pd.DataFrame(equity_points)
    equity_curve["rolling_peak"] = equity_curve["equity"].cummax()
    equity_curve["drawdown_pct"] = (
        (equity_curve["equity"] - equity_curve["rolling_peak"]) / equity_curve["rolling_peak"] * 100
    )

    summary = {
        "warmup_start_time": warmup_start_time,
        "start_time": start_time,
        "end_time": end_time,
        "data_end_time": history.iloc[-1]["time_key"],
        "initial_cash": initial_cash,
        "fast_span": fast_span,
        "slow_span": slow_span,
        "position_ratio": position_ratio,
        "volume_window": volume_window,
        "min_volume_ratio": min_volume_ratio,
        "flat_at_close": flat_at_close,
        "fee_account": fee_account,
        "market": market,
        "security_type": security_type,
        "trade_count": len(trades),
        "buy_count": sum(1 for trade in trades if trade["action"] == "BUY"),
        "sell_count": sum(1 for trade in trades if trade["action"] == "SELL"),
        "total_fees": sum_trade_fees(trades),
        "ending_cash": cash,
        "ending_shares": shares,
        "last_price": last_price,
        "final_value": final_value,
        "total_return_pct": (final_value / initial_cash - 1) * 100,
        "max_drawdown_pct": equity_curve["drawdown_pct"].min(),
    }
    return summary, pd.DataFrame(trades)


def run_portfolio_backtest(
    histories: dict[str, pd.DataFrame],
    initial_cash: float,
    fast_span: int,
    slow_span: int,
    position_ratio: float,
    volume_window: int,
    min_volume_ratio: float,
    flat_at_close: bool,
    max_open_positions: int,
    eval_start: pd.Timestamp | None = None,
    eval_end: pd.Timestamp | None = None,
    fee_account: str | None = None,
    *,
    market: str,
    security_type: str = "stock",
    pool_cache: MinutePoolFeatureCache | None = None,
) -> tuple[dict, pd.DataFrame]:
    market = normalize_market(market)
    validate_volume_filter(volume_window, min_volume_ratio)
    pool = pool_cache or MinutePoolFeatureCache(histories)
    max_open_positions = normalize_max_open_positions(max_open_positions, len(pool.codes))

    fast_emas = pool.ema(fast_span)
    slow_emas = pool.ema(slow_span)
    volume_ratios = pool.volume_ratio(volume_window)
    buy_signals: list[np.ndarray] = []
    sell_signals: list[np.ndarray] = []
    for code_index in range(len(pool.codes)):
        fast_ema = fast_emas[code_index]
        slow_ema = slow_emas[code_index]
        previous_fast = np.empty_like(fast_ema)
        previous_fast[0] = np.nan
        previous_fast[1:] = fast_ema[:-1]
        previous_slow = np.empty_like(slow_ema)
        previous_slow[0] = np.nan
        previous_slow[1:] = slow_ema[:-1]
        buy_signals.append((fast_ema > slow_ema) & (previous_fast <= previous_slow))
        sell_signals.append((fast_ema < slow_ema) & (previous_fast >= previous_slow))

    window = pool.resolve_window(eval_start, eval_end)
    cash = initial_cash
    positions = np.zeros(len(pool.codes), dtype=np.int64)
    last_prices = np.zeros(len(pool.codes), dtype=float)
    trades: list[dict] = []
    equity_points: list[dict] = []
    open_count = 0

    for timeline_index in window.row_indices:
        ts = pool.timeline[timeline_index]
        row_indices = pool.row_lookup[timeline_index]
        active_codes = np.flatnonzero(row_indices >= 0)
        for code_index in active_codes:
            row_index = int(row_indices[code_index])
            arrays = pool.code_arrays[code_index]
            price = float(arrays.close[row_index])
            last_prices[code_index] = price
            if positions[code_index] > 0 and (
                bool(sell_signals[code_index][row_index]) or (flat_at_close and bool(arrays.is_day_end[row_index]))
            ):
                fee_total, fee_breakdown = compute_order_fees(
                    fee_account=fee_account,
                    market=market,
                    side="sell",
                    price=price,
                    shares=int(positions[code_index]),
                    security_type=security_type,
                )
                cash += int(positions[code_index]) * price - fee_total
                trades.append(
                    {
                        "time_key": ts,
                        "code": pool.codes[code_index],
                        "action": "SELL",
                        "price": price,
                        "shares": int(positions[code_index]),
                        "fast_ema": float(fast_emas[code_index][row_index]),
                        "slow_ema": float(slow_emas[code_index][row_index]),
                        "fee": fee_total,
                        "fee_breakdown": fee_breakdown,
                        "cash_after": cash,
                    }
                )
                positions[code_index] = 0
                open_count -= 1

        slots_left = max_open_positions - open_count
        if slots_left > 0:
            buy_candidates: list[tuple[float, float, int, int]] = []
            for code_index in active_codes:
                if positions[code_index] > 0:
                    continue
                row_index = int(row_indices[code_index])
                if not bool(buy_signals[code_index][row_index]):
                    continue
                buy_candidates.append(
                    (
                        float(fast_emas[code_index][row_index] - slow_emas[code_index][row_index]),
                        float(volume_ratios[code_index][row_index]),
                        code_index,
                        row_index,
                    )
                )

            buy_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            for _, volume_ratio, code_index, row_index in buy_candidates:
                if slots_left <= 0:
                    break
                price = float(pool.code_arrays[code_index].close[row_index])
                remaining_slots = max_open_positions - open_count
                if remaining_slots <= 0:
                    break
                volume_scale = compute_volume_scale(volume_ratio, min_volume_ratio, min_scale=1.0, max_scale=1.25)
                budget = min(cash * position_ratio * volume_scale, cash / remaining_slots)
                qty, fee_total, fee_breakdown = compute_buy_quantity_with_fees(
                    budget=budget,
                    price=price,
                    fee_account=fee_account,
                    market=market,
                    security_type=security_type,
                )
                if qty <= 0:
                    continue
                cash -= qty * price + fee_total
                positions[code_index] = qty
                slots_left -= 1
                open_count += 1
                trades.append(
                    {
                        "time_key": ts,
                        "code": pool.codes[code_index],
                        "action": "BUY",
                        "price": price,
                        "shares": qty,
                        "fast_ema": float(fast_emas[code_index][row_index]),
                        "slow_ema": float(slow_emas[code_index][row_index]),
                        "volume_ratio": float(volume_ratios[code_index][row_index]),
                        "fee": fee_total,
                        "fee_breakdown": fee_breakdown,
                        "cash_after": cash,
                    }
                )

        equity = cash + float(np.dot(positions, last_prices))
        equity_points.append({"time_key": ts, "equity": equity})

    final_value = cash + float(np.dot(positions, last_prices))
    equity_curve = pd.DataFrame(equity_points)
    equity_curve["rolling_peak"] = equity_curve["equity"].cummax()
    equity_curve["drawdown_pct"] = (
        (equity_curve["equity"] - equity_curve["rolling_peak"]) / equity_curve["rolling_peak"] * 100
    )
    summary = {
        "warmup_start_time": window.warmup_start_time,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "data_end_time": pool.timeline[-1],
        "initial_cash": initial_cash,
        "codes": pool.codes,
        "fast_span": fast_span,
        "slow_span": slow_span,
        "position_ratio": position_ratio,
        "volume_window": volume_window,
        "min_volume_ratio": min_volume_ratio,
        "flat_at_close": flat_at_close,
        "max_open_positions": max_open_positions,
        "fee_account": fee_account,
        "market": market,
        "security_type": security_type,
        "trade_count": len(trades),
        "buy_count": sum(1 for trade in trades if trade["action"] == "BUY"),
        "sell_count": sum(1 for trade in trades if trade["action"] == "SELL"),
        "total_fees": sum_trade_fees(trades),
        "ending_cash": cash,
        "ending_positions": {
            pool.codes[code_index]: int(qty) for code_index, qty in enumerate(positions) if int(qty) > 0
        },
        "final_value": final_value,
        "total_return_pct": (final_value / initial_cash - 1) * 100,
        "max_drawdown_pct": equity_curve["drawdown_pct"].min(),
    }
    return summary, pd.DataFrame(trades)


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
        summary, trades = run_portfolio_backtest(
            histories=histories,
            initial_cash=args.initial_cash,
            fast_span=args.fast_span,
            slow_span=args.slow_span,
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
            "ema_cross",
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
