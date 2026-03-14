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

import pandas as pd

try:
    from .backtest_common import (
        add_data_source_args,
        add_fee_args,
        compute_buy_quantity_with_fees,
        compute_order_fees,
        compute_relative_volume,
        compute_volume_scale,
        infer_market_from_codes,
        load_histories,
        load_history,
        normalize_max_open_positions,
        resolve_codes,
        resolve_data_dir,
        validate_volume_filter,
    )
except ImportError:
    from backtest_common import (
        add_data_source_args,
        add_fee_args,
        compute_buy_quantity_with_fees,
        compute_order_fees,
        compute_relative_volume,
        compute_volume_scale,
        infer_market_from_codes,
        load_histories,
        load_history,
        normalize_max_open_positions,
        resolve_codes,
        resolve_data_dir,
        validate_volume_filter,
    )


DEFAULT_INITIAL_CASH = 100_000.0
DEFAULT_FAST_SPAN = 30
DEFAULT_SLOW_SPAN = 120
DEFAULT_POSITION_RATIO = 0.5
DEFAULT_MAX_OPEN_POSITIONS = 2
DEFAULT_VOLUME_WINDOW = 5
DEFAULT_MIN_VOLUME_RATIO = 0.6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest an EMA cross strategy on minute-level K-line data."
    )
    add_data_source_args(parser)
    add_fee_args(parser)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--fast-span", type=int, default=DEFAULT_FAST_SPAN)
    parser.add_argument("--slow-span", type=int, default=DEFAULT_SLOW_SPAN)
    parser.add_argument("--position-ratio", type=float, default=DEFAULT_POSITION_RATIO)
    parser.add_argument("--max-open-positions", type=int, default=DEFAULT_MAX_OPEN_POSITIONS)
    parser.add_argument(
        "--volume-window",
        type=int,
        default=DEFAULT_VOLUME_WINDOW,
        help="Rolling window used to compare current volume against recent average volume.",
    )
    parser.add_argument(
        "--min-volume-ratio",
        type=float,
        default=DEFAULT_MIN_VOLUME_RATIO,
        help="Relative-volume level above which crossover entries can scale above the base position size.",
    )
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
    fast_span: int,
    slow_span: int,
    position_ratio: float,
    volume_window: int,
    min_volume_ratio: float,
    flat_at_close: bool,
    fee_account: str | None = None,
    market: str = "US",
    security_type: str = "stock",
) -> tuple[dict, pd.DataFrame]:
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

    cash = initial_cash
    shares = 0
    trades: list[dict] = []
    equity_points: list[dict] = []

    for row, should_buy, should_sell, fast_value, slow_value, volume_ratio in zip(
        history.itertuples(index=False), buy_signal, sell_signal, fast_ema, slow_ema, relative_volume
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
    fee_account: str | None = None,
    market: str = "US",
    security_type: str = "stock",
) -> tuple[dict, pd.DataFrame]:
    max_open_positions = normalize_max_open_positions(max_open_positions, len(histories))
    validate_volume_filter(volume_window, min_volume_ratio)

    code_frames: dict[str, pd.DataFrame] = {}
    code_buy: dict[str, pd.Series] = {}
    code_sell: dict[str, pd.Series] = {}
    for code, history in histories.items():
        fast_ema = history["close"].ewm(span=fast_span, adjust=False).mean()
        slow_ema = history["close"].ewm(span=slow_span, adjust=False).mean()
        relative_volume = compute_relative_volume(history["volume"], volume_window)
        frame = history.set_index("time_key", drop=False)
        frame["fast_ema"] = fast_ema.values
        frame["slow_ema"] = slow_ema.values
        frame["volume_ratio"] = relative_volume.values
        code_frames[code] = frame
        code_buy[code] = ((fast_ema > slow_ema) & (fast_ema.shift(1) <= slow_ema.shift(1))).set_axis(history["time_key"])
        code_sell[code] = ((fast_ema < slow_ema) & (fast_ema.shift(1) >= slow_ema.shift(1))).set_axis(history["time_key"])

    timeline = sorted({ts for frame in code_frames.values() for ts in frame.index})
    cash = initial_cash
    positions = {code: 0 for code in histories}
    last_prices: dict[str, float] = {}
    trades: list[dict] = []
    equity_points: list[dict] = []

    for ts in timeline:
        for code in sorted(histories):
            frame = code_frames[code]
            if ts not in frame.index:
                continue
            row = frame.loc[ts]
            price = float(row["close"])
            last_prices[code] = price
            if positions[code] > 0 and (bool(code_sell[code].get(ts, False)) or (flat_at_close and bool(row["is_day_end"]))):
                fee_total, fee_breakdown = compute_order_fees(
                    fee_account=fee_account,
                    market=market,
                    side="sell",
                    price=price,
                    shares=positions[code],
                    security_type=security_type,
                )
                cash += positions[code] * price - fee_total
                trades.append(
                    {
                        "time_key": ts,
                        "code": code,
                        "action": "SELL",
                        "price": price,
                        "shares": positions[code],
                        "fast_ema": float(row["fast_ema"]),
                        "slow_ema": float(row["slow_ema"]),
                        "fee": fee_total,
                        "fee_breakdown": fee_breakdown,
                        "cash_after": cash,
                    }
                )
                positions[code] = 0

        slots_left = max_open_positions - sum(1 for qty in positions.values() if qty > 0)
        if slots_left > 0:
            buy_candidates: list[tuple[float, float, str, pd.Series]] = []
            for code in sorted(histories):
                if positions[code] > 0:
                    continue
                frame = code_frames[code]
                if ts not in frame.index or not bool(code_buy[code].get(ts, False)):
                    continue
                row = frame.loc[ts]
                volume_ratio = float(row["volume_ratio"])
                score = float(row["fast_ema"] - row["slow_ema"])
                buy_candidates.append((score, volume_ratio, code, row))

            buy_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            for _, volume_ratio, code, row in buy_candidates:
                if slots_left <= 0:
                    break
                price = float(row["close"])
                remaining_slots = max_open_positions - sum(1 for qty in positions.values() if qty > 0)
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
                positions[code] = qty
                slots_left -= 1
                trades.append(
                    {
                        "time_key": ts,
                        "code": code,
                        "action": "BUY",
                        "price": price,
                        "shares": qty,
                        "fast_ema": float(row["fast_ema"]),
                        "slow_ema": float(row["slow_ema"]),
                        "volume_ratio": float(row["volume_ratio"]),
                        "fee": fee_total,
                        "fee_breakdown": fee_breakdown,
                        "cash_after": cash,
                    }
                )

        equity = cash + sum(qty * last_prices.get(code, 0.0) for code, qty in positions.items())
        equity_points.append({"time_key": ts, "equity": equity})

    final_value = cash + sum(qty * last_prices.get(code, 0.0) for code, qty in positions.items())
    equity_curve = pd.DataFrame(equity_points)
    equity_curve["rolling_peak"] = equity_curve["equity"].cummax()
    equity_curve["drawdown_pct"] = (
        (equity_curve["equity"] - equity_curve["rolling_peak"]) / equity_curve["rolling_peak"] * 100
    )
    summary = {
        "start_time": timeline[0],
        "end_time": timeline[-1],
        "initial_cash": initial_cash,
        "codes": sorted(histories),
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
        "ending_cash": cash,
        "ending_positions": {code: qty for code, qty in positions.items() if qty > 0},
        "final_value": final_value,
        "total_return_pct": (final_value / initial_cash - 1) * 100,
        "max_drawdown_pct": equity_curve["drawdown_pct"].min(),
    }
    return summary, pd.DataFrame(trades)


