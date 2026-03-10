#!/usr/bin/env python3
from __future__ import annotations

import argparse

import pandas as pd

try:
    from .backtest_common import (
        add_data_source_args,
        load_histories,
        load_history,
        resolve_codes,
        resolve_data_dir,
    )
    from .backtest_rsi_reversion import compute_rsi
except ImportError:
    from backtest_common import add_data_source_args, load_histories, load_history, resolve_codes, resolve_data_dir
    from backtest_rsi_reversion import compute_rsi


DEFAULT_INITIAL_CASH = 100_000.0
DEFAULT_FAST_SPAN = 20
DEFAULT_SLOW_SPAN = 240
DEFAULT_RSI_PERIOD = 6
DEFAULT_BUY_THRESHOLD = 40.0
DEFAULT_SELL_THRESHOLD = 55.0
DEFAULT_POSITION_RATIO = 1.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest an EMA trend filter plus RSI reversion strategy."
    )
    add_data_source_args(parser)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--fast-span", type=int, default=DEFAULT_FAST_SPAN)
    parser.add_argument("--slow-span", type=int, default=DEFAULT_SLOW_SPAN)
    parser.add_argument("--rsi-period", type=int, default=DEFAULT_RSI_PERIOD)
    parser.add_argument("--buy-threshold", type=float, default=DEFAULT_BUY_THRESHOLD)
    parser.add_argument("--sell-threshold", type=float, default=DEFAULT_SELL_THRESHOLD)
    parser.add_argument("--position-ratio", type=float, default=DEFAULT_POSITION_RATIO)
    parser.add_argument("--max-open-positions", type=int, default=4)
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
    rsi_period: int,
    buy_threshold: float,
    sell_threshold: float,
    position_ratio: float,
    flat_at_close: bool,
) -> tuple[dict, pd.DataFrame]:
    if fast_span <= 0 or slow_span <= 0 or rsi_period <= 0:
        raise ValueError("fast-span, slow-span and rsi-period must be positive")
    if fast_span >= slow_span:
        raise ValueError("fast-span must be smaller than slow-span")
    if buy_threshold >= sell_threshold:
        raise ValueError("buy-threshold must be smaller than sell-threshold")
    if not 0 < position_ratio <= 1:
        raise ValueError("position-ratio must be in the range (0, 1]")

    fast_ema = history["close"].ewm(span=fast_span, adjust=False).mean()
    slow_ema = history["close"].ewm(span=slow_span, adjust=False).mean()
    rsi = compute_rsi(history["close"], rsi_period)

    buy_signal = (fast_ema > slow_ema) & (rsi < buy_threshold) & (rsi.shift(1) >= buy_threshold)
    sell_signal = ((rsi > sell_threshold) & (rsi.shift(1) <= sell_threshold)) | (
        (fast_ema < slow_ema) & (fast_ema.shift(1) >= slow_ema.shift(1))
    )

    cash = initial_cash
    shares = 0
    trades: list[dict] = []
    equity_points: list[dict] = []

    for row, should_buy, should_sell, fast_value, slow_value, rsi_value in zip(
        history.itertuples(index=False), buy_signal, sell_signal, fast_ema, slow_ema, rsi
    ):
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
                        "fast_ema": float(fast_value),
                        "slow_ema": float(slow_value),
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
                    "fast_ema": float(fast_value),
                    "slow_ema": float(slow_value),
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
        "fast_span": fast_span,
        "slow_span": slow_span,
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


def run_portfolio_backtest(
    histories: dict[str, pd.DataFrame],
    initial_cash: float,
    fast_span: int,
    slow_span: int,
    rsi_period: int,
    buy_threshold: float,
    sell_threshold: float,
    position_ratio: float,
    flat_at_close: bool,
    max_open_positions: int,
) -> tuple[dict, pd.DataFrame]:
    if max_open_positions <= 0:
        raise ValueError("max-open-positions must be positive")
    if max_open_positions > len(histories):
        max_open_positions = len(histories)

    code_frames: dict[str, pd.DataFrame] = {}
    code_buy: dict[str, pd.Series] = {}
    code_sell: dict[str, pd.Series] = {}
    for code, history in histories.items():
        fast_ema = history["close"].ewm(span=fast_span, adjust=False).mean()
        slow_ema = history["close"].ewm(span=slow_span, adjust=False).mean()
        rsi = compute_rsi(history["close"], rsi_period)
        frame = history.set_index("time_key", drop=False)
        frame["fast_ema"] = fast_ema.values
        frame["slow_ema"] = slow_ema.values
        frame["rsi"] = rsi.values
        code_frames[code] = frame
        code_buy[code] = (
            (fast_ema > slow_ema) & (rsi < buy_threshold) & (rsi.shift(1) >= buy_threshold)
        ).set_axis(history["time_key"])
        code_sell[code] = (
            ((rsi > sell_threshold) & (rsi.shift(1) <= sell_threshold))
            | ((fast_ema < slow_ema) & (fast_ema.shift(1) >= slow_ema.shift(1)))
        ).set_axis(history["time_key"])

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
                cash += positions[code] * price
                trades.append(
                    {
                        "time_key": ts,
                        "code": code,
                        "action": "SELL",
                        "price": price,
                        "shares": positions[code],
                        "fast_ema": float(row["fast_ema"]),
                        "slow_ema": float(row["slow_ema"]),
                        "rsi": float(row["rsi"]),
                        "cash_after": cash,
                    }
                )
                positions[code] = 0

        slots_left = max_open_positions - sum(1 for qty in positions.values() if qty > 0)
        if slots_left > 0:
            for code in sorted(histories):
                if slots_left <= 0:
                    break
                if positions[code] > 0:
                    continue
                frame = code_frames[code]
                if ts not in frame.index or not bool(code_buy[code].get(ts, False)):
                    continue
                row = frame.loc[ts]
                price = float(row["close"])
                budget = min(cash * position_ratio, cash / slots_left)
                qty = int(budget // price)
                if qty <= 0:
                    continue
                cash -= qty * price
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
                        "rsi": float(row["rsi"]),
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
        "rsi_period": rsi_period,
        "buy_threshold": buy_threshold,
        "sell_threshold": sell_threshold,
        "position_ratio": position_ratio,
        "flat_at_close": flat_at_close,
        "max_open_positions": max_open_positions,
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
        summary, trades = run_portfolio_backtest(
            histories=histories,
            initial_cash=args.initial_cash,
            fast_span=args.fast_span,
            slow_span=args.slow_span,
            rsi_period=args.rsi_period,
            buy_threshold=args.buy_threshold,
            sell_threshold=args.sell_threshold,
            position_ratio=args.position_ratio,
            flat_at_close=args.flat_at_close,
            max_open_positions=args.max_open_positions,
        )
    else:
        history = load_history(resolve_data_dir(args.data_dir))
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
        f"EMA({summary['fast_span']}) > EMA({summary['slow_span']}) trend filter + "
        f"RSI({summary['rsi_period']}) buy<{summary['buy_threshold']:.0f} "
        f"sell>{summary['sell_threshold']:.0f}"
    )
    print(f"Position ratio per buy: {summary['position_ratio']:.0%}")
    print(f"Flat at close: {summary['flat_at_close']}")
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
