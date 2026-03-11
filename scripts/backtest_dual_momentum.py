#!/usr/bin/env python3
"""Daily dual-momentum stock-pool rotation strategy.

Research references consulted while shaping this simplified implementation:

1. Gary Antonacci, "Risk Premia Harvesting Through Dual Momentum"
   Research index: https://www.optimalmomentum.com/research-papers/
   Used for the high-level idea of combining relative momentum selection with
   an absolute-momentum cash filter.

2. Tobias J. Moskowitz, Yao Hua Ooi, Lasse H. Pedersen, "Time Series Momentum"
   Journal article page: https://www.aqr.com/insights/research/journal-article/time-series-momentum
   Used as background for the trend-following / absolute-momentum side.

3. Alan Moreira, Tyler Muir, "Volatility Managed Portfolios"
   NBER page: https://www.nber.org/papers/w22208
   Reviewed as a possible extension for volatility scaling. The current script
   does not implement volatility targeting; it keeps equal-weight rotation plus
   a cash filter for simplicity.

4. Fidelity, "Average Volume"
   https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/average-volume
   Used as background for comparing current volume against a recent baseline.

5. Fidelity, "Volume Oscillator (VO)"
   https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/volume-oscillator
   Used as background for treating a rise in volume relative to recent history
   as a confirmation signal rather than just looking at raw volume alone.

This script is intentionally a simplified local adaptation for the repository's
daily stock-pool backtests. It is not a line-by-line reproduction of any paper.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

try:
    from .backtest_common import DEFAULT_DATA_ROOT, compute_relative_volume, resolve_codes, validate_volume_filter
except ImportError:
    from backtest_common import DEFAULT_DATA_ROOT, compute_relative_volume, resolve_codes, validate_volume_filter


DEFAULT_INITIAL_CASH = 100_000.0
DEFAULT_LOOKBACK_DAYS = 40
DEFAULT_TOP_N = 1
DEFAULT_VOLUME_WINDOW = 20
DEFAULT_MIN_VOLUME_RATIO = 1.3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest a daily dual-momentum stock-pool rotation strategy."
    )
    parser.add_argument("--codes", nargs="+", required=True, help="Stock pool codes under --data-root.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument(
        "--volume-window",
        type=int,
        default=DEFAULT_VOLUME_WINDOW,
        help="Rolling window used to compare current daily volume against recent average volume.",
    )
    parser.add_argument(
        "--min-volume-ratio",
        type=float,
        default=DEFAULT_MIN_VOLUME_RATIO,
        help="Relative-volume level above which momentum scores receive a volume boost.",
    )
    parser.add_argument(
        "--show-trades",
        type=int,
        default=5,
        help="How many head/tail trades to print. Use 0 to suppress trade samples.",
    )
    return parser.parse_args()


def load_daily_data(data_root: Path, codes: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    price_map: dict[str, pd.Series] = {}
    volume_map: dict[str, pd.Series] = {}
    for code in codes:
        close_parts: list[pd.Series] = []
        volume_parts: list[pd.Series] = []
        for path in sorted((data_root / code).glob("*.csv")):
            daily = pd.read_csv(path, usecols=["time_key", "close", "volume"])
            if daily.empty:
                continue
            trade_date = pd.to_datetime(daily.iloc[-1]["time_key"]).date()
            close_price = float(daily.iloc[-1]["close"])
            total_volume = float(daily["volume"].sum())
            close_parts.append(pd.Series([close_price], index=[trade_date]))
            volume_parts.append(pd.Series([total_volume], index=[trade_date]))
        if not close_parts:
            raise FileNotFoundError(f"No CSV files found in {data_root / code}")
        price_map[code] = pd.concat(close_parts).sort_index()
        volume_map[code] = pd.concat(volume_parts).sort_index()

    prices = pd.DataFrame(price_map).sort_index().ffill()
    volumes = pd.DataFrame(volume_map).sort_index().ffill()
    if prices.empty or volumes.empty:
        raise ValueError("no daily closes loaded")
    return prices, volumes


def select_target_codes(momentum: pd.Series, top_n: int) -> list[str]:
    eligible = momentum.dropna()
    eligible = eligible[eligible > 0]
    if eligible.empty:
        return []
    return eligible.sort_values(ascending=False).head(top_n).index.tolist()


def run_backtest(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    initial_cash: float,
    lookback_days: int,
    top_n: int,
    volume_window: int,
    min_volume_ratio: float,
) -> tuple[dict, pd.DataFrame]:
    if lookback_days <= 0:
        raise ValueError("lookback-days must be positive")
    if top_n <= 0:
        raise ValueError("top-n must be positive")
    validate_volume_filter(volume_window, min_volume_ratio)

    top_n = min(top_n, len(prices.columns))
    relative_volume = volumes.apply(lambda column: compute_relative_volume(column, volume_window))
    cash = initial_cash
    shares = {code: 0 for code in prices.columns}
    trades: list[dict] = []
    equity_points: list[dict] = []
    target_codes: list[str] = []

    for index, (trade_date, close_row) in enumerate(prices.iterrows()):
        if index >= lookback_days:
            momentum = prices.iloc[index] / prices.iloc[index - lookback_days] - 1
            volume_weight = relative_volume.iloc[index].clip(lower=min_volume_ratio, upper=1.5) / min_volume_ratio
            weighted_momentum = momentum.where(momentum > 0) * volume_weight
            target_codes = select_target_codes(weighted_momentum, top_n)

        for code in list(shares):
            qty = shares[code]
            if qty <= 0 or code in target_codes:
                continue
            price = float(close_row[code])
            cash += qty * price
            trades.append(
                {
                    "time_key": trade_date,
                    "code": code,
                    "action": "SELL",
                    "price": price,
                    "shares": qty,
                    "cash_after": cash,
                }
            )
            shares[code] = 0

        if target_codes:
            open_codes = [code for code, qty in shares.items() if qty > 0]
            missing_codes = [code for code in target_codes if shares[code] == 0]
            remaining_slots = len(missing_codes)
            for code in missing_codes:
                price = float(close_row[code])
                if remaining_slots <= 0:
                    break
                budget = cash / remaining_slots
                qty = int(budget // price)
                remaining_slots -= 1
                if qty <= 0:
                    continue
                cash -= qty * price
                shares[code] = qty
                trades.append(
                    {
                        "time_key": trade_date,
                        "code": code,
                        "action": "BUY",
                        "price": price,
                        "shares": qty,
                        "cash_after": cash,
                    }
                )
            open_codes = [code for code, qty in shares.items() if qty > 0]
        else:
            open_codes = []

        equity = cash + sum(int(qty) * float(close_row[code]) for code, qty in shares.items())
        equity_points.append({"time_key": trade_date, "equity": equity, "open_codes": ",".join(sorted(open_codes))})

    equity_curve = pd.DataFrame(equity_points)
    equity_curve["rolling_peak"] = equity_curve["equity"].cummax()
    equity_curve["drawdown_pct"] = (
        (equity_curve["equity"] - equity_curve["rolling_peak"]) / equity_curve["rolling_peak"] * 100
    )
    final_value = float(equity_curve.iloc[-1]["equity"])
    summary = {
        "start_time": prices.index[0],
        "end_time": prices.index[-1],
        "initial_cash": initial_cash,
        "codes": list(prices.columns),
        "lookback_days": lookback_days,
        "top_n": top_n,
        "volume_window": volume_window,
        "min_volume_ratio": min_volume_ratio,
        "trade_count": len(trades),
        "buy_count": sum(1 for trade in trades if trade["action"] == "BUY"),
        "sell_count": sum(1 for trade in trades if trade["action"] == "SELL"),
        "ending_cash": cash,
        "ending_positions": {code: qty for code, qty in shares.items() if qty > 0},
        "final_value": final_value,
        "total_return_pct": (final_value / initial_cash - 1) * 100,
        "max_drawdown_pct": float(equity_curve["drawdown_pct"].min()),
    }
    return summary, pd.DataFrame(trades)


def main() -> int:
    args = parse_args()
    codes = resolve_codes(args.data_root, args.codes)
    prices, volumes = load_daily_data(args.data_root, codes)
    summary, trades = run_backtest(
        prices=prices,
        volumes=volumes,
        initial_cash=args.initial_cash,
        lookback_days=args.lookback_days,
        top_n=args.top_n,
        volume_window=args.volume_window,
        min_volume_ratio=args.min_volume_ratio,
    )

    print(f"Data range: {summary['start_time']} -> {summary['end_time']}")
    print(f"Initial cash: {summary['initial_cash']:.2f}")
    print(
        "Strategy: daily dual momentum "
        f"(lookback {summary['lookback_days']} trading days, top {summary['top_n']}, "
        f"volume boost above {summary['min_volume_ratio']:.2f}x avg({summary['volume_window']}))"
    )
    print(f"Stock pool: {', '.join(summary['codes'])}")
    print(f"Trades: {summary['trade_count']} (BUY {summary['buy_count']}, SELL {summary['sell_count']})")
    print(f"Ending cash: {summary['ending_cash']:.2f}")
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
