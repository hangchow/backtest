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

from backtest.backtest_common import (
    add_eval_end_arg,
    add_eval_start_arg,
    add_fee_args,
    add_market_arg,
    compute_order_fees,
    normalize_market,
    parse_eval_end,
    parse_eval_start,
    resolve_eval_window,
    resolve_codes,
    validate_market_for_symbols,
)
from strategy.dual_momentum import (
    DEFAULT_LONG_LOOKBACK_DAYS,
    DEFAULT_LONG_LOOKBACK_WEIGHT,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MARKET_FILTER_WINDOW,
    DEFAULT_MAX_GROSS_EXPOSURE,
    DEFAULT_MIN_VOLUME_RATIO,
    DEFAULT_TARGET_ANNUAL_VOL,
    DEFAULT_TOP_N,
    DEFAULT_VOLATILITY_WINDOW,
    DEFAULT_VOLUME_WINDOW,
    DualMomentumParams,
    build_dual_momentum_signal,
    compute_volume_boost,
)
from strategy.rebalance import (
    DEFAULT_REBALANCE_BAND_PCT,
    RebalancePolicy,
    build_desired_shares,
    compute_affordable_qty_with_fee,
    compute_portfolio_value,
)


DEFAULT_INITIAL_CASH = 100_000.0
DEFAULT_DAILY_DATA_ROOT = Path("kline_day")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest a daily dual-momentum stock-pool rotation strategy."
    )
    parser.add_argument("--codes", nargs="+", required=True, help="Stock pool codes under --data-root.")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DAILY_DATA_ROOT,
        help="Base directory for per-code daily CSVs. Defaults to kline_day.",
    )
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
    add_eval_end_arg(parser)
    add_fee_args(parser)
    add_market_arg(parser)
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
    parser.add_argument(
        "--max-gross-exposure",
        type=float,
        default=DEFAULT_MAX_GROSS_EXPOSURE,
        help="Maximum gross exposure multiplier (1.0=fully funded, >1 allows bounded leverage).",
    )
    return parser.parse_args()


