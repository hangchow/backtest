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
    from .backtest_common import (
        DEFAULT_DATA_ROOT,
        add_eval_start_arg,
        add_fee_args,
        compute_order_fees,
        compute_relative_volume,
        infer_market_from_codes,
        parse_eval_start,
        resolve_codes,
        validate_volume_filter,
    )
except ImportError:
    from backtest_common import (
        DEFAULT_DATA_ROOT,
        add_eval_start_arg,
        add_fee_args,
        compute_order_fees,
        compute_relative_volume,
        infer_market_from_codes,
        parse_eval_start,
        resolve_codes,
        validate_volume_filter,
    )


DEFAULT_INITIAL_CASH = 100_000.0
DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_LONG_LOOKBACK_DAYS = 180
DEFAULT_LONG_LOOKBACK_WEIGHT = 0.25
DEFAULT_TOP_N = 1
DEFAULT_VOLUME_WINDOW = 20
DEFAULT_MIN_VOLUME_RATIO = 1.3
MAX_VOLUME_BOOST_RATIO = 1.5
DEFAULT_MARKET_FILTER_WINDOW = 120
DEFAULT_REBALANCE_BAND_PCT = 0.1
DEFAULT_VOLATILITY_WINDOW = 20
DEFAULT_TARGET_ANNUAL_VOL = 0.30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest a daily dual-momentum stock-pool rotation strategy."
    )
    parser.add_argument("--codes", nargs="+", required=True, help="Stock pool codes under --data-root.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument(
        "--long-lookback-days",
        type=int,
        default=DEFAULT_LONG_LOOKBACK_DAYS,
        help="Secondary lookback horizon to build a blended momentum score.",
    )
    parser.add_argument(
        "--long-lookback-weight",
        type=float,
        default=DEFAULT_LONG_LOOKBACK_WEIGHT,
        help="Weight assigned to the long lookback momentum score in blended ranking.",
    )
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    add_eval_start_arg(parser)
    add_fee_args(parser)
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
        choices=[0, 1],
        default=0,
        help="Whether to print all trade records (1=yes, 0=no).",
    )
    parser.add_argument(
        "--market-filter-window",
        type=int,
        default=DEFAULT_MARKET_FILTER_WINDOW,
        help="Risk-on filter window: only hold risk assets when equal-weight pool is above this MA.",
    )
    parser.add_argument(
        "--rebalance-band-pct",
        type=float,
        default=DEFAULT_REBALANCE_BAND_PCT,
        help="Only rebalance a target when weight gap exceeds this portfolio-level band.",
    )
    parser.add_argument(
        "--volatility-window",
        type=int,
        default=DEFAULT_VOLATILITY_WINDOW,
        help="Rolling window used to estimate daily volatility for position scaling.",
    )
    parser.add_argument(
        "--target-annual-vol",
        type=float,
        default=DEFAULT_TARGET_ANNUAL_VOL,
        help="Annualized volatility target. Lower values reduce gross risk allocation.",
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

    prices = pd.DataFrame(price_map).sort_index()
    volumes = pd.DataFrame(volume_map).sort_index()
    if prices.empty or volumes.empty:
        raise ValueError("no daily closes loaded")
    return prices, volumes


def select_target_codes(momentum: pd.Series, top_n: int) -> list[str]:
    eligible = momentum.dropna()
    eligible = eligible[eligible > 0]
    if eligible.empty:
        return []
    return eligible.sort_values(ascending=False).head(top_n).index.tolist()


def compute_volume_boost(volume_ratio: pd.Series, min_volume_ratio: float) -> pd.Series:
    capped_ratio = volume_ratio.clip(upper=MAX_VOLUME_BOOST_RATIO)
    volume_boost = pd.Series(1.0, index=volume_ratio.index, dtype=float)
    boosted = capped_ratio >= min_volume_ratio
    volume_boost.loc[boosted] = capped_ratio.loc[boosted] / min_volume_ratio
    return volume_boost.where(volume_ratio.notna())


def _compute_affordable_qty_with_fee(
    cash: float,
    price: float,
    needed_qty: int,
    fee_account: str | None,
    market: str,
    security_type: str,
) -> tuple[int, float, dict[str, float]]:
    qty = min(needed_qty, int(cash // price))
    while qty > 0:
        fee_total, fee_breakdown = compute_order_fees(
            fee_account=fee_account,
            market=market,
            side="buy",
            price=price,
            shares=qty,
            security_type=security_type,
        )
        if qty * price + fee_total <= cash + 1e-9:
            return qty, fee_total, fee_breakdown
        qty -= 1
    return 0, 0.0, {}


def run_backtest(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    initial_cash: float,
    lookback_days: int,
    long_lookback_days: int,
    long_lookback_weight: float,
    top_n: int,
    volume_window: int,
    min_volume_ratio: float,
    market_filter_window: int,
    rebalance_band_pct: float,
    volatility_window: int,
    target_annual_vol: float,
    eval_start: pd.Timestamp | None = None,
    fee_account: str | None = None,
    market: str | None = None,
    security_type: str = "stock",
) -> tuple[dict, pd.DataFrame]:
    if lookback_days <= 0:
        raise ValueError("lookback-days must be positive")
    if long_lookback_days <= 0:
        raise ValueError("long-lookback-days must be positive")
    if not 0 <= long_lookback_weight <= 1:
        raise ValueError("long-lookback-weight must be within [0, 1]")
    if top_n <= 0:
        raise ValueError("top-n must be positive")
    if market_filter_window <= 0:
        raise ValueError("market-filter-window must be positive")
    if not 0 <= rebalance_band_pct <= 1:
        raise ValueError("rebalance-band-pct must be within [0, 1]")
    if volatility_window <= 1:
        raise ValueError("volatility-window must be > 1")
    if target_annual_vol <= 0:
        raise ValueError("target-annual-vol must be positive")
    validate_volume_filter(volume_window, min_volume_ratio)
    if not prices.index.equals(volumes.index) or not prices.columns.equals(volumes.columns):
        raise ValueError("prices and volumes must share the same index and columns")
    if fee_account and not market:
        raise ValueError("market is required when fee-account is enabled")

    top_n = min(top_n, len(prices.columns))
    eval_start_date = eval_start.date() if eval_start is not None else None
    eval_dates = [trade_date for trade_date in prices.index if eval_start_date is None or trade_date >= eval_start_date]
    if not eval_dates:
        raise ValueError("eval-start is after the available data range")
    relative_volume = volumes.apply(lambda column: compute_relative_volume(column, volume_window))
    pool_close = prices.mean(axis=1)
    pool_ma = pool_close.rolling(window=market_filter_window, min_periods=market_filter_window).mean()
    daily_pool_returns = pool_close.pct_change()
    realized_daily_vol = daily_pool_returns.rolling(window=volatility_window, min_periods=volatility_window).std()
    cash = initial_cash
    shares = {code: 0 for code in prices.columns}
    trades: list[dict] = []
    equity_points: list[dict] = []
    target_codes: list[str] = []
    last_prices: dict[str, float] = {}

    for index, (trade_date, close_row) in enumerate(prices.iterrows()):
        tradable_row = close_row.dropna()
        tradable_codes = set(tradable_row.index)
        for code, price in tradable_row.items():
            last_prices[code] = float(price)

        if index >= lookback_days:
            short_momentum = prices.iloc[index] / prices.iloc[index - lookback_days] - 1
            long_momentum = pd.Series(0.0, index=prices.columns)
            if index >= long_lookback_days:
                long_momentum = prices.iloc[index] / prices.iloc[index - long_lookback_days] - 1
            blended_momentum = short_momentum * (1 - long_lookback_weight) + long_momentum * long_lookback_weight
            volume_weight = compute_volume_boost(relative_volume.iloc[index], min_volume_ratio)
            weighted_momentum = blended_momentum.where(blended_momentum > 0) * volume_weight
            candidate_codes = select_target_codes(weighted_momentum, top_n)
            market_is_risk_on = bool(pd.notna(pool_ma.iloc[index]) and pool_close.iloc[index] >= pool_ma.iloc[index])
            target_codes = candidate_codes if market_is_risk_on else []
        if eval_start_date is not None and trade_date < eval_start_date:
            continue

        desired_shares = {code: 0 for code in shares}
        portfolio_value = cash + sum(qty * last_prices.get(code, 0.0) for code, qty in shares.items())
        if target_codes:
            target_vol_multiplier = 1.0
            if pd.notna(realized_daily_vol.iloc[index]) and realized_daily_vol.iloc[index] > 0:
                annualized_vol = float(realized_daily_vol.iloc[index]) * (252**0.5)
                target_vol_multiplier = min(1.0, target_annual_vol / annualized_vol)
            investable_value = portfolio_value * target_vol_multiplier
            target_value = investable_value / len(target_codes)
            for code in target_codes:
                if code not in tradable_codes:
                    desired_shares[code] = shares[code]
                    continue
                price = float(tradable_row[code])
                desired_qty = int(target_value // price)
                delta_value = abs(desired_qty - shares[code]) * price
                if portfolio_value > 0 and (delta_value / portfolio_value) < rebalance_band_pct:
                    desired_qty = shares[code]
                desired_shares[code] = desired_qty

        for code in list(shares):
            qty = shares[code]
            if qty <= desired_shares[code] or code not in tradable_codes:
                continue
            price = float(tradable_row[code])
            sell_qty = qty - desired_shares[code]
            fee_total, fee_breakdown = compute_order_fees(
                fee_account=fee_account,
                market=market if market is not None else "",
                side="sell",
                price=price,
                shares=sell_qty,
                security_type=security_type,
            )
            cash += sell_qty * price - fee_total
            trades.append(
                {
                    "time_key": trade_date,
                    "code": code,
                    "action": "SELL",
                    "price": price,
                    "shares": sell_qty,
                    "fee_total": fee_total,
                    "fee_breakdown": fee_breakdown,
                    "cash_after": cash,
                }
            )
            shares[code] -= sell_qty

        if target_codes:
            for code in target_codes:
                if code not in tradable_codes:
                    continue
                needed_qty = desired_shares[code] - shares[code]
                if needed_qty <= 0:
                    continue
                price = float(tradable_row[code])
                affordable_qty, fee_total, fee_breakdown = _compute_affordable_qty_with_fee(
                    cash=cash,
                    price=price,
                    needed_qty=needed_qty,
                    fee_account=fee_account,
                    market=market if market is not None else "",
                    security_type=security_type,
                )
                if affordable_qty <= 0:
                    continue
                cash -= affordable_qty * price + fee_total
                shares[code] += affordable_qty
                trades.append(
                    {
                        "time_key": trade_date,
                        "code": code,
                        "action": "BUY",
                        "price": price,
                        "shares": affordable_qty,
                        "fee_total": fee_total,
                        "fee_breakdown": fee_breakdown,
                        "cash_after": cash,
                    }
                )

        open_codes = [code for code, qty in shares.items() if qty > 0]
        equity = cash + sum(qty * last_prices.get(code, 0.0) for code, qty in shares.items())
        equity_points.append({"time_key": trade_date, "equity": equity, "open_codes": ",".join(sorted(open_codes))})

    equity_curve = pd.DataFrame(equity_points)
    equity_curve["rolling_peak"] = equity_curve["equity"].cummax()
    equity_curve["drawdown_pct"] = (
        (equity_curve["equity"] - equity_curve["rolling_peak"]) / equity_curve["rolling_peak"] * 100
    )
    final_value = float(equity_curve.iloc[-1]["equity"])
    summary = {
        "warmup_start_time": prices.index[0],
        "start_time": eval_dates[0],
        "end_time": prices.index[-1],
        "initial_cash": initial_cash,
        "codes": list(prices.columns),
        "lookback_days": lookback_days,
        "long_lookback_days": long_lookback_days,
        "long_lookback_weight": long_lookback_weight,
        "top_n": top_n,
        "volume_window": volume_window,
        "min_volume_ratio": min_volume_ratio,
        "market_filter_window": market_filter_window,
        "rebalance_band_pct": rebalance_band_pct,
        "volatility_window": volatility_window,
        "target_annual_vol": target_annual_vol,
        "fee_account": fee_account,
        "market": market,
        "security_type": security_type,
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
    eval_start = parse_eval_start(args.eval_start)
    market = infer_market_from_codes(codes)
    summary, trades = run_backtest(
        prices=prices,
        volumes=volumes,
        initial_cash=args.initial_cash,
        lookback_days=args.lookback_days,
        long_lookback_days=args.long_lookback_days,
        long_lookback_weight=args.long_lookback_weight,
        top_n=args.top_n,
        volume_window=args.volume_window,
        min_volume_ratio=args.min_volume_ratio,
        market_filter_window=args.market_filter_window,
        rebalance_band_pct=args.rebalance_band_pct,
        volatility_window=args.volatility_window,
        target_annual_vol=args.target_annual_vol,
        eval_start=eval_start,
        fee_account=args.fee_account,
        market=market,
        security_type=args.security_type,
    )

    print(f"Data range: {summary['warmup_start_time']} -> {summary['end_time']}")
    if summary["warmup_start_time"] != summary["start_time"]:
        print(f"Evaluation range: {summary['start_time']} -> {summary['end_time']}")
    print(f"Initial cash: {summary['initial_cash']:.2f}")
    print(
        "Strategy: daily dual momentum "
        f"(short/long lookback {summary['lookback_days']}/{summary['long_lookback_days']} trading days, "
        f"long-weight {summary['long_lookback_weight']:.2f}, top {summary['top_n']}, "
        f"volume boost above {summary['min_volume_ratio']:.2f}x avg({summary['volume_window']}), "
        f"market filter MA{summary['market_filter_window']}, "
        f"rebalance band {summary['rebalance_band_pct']:.2%}, "
        f"vol target {summary['target_annual_vol']:.2f} ann (window {summary['volatility_window']}))"
    )
    if summary["fee_account"]:
        print(f"Fee account: {summary['fee_account']}")
        print(f"Market/Security: {summary['market']} / {summary['security_type']}")
    print(f"Stock pool: {', '.join(summary['codes'])}")
    print(f"Trades: {summary['trade_count']} (BUY {summary['buy_count']}, SELL {summary['sell_count']})")
    print(f"Ending cash: {summary['ending_cash']:.2f}")
    print(f"Ending positions: {summary['ending_positions']}")
    print(f"Final value: {summary['final_value']:.2f}")
    print(f"Total return: {summary['total_return_pct']:.2f}%")
    print(f"Max drawdown: {summary['max_drawdown_pct']:.2f}%")

    if args.show_trades == 1:
        if trades.empty:
            print("\nNo trades.")
        else:
            print("\nAll trades:")
            print(trades.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
