#!/usr/bin/env python3
"""Minute-level RSI reversion strategy with volume confirmation.

Research references consulted while shaping this implementation:

1. Fidelity, "Relative Strength Index (RSI)"
   https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI
   Used for the basic overbought / oversold RSI interpretation and the trend-range notes.

2. Fidelity, "Average Volume"
   https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/average-volume
   Used as background for confirming that reversals occurring on stronger-than-usual volume
   are typically more meaningful than similar price moves on thin volume.

3. Fidelity, "Volume Oscillator (VO)"
   https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/volume-oscillator
   Used as background for comparing current volume against a recent baseline instead of
   treating raw volume in isolation.

This script is a simplified local implementation for the repository's minute-level datasets.
It is not a line-by-line reproduction of any published trading system.
"""

from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from backtest.backtest_common import (
    add_data_source_args,
    add_eval_end_arg,
    add_eval_start_arg,
    add_fee_args,
    add_market_arg,
    add_volume_filter_args,
    compute_buy_quantity_with_fees,
    compute_order_fees,
    compute_relative_volume,
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
from backtest.minute_indicators import compute_rsi
from backtest.minute_pool_cache import MinutePoolFeatureCache


DEFAULT_INITIAL_CASH = 100_000.0
DEFAULT_RSI_PERIOD = 6
DEFAULT_BUY_THRESHOLD = 30.0
DEFAULT_SELL_THRESHOLD = 60.0
DEFAULT_POSITION_RATIO = 1.0
DEFAULT_MAX_OPEN_POSITIONS = -1
DEFAULT_VOLUME_WINDOW = 5
DEFAULT_MIN_VOLUME_RATIO = 0.6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest an RSI reversion strategy on minute-level K-line data."
    )
    add_data_source_args(parser)
    add_fee_args(parser)
    add_market_arg(parser)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--rsi-period", type=int, default=DEFAULT_RSI_PERIOD)
    parser.add_argument("--buy-threshold", type=float, default=DEFAULT_BUY_THRESHOLD)
    parser.add_argument("--sell-threshold", type=float, default=DEFAULT_SELL_THRESHOLD)
    parser.add_argument("--position-ratio", type=float, default=DEFAULT_POSITION_RATIO)
    parser.add_argument("--max-open-positions", type=int, default=DEFAULT_MAX_OPEN_POSITIONS)
    add_eval_start_arg(parser)
    add_eval_end_arg(parser)
    add_volume_filter_args(parser, DEFAULT_VOLUME_WINDOW, DEFAULT_MIN_VOLUME_RATIO, label="buy")
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

def run_backtest(
    history: pd.DataFrame,
    initial_cash: float,
    rsi_period: int,
    buy_threshold: float,
    sell_threshold: float,
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
    if rsi_period <= 0:
        raise ValueError("rsi-period must be positive")
    if not 0 < position_ratio <= 1:
        raise ValueError("position-ratio must be in the range (0, 1]")
    if buy_threshold >= sell_threshold:
        raise ValueError("buy-threshold must be smaller than sell-threshold")
    validate_volume_filter(volume_window, min_volume_ratio)

    rsi = compute_rsi(history["close"], rsi_period)
    relative_volume = compute_relative_volume(history["volume"], volume_window)
    buy_signal = (rsi < buy_threshold) & (rsi.shift(1) >= buy_threshold) & (relative_volume >= min_volume_ratio)
    sell_signal = (rsi > sell_threshold) & (rsi.shift(1) <= sell_threshold)
    eval_mask, warmup_start_time, start_time, end_time = resolve_eval_window(history["time_key"], eval_start, eval_end)
    eval_history = history.loc[eval_mask].reset_index(drop=True)
    eval_buy_signal = buy_signal.loc[eval_mask].reset_index(drop=True)
    eval_sell_signal = sell_signal.loc[eval_mask].reset_index(drop=True)
    eval_rsi = rsi.loc[eval_mask].reset_index(drop=True)
    eval_relative_volume = relative_volume.loc[eval_mask].reset_index(drop=True)

    cash = initial_cash
    shares = 0
    trades: list[dict] = []
    equity_points: list[dict] = []

    for row, should_buy, should_sell, rsi_value, volume_ratio in zip(
        eval_history.itertuples(index=False), eval_buy_signal, eval_sell_signal, eval_rsi, eval_relative_volume
    ):
        price = float(row.close)
        timestamp = row.time_key

        if shares == 0 and bool(should_buy):
            budget = cash * position_ratio
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
                        "rsi": float(rsi_value),
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
                        "rsi": float(rsi_value),
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
        "rsi_period": rsi_period,
        "buy_threshold": buy_threshold,
        "sell_threshold": sell_threshold,
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
    rsi_period: int,
    buy_threshold: float,
    sell_threshold: float,
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

    rsi_values = pool.rsi(rsi_period)
    volume_ratios = pool.volume_ratio(volume_window)
    buy_signals: list[np.ndarray] = []
    sell_signals: list[np.ndarray] = []
    for code_index in range(len(pool.codes)):
        rsi = rsi_values[code_index]
        volume_ratio = volume_ratios[code_index]
        previous_rsi = np.empty_like(rsi)
        previous_rsi[0] = np.nan
        previous_rsi[1:] = rsi[:-1]
        buy_signals.append((rsi < buy_threshold) & (previous_rsi >= buy_threshold) & (volume_ratio >= min_volume_ratio))
        sell_signals.append((rsi > sell_threshold) & (previous_rsi <= sell_threshold))

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
                        "rsi": float(rsi_values[code_index][row_index]),
                        "fee": fee_total,
                        "fee_breakdown": fee_breakdown,
                        "cash_after": cash,
                    }
                )
                positions[code_index] = 0
                open_count -= 1

        slots_left = max_open_positions - open_count
        if slots_left > 0:
            buy_candidates: list[tuple[float, int, int]] = []
            for code_index in active_codes:
                if positions[code_index] > 0:
                    continue
                row_index = int(row_indices[code_index])
                if not bool(buy_signals[code_index][row_index]):
                    continue
                buy_candidates.append((float(rsi_values[code_index][row_index]), code_index, row_index))

            buy_candidates.sort(key=lambda item: item[0])
            for _, code_index, row_index in buy_candidates[:slots_left]:
                price = float(pool.code_arrays[code_index].close[row_index])
                remaining_slots = max_open_positions - open_count
                budget = min(cash * position_ratio, cash / remaining_slots)
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
                open_count += 1
                trades.append(
                    {
                        "time_key": ts,
                        "code": pool.codes[code_index],
                        "action": "BUY",
                        "price": price,
                        "shares": qty,
                        "rsi": float(rsi_values[code_index][row_index]),
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
        "rsi_period": rsi_period,
        "buy_threshold": buy_threshold,
        "sell_threshold": sell_threshold,
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
    args = parse_args()
    eval_start = parse_eval_start(args.eval_start)
    eval_end = parse_eval_end(args.eval_end)
    if args.codes:
        if args.data_dir is not None:
            raise ValueError("--codes cannot be used with --data-dir")
        codes = resolve_codes(args.data_root, args.codes)
        market = validate_market_for_symbols(codes, args.market, label="--codes")
        histories = load_histories(args.data_root, codes)
        summary, trades = run_portfolio_backtest(
            histories=histories,
            initial_cash=args.initial_cash,
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
    print(f"Total fees: {summary['total_fees']:.2f}")
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