def main() -> int:
    args = parse_args()
    if args.codes:
        if args.data_dir is not None:
            raise ValueError("--codes cannot be used with --data-dir")
        codes = resolve_codes(args.data_root, args.codes)
        histories = load_histories(args.data_root, codes)
        market = infer_market_from_codes(codes)
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
            fee_account=args.fee_account,
            market=market,
            security_type=args.security_type,
        )
    else:
        data_dir = resolve_data_dir(args.data_dir)
        history = load_history(data_dir)
        market = infer_market_from_codes([data_dir.name])
        summary, trades = run_backtest(
            history=history,
            initial_cash=args.initial_cash,
            fast_span=args.fast_span,
            slow_span=args.slow_span,
            position_ratio=args.position_ratio,
            volume_window=args.volume_window,
            min_volume_ratio=args.min_volume_ratio,
            flat_at_close=args.flat_at_close,
            fee_account=args.fee_account,
            market=market,
            security_type=args.security_type,
        )

    print(f"Data range: {summary['start_time']} -> {summary['end_time']}")
    print(f"Initial cash: {summary['initial_cash']:.2f}")
    print(f"Strategy: EMA({summary['fast_span']}) / EMA({summary['slow_span']}) cross")
    print(f"Position ratio per buy: {summary['position_ratio']:.0%}")
    print(
        f"Volume sizing: bars above {summary['min_volume_ratio']:.2f}x "
        f"avg({summary['volume_window']}) can scale orders above the base size"
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