def load_daily_data(data_root: Path, codes: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    price_map: dict[str, pd.Series] = {}
    volume_map: dict[str, pd.Series] = {}
    for code in codes:
        history_parts: list[pd.DataFrame] = []
        for path in sorted((data_root / code).glob("*.csv")):
            history = pd.read_csv(path, usecols=["time_key", "close", "volume"])
            if history.empty:
                continue
            history_parts.append(history)
        if not history_parts:
            raise FileNotFoundError(f"No CSV files found in {data_root / code}")

        history = pd.concat(history_parts, ignore_index=True)
        history["time_key"] = pd.to_datetime(history["time_key"])
        history = history.sort_values("time_key").drop_duplicates(subset=["time_key"], keep="last").reset_index(drop=True)
        trade_dates = history["time_key"].dt.date
        price_map[code] = pd.Series(history["close"].astype(float).to_numpy(), index=trade_dates)
        volume_map[code] = pd.Series(history["volume"].astype(float).to_numpy(), index=trade_dates)

    prices = pd.DataFrame(price_map).sort_index()
    volumes = pd.DataFrame(volume_map).sort_index()
    if prices.empty or volumes.empty:
        raise ValueError("no daily closes loaded")
    return prices, volumes


def run_backtest(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    initial_cash: float = DEFAULT_INITIAL_CASH,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    long_lookback_days: int = DEFAULT_LONG_LOOKBACK_DAYS,
    long_lookback_weight: float = DEFAULT_LONG_LOOKBACK_WEIGHT,
    top_n: int = DEFAULT_TOP_N,
    volume_window: int = DEFAULT_VOLUME_WINDOW,
    min_volume_ratio: float = DEFAULT_MIN_VOLUME_RATIO,
    market_filter_window: int = DEFAULT_MARKET_FILTER_WINDOW,
    rebalance_band_pct: float = DEFAULT_REBALANCE_BAND_PCT,
    volatility_window: int = DEFAULT_VOLATILITY_WINDOW,
    target_annual_vol: float = DEFAULT_TARGET_ANNUAL_VOL,
    max_gross_exposure: float = DEFAULT_MAX_GROSS_EXPOSURE,
    eval_start: pd.Timestamp | None = None,
    eval_end: pd.Timestamp | None = None,
    fee_account: str | None = None,
    *,
    market: str,
    security_type: str = "stock",
) -> tuple[dict, pd.DataFrame]:
    market = normalize_market(market)
    # 回测入口继续保留原有函数签名，但内部统一转换成 strategy 层的参数对象，
    # 这样 backtest 和 livetrading 会严格共用同一套参数口径和校验逻辑。
    strategy_params = DualMomentumParams(
        lookback_days=lookback_days,
        long_lookback_days=long_lookback_days,
        long_lookback_weight=long_lookback_weight,
        top_n=top_n,
        volume_window=volume_window,
        min_volume_ratio=min_volume_ratio,
        market_filter_window=market_filter_window,
        volatility_window=volatility_window,
        target_annual_vol=target_annual_vol,
        max_gross_exposure=max_gross_exposure,
    )
    strategy_params.validate()
    rebalance_policy = RebalancePolicy(band_pct=rebalance_band_pct)
    rebalance_policy.validate()
    if not prices.index.equals(volumes.index) or not prices.columns.equals(volumes.columns):
        raise ValueError("prices and volumes must share the same index and columns")

    effective_top_n = min(strategy_params.top_n, len(prices.columns))
    # eval window 允许只回测其中一段区间，但信号仍可使用区间之前的数据做 warm-up。
    eval_mask, warmup_start_time, start_time, end_time = resolve_eval_window(prices.index, eval_start, eval_end)
    eval_dates = [trade_date for trade_date, include in zip(prices.index, eval_mask) if include]
    eval_start_date = eval_dates[0]
    eval_end_date = eval_dates[-1]
    cash = initial_cash
    shares = {code: 0 for code in prices.columns}
    trades: list[dict] = []
    equity_points: list[dict] = []
    target_weights: dict[str, float] = {}
    last_prices: dict[str, float] = {}

    for index, (trade_date, close_row) in enumerate(prices.iterrows()):
        # 某些股票当天可能停牌或缺数据，所以这里只拿当日可交易的 code。
        tradable_row = close_row.dropna()
        tradable_codes = set(tradable_row.index)
        for code, price in tradable_row.items():
            last_prices[code] = float(price)

        # 策略信号总是基于“截至当前交易日收盘前已知的全部历史”来算。
        signal = build_dual_momentum_signal(
            prices.iloc[: index + 1],
            volumes.iloc[: index + 1],
            params=strategy_params,
        )
        target_weights = signal.target_weights if signal is not None else {}
        if trade_date < eval_start_date or trade_date > eval_end_date:
            continue

        # 先根据目标权重推导每个标的的理论持仓股数。
        portfolio_value = compute_portfolio_value(cash=cash, positions=shares, prices=last_prices)
        max_gross_notional = portfolio_value
        desired_shares = {code: 0 for code in shares}
        if target_weights:
            # dual momentum 可能因为波动率控制而降低总风险暴露，所以最大总仓位不一定等于组合净值。
            max_gross_notional = portfolio_value * (signal.gross_exposure if signal is not None else 0.0)
            desired_shares = build_desired_shares(
                active_codes=shares.keys(),
                current_positions=shares,
                target_weights=target_weights,
                prices={code: float(price) for code, price in tradable_row.items()},
                portfolio_value=portfolio_value,
                policy=rebalance_policy,
                tradable_codes=tradable_codes,
            )

        # 先卖后买，优先释放现金，也更符合常见回测撮合顺序。
        for code in list(shares):
            qty = shares[code]
            if qty <= desired_shares[code] or code not in tradable_codes:
                continue
            price = float(tradable_row[code])
            sell_qty = qty - desired_shares[code]
            fee_total, fee_breakdown = compute_order_fees(
                fee_account=fee_account,
                market=market,
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

        if target_weights:
            for code in target_weights:
                if code not in tradable_codes:
                    continue
                needed_qty = desired_shares[code] - shares[code]
                if needed_qty <= 0:
                    continue
                price = float(tradable_row[code])
                # 即使策略允许更高 gross exposure，也不能突破剩余杠杆空间和现金约束。
                current_gross_notional = sum(qty * last_prices.get(sym, 0.0) for sym, qty in shares.items())
                remaining_gross_capacity = max(0.0, max_gross_notional - current_gross_notional)
                affordable_qty, fee_total, fee_breakdown = compute_affordable_qty_with_fee(
                    available_cash=cash + remaining_gross_capacity,
                    price=price,
                    desired_qty=needed_qty,
                    fee_account=fee_account,
                    market=market,
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

        # 每个交易日记录一次权益曲线，用于最终收益和回撤统计。
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
        "warmup_start_time": warmup_start_time,
        "start_time": start_time,
        "end_time": end_time,
        "data_end_time": prices.index[-1],
        "initial_cash": initial_cash,
        "codes": list(prices.columns),
        "lookback_days": strategy_params.lookback_days,
        "long_lookback_days": strategy_params.long_lookback_days,
        "long_lookback_weight": strategy_params.long_lookback_weight,
        "top_n": effective_top_n,
        "volume_window": strategy_params.volume_window,
        "min_volume_ratio": strategy_params.min_volume_ratio,
        "market_filter_window": strategy_params.market_filter_window,
        "rebalance_band_pct": rebalance_policy.band_pct,
        "volatility_window": strategy_params.volatility_window,
        "target_annual_vol": strategy_params.target_annual_vol,
        "max_gross_exposure": strategy_params.max_gross_exposure,
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
    market = validate_market_for_symbols(codes, args.market, label="--codes")
    prices, volumes = load_daily_data(args.data_root, codes)
    eval_start = parse_eval_start(args.eval_start)
    eval_end = parse_eval_end(args.eval_end)
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
        max_gross_exposure=args.max_gross_exposure,
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
        "Strategy: daily dual momentum "
        f"(short/long lookback {summary['lookback_days']}/{summary['long_lookback_days']} trading days, "
        f"long-weight {summary['long_lookback_weight']:.2f}, top {summary['top_n']}, "
        f"volume boost above {summary['min_volume_ratio']:.2f}x avg({summary['volume_window']}), "
        f"market filter MA{summary['market_filter_window']}, "
        f"rebalance band {summary['rebalance_band_pct']:.2%}, "
        f"vol target {summary['target_annual_vol']:.2f} ann (window {summary['volatility_window']}), "
        f"max gross exposure {summary['max_gross_exposure']:.2f}x)"
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
