#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.backtest_dual_momentum import load_daily_data, run_backtest as run_baseline
from backtest.backtest_common import (
    add_eval_end_arg,
    add_eval_start_arg,
    add_fee_args,
    compute_order_fees,
    infer_market_from_codes,
    parse_eval_end,
    parse_eval_start,
    resolve_codes,
    resolve_eval_window,
)
from strategy.dual_momentum_v2 import DualMomentumV2Params, build_dual_momentum_v2_signal
from strategy.rebalance import (
    DEFAULT_REBALANCE_BAND_PCT,
    RebalancePolicy,
    build_desired_shares,
    compute_affordable_qty_with_fee,
    compute_portfolio_value,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Dual momentum v2 backtest with baseline comparison")
    p.add_argument("--codes", nargs="+", required=True)
    p.add_argument("--data-root", type=Path, default=Path("kline_day"))
    p.add_argument("--initial-cash", type=float, default=800000)
    p.add_argument("--lookback-days", type=int, default=40)
    p.add_argument("--long-lookback-days", type=int, default=120)
    p.add_argument("--momentum-skip-days", type=int, default=5)
    p.add_argument("--long-lookback-weight", type=float, default=0.35)
    p.add_argument("--top-n", type=int, default=2)
    p.add_argument("--volume-window", type=int, default=20)
    p.add_argument("--min-volume-ratio", type=float, default=1.0)
    p.add_argument("--market-filter-window", type=int, default=80)
    p.add_argument("--market-trend-window", type=int, default=20)
    p.add_argument("--asset-filter-window", type=int, default=60)
    p.add_argument("--rebalance-band-pct", type=float, default=DEFAULT_REBALANCE_BAND_PCT)
    p.add_argument("--volatility-window", type=int, default=20)
    p.add_argument("--target-annual-vol", type=float, default=0.35)
    p.add_argument("--max-gross-exposure", type=float, default=1.2)
    p.add_argument("--show-trades", type=int, choices=[0, 1], default=0)
    p.add_argument("--compare-baseline", type=int, choices=[0, 1], default=1)
    add_eval_start_arg(p)
    add_eval_end_arg(p)
    add_fee_args(p)
    return p.parse_args()


def run_backtest_v2(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    *,
    params: DualMomentumV2Params,
    initial_cash: float,
    rebalance_band_pct: float,
    eval_start: pd.Timestamp | None,
    eval_end: pd.Timestamp | None,
    fee_account: str | None,
    market: str | None,
    security_type: str,
):
    eval_mask, warmup_start_time, start_time, end_time = resolve_eval_window(prices.index, eval_start, eval_end)
    eval_dates = [d for d, ok in zip(prices.index, eval_mask) if ok]
    eval_start_date = eval_dates[0]
    eval_end_date = eval_dates[-1]

    policy = RebalancePolicy(band_pct=rebalance_band_pct)
    policy.validate()

    cash = initial_cash
    shares = {c: 0 for c in prices.columns}
    last_prices: dict[str, float] = {}
    trades: list[dict] = []
    equity_points: list[dict] = []

    for idx, (trade_date, close_row) in enumerate(prices.iterrows()):
        tradable_row = close_row.dropna()
        tradable_codes = set(tradable_row.index)
        for code, px in tradable_row.items():
            last_prices[code] = float(px)

        signal = build_dual_momentum_v2_signal(prices.iloc[: idx + 1], volumes.iloc[: idx + 1], params)
        target_weights = signal.target_weights if signal is not None else {}

        if trade_date < eval_start_date or trade_date > eval_end_date:
            continue

        portfolio_value = compute_portfolio_value(cash=cash, positions=shares, prices=last_prices)
        max_gross_notional = portfolio_value
        desired_shares = {code: 0 for code in shares}
        if target_weights:
            max_gross_notional = portfolio_value * (signal.gross_exposure if signal is not None else 0.0)
            desired_shares = build_desired_shares(
                active_codes=shares.keys(),
                current_positions=shares,
                target_weights=target_weights,
                prices={code: float(price) for code, price in tradable_row.items()},
                portfolio_value=portfolio_value,
                policy=policy,
                tradable_codes=tradable_codes,
            )

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
            shares[code] -= sell_qty
            trades.append({"time_key": trade_date, "code": code, "action": "SELL", "price": price, "shares": sell_qty, "fee_total": fee_total, "fee_breakdown": fee_breakdown, "cash_after": cash})

        for code in target_weights:
            if code not in tradable_codes:
                continue
            need = desired_shares[code] - shares[code]
            if need <= 0:
                continue
            price = float(tradable_row[code])
            current_gross = sum(qty * last_prices.get(sym, 0.0) for sym, qty in shares.items())
            capacity = max(0.0, max_gross_notional - current_gross)
            buy_qty, fee_total, fee_breakdown = compute_affordable_qty_with_fee(
                available_cash=cash + capacity,
                price=price,
                desired_qty=need,
                fee_account=fee_account,
                market=market if market is not None else "",
                security_type=security_type,
            )
            if buy_qty <= 0:
                continue
            cash -= buy_qty * price + fee_total
            shares[code] += buy_qty
            trades.append({"time_key": trade_date, "code": code, "action": "BUY", "price": price, "shares": buy_qty, "fee_total": fee_total, "fee_breakdown": fee_breakdown, "cash_after": cash})

        equity = cash + sum(qty * last_prices.get(c, 0.0) for c, qty in shares.items())
        equity_points.append({"time_key": trade_date, "equity": equity})

    eq = pd.DataFrame(equity_points)
    eq["rolling_peak"] = eq["equity"].cummax()
    eq["drawdown_pct"] = (eq["equity"] - eq["rolling_peak"]) / eq["rolling_peak"] * 100
    final_value = float(eq.iloc[-1]["equity"])
    return {
        "warmup_start_time": warmup_start_time,
        "start_time": start_time,
        "end_time": end_time,
        "final_value": final_value,
        "total_return_pct": (final_value / initial_cash - 1) * 100,
        "max_drawdown_pct": float(eq["drawdown_pct"].min()),
        "trade_count": len(trades),
    }, pd.DataFrame(trades)


def main() -> int:
    args = parse_args()
    codes = resolve_codes(args.data_root, args.codes)
    prices, volumes = load_daily_data(args.data_root, codes)
    eval_start = parse_eval_start(args.eval_start)
    eval_end = parse_eval_end(args.eval_end)
    market = infer_market_from_codes(codes)

    params = DualMomentumV2Params(
        lookback_days=args.lookback_days,
        long_lookback_days=args.long_lookback_days,
        momentum_skip_days=args.momentum_skip_days,
        long_lookback_weight=args.long_lookback_weight,
        top_n=args.top_n,
        volume_window=args.volume_window,
        min_volume_ratio=args.min_volume_ratio,
        market_filter_window=args.market_filter_window,
        market_trend_window=args.market_trend_window,
        asset_filter_window=args.asset_filter_window,
        volatility_window=args.volatility_window,
        target_annual_vol=args.target_annual_vol,
        max_gross_exposure=args.max_gross_exposure,
    )
    v2_summary, v2_trades = run_backtest_v2(
        prices,
        volumes,
        params=params,
        initial_cash=args.initial_cash,
        rebalance_band_pct=args.rebalance_band_pct,
        eval_start=eval_start,
        eval_end=eval_end,
        fee_account=args.fee_account,
        market=market,
        security_type=args.security_type,
    )

    print("V2 result")
    print(f"Return: {v2_summary['total_return_pct']:.2f}%  MDD: {v2_summary['max_drawdown_pct']:.2f}%  Trades: {v2_summary['trade_count']}")

    if args.compare_baseline == 1:
        base_summary, _ = run_baseline(
            prices=prices,
            volumes=volumes,
            initial_cash=args.initial_cash,
            lookback_days=40,
            long_lookback_days=120,
            long_lookback_weight=0.25,
            top_n=1,
            volume_window=20,
            min_volume_ratio=1.0,
            market_filter_window=60,
            rebalance_band_pct=args.rebalance_band_pct,
            volatility_window=20,
            target_annual_vol=0.60,
            max_gross_exposure=1.20,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=args.fee_account,
            market=market,
            security_type=args.security_type,
        )
        print("Baseline result")
        print(f"Return: {base_summary['total_return_pct']:.2f}%  MDD: {base_summary['max_drawdown_pct']:.2f}%  Trades: {base_summary['trade_count']}")
        print(f"Excess return (V2 - Baseline): {v2_summary['total_return_pct'] - base_summary['total_return_pct']:.2f}%")

    if args.show_trades == 1 and not v2_trades.empty:
        print(v2_trades.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
