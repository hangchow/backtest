#!/usr/bin/env python3
"""Monthly momentum stock-pool rotation (current backtest accounting, HK preset).

Research idea used here: low-frequency cross-sectional momentum rotation
(formation lookback 20 trading days, monthly rebalance) inspired by
Jegadeesh & Titman style momentum effects, adapted to repository accounting.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter

import pandas as pd

from backtest.backtest_common import (
    add_eval_end_arg,
    add_eval_start_arg,
    add_fee_args,
    add_market_arg,
    compute_order_fees,
    FilesystemLoadTracker,
    normalize_market,
    parse_eval_end,
    parse_eval_start,
    resolve_codes,
    resolve_eval_window,
    sum_trade_fees,
    validate_market_for_symbols,
)
from backtest.backtest_dual_momentum import load_daily_data, run_backtest as run_baseline
from backtest.reporting import (
    build_strategy_summary_row,
    build_strategy_summary_table,
    observations_by_code_from_frame,
    render_single_strategy_report,
)
from backtest.strategy_config import add_strategy_config_arg, resolve_single_strategy_defaults
from strategy.rebalance import (
    RebalancePolicy,
    build_desired_shares,
    compute_affordable_qty_with_fee,
    compute_portfolio_value,
)


DEFAULT_INITIAL_CASH = 800_000.0
DEFAULT_LOOKBACK_DAYS = 20
DEFAULT_TOP_N = 1
DEFAULT_REBALANCE_BAND_PCT = 0.02


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    config_defaults = resolve_single_strategy_defaults(
        "momentum_monthly",
        {
            "lookback_days": DEFAULT_LOOKBACK_DAYS,
            "top_n": DEFAULT_TOP_N,
            "rebalance_band_pct": DEFAULT_REBALANCE_BAND_PCT,
        },
        argv=argv,
    )
    p = argparse.ArgumentParser(description="Monthly momentum rotation backtest with baseline comparison")
    add_strategy_config_arg(p)
    p.add_argument("--codes", nargs="+", required=True)
    p.add_argument("--data-root", type=Path, default=Path("kline_day"))
    p.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    p.add_argument("--lookback-days", type=int, default=config_defaults["lookback_days"])
    p.add_argument("--top-n", type=int, default=config_defaults["top_n"])
    p.add_argument("--rebalance-band-pct", type=float, default=config_defaults["rebalance_band_pct"])
    p.add_argument("--compare-baseline", type=int, choices=[0, 1], default=1)
    add_eval_start_arg(p)
    add_eval_end_arg(p)
    add_fee_args(p)
    add_market_arg(p)
    return p.parse_args(argv)


def run_monthly_momentum(
    prices: pd.DataFrame,
    *,
    initial_cash: float,
    lookback_days: int,
    top_n: int,
    rebalance_band_pct: float,
    eval_start: pd.Timestamp | None,
    eval_end: pd.Timestamp | None,
    fee_account: str | None,
    market: str,
    security_type: str,
) -> tuple[dict, pd.DataFrame]:
    market = normalize_market(market)
    eval_mask, warmup_start_time, start_time, end_time = resolve_eval_window(prices.index, eval_start, eval_end)
    eval_dates = [d for d, ok in zip(prices.index, eval_mask) if ok]
    eval_start_date = eval_dates[0]
    eval_end_date = eval_dates[-1]

    cash = initial_cash
    shares = {code: 0 for code in prices.columns}
    last_prices: dict[str, float] = {}
    trades: list[dict] = []
    equity_points: list[dict] = []
    policy = RebalancePolicy(band_pct=rebalance_band_pct)

    prev_month: tuple[int, int] | None = None
    target_weights: dict[str, float] = {}

    for idx, (trade_date, close_row) in enumerate(prices.iterrows()):
        tradable_row = close_row.dropna()
        tradable_codes = set(tradable_row.index)
        for code, price in tradable_row.items():
            last_prices[code] = float(price)

        if trade_date < eval_start_date or trade_date > eval_end_date:
            continue

        month_key = (trade_date.year, trade_date.month)
        if month_key != prev_month:
            prev_month = month_key
            scores: dict[str, float] = {}
            for code in tradable_row.index:
                history = prices[code].iloc[: idx + 1].dropna()
                if len(history) <= lookback_days:
                    continue
                scores[code] = float(history.iloc[-1] / history.iloc[-1 - lookback_days] - 1)
            ranked = [c for c, s in sorted(scores.items(), key=lambda x: x[1], reverse=True) if s > 0]
            picks = ranked[: min(top_n, len(ranked))]
            weight = 1.0 / len(picks) if picks else 0.0
            target_weights = {c: weight for c in picks}

        portfolio_value = compute_portfolio_value(cash=cash, positions=shares, prices=last_prices)
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
                market=market,
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
            needed_qty = desired_shares[code] - shares[code]
            if needed_qty <= 0:
                continue
            price = float(tradable_row[code])
            affordable_qty, fee_total, fee_breakdown = compute_affordable_qty_with_fee(
                available_cash=cash,
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
            trades.append({"time_key": trade_date, "code": code, "action": "BUY", "price": price, "shares": affordable_qty, "fee_total": fee_total, "fee_breakdown": fee_breakdown, "cash_after": cash})

        equity = cash + sum(qty * last_prices.get(c, 0.0) for c, qty in shares.items())
        equity_points.append({"time_key": trade_date, "equity": equity})

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
        "initial_cash": initial_cash,
        "lookback_days": lookback_days,
        "top_n": top_n,
        "trade_count": len(trades),
        "buy_count": sum(1 for trade in trades if trade["action"] == "BUY"),
        "sell_count": sum(1 for trade in trades if trade["action"] == "SELL"),
        "total_fees": sum_trade_fees(trades),
        "final_value": final_value,
        "total_return_pct": (final_value / initial_cash - 1) * 100,
        "max_drawdown_pct": float(equity_curve["drawdown_pct"].min()),
    }
    return summary, pd.DataFrame(trades)


def main() -> int:
    total_started_at = perf_counter()
    args = parse_args()
    codes = resolve_codes(args.data_root, args.codes)
    market = validate_market_for_symbols(codes, args.market, label="--codes")
    load_tracker = FilesystemLoadTracker()
    prices, volumes = load_daily_data(args.data_root, codes, load_tracker=load_tracker)
    eval_start = parse_eval_start(args.eval_start)
    eval_end = parse_eval_end(args.eval_end)

    strategy_started_at = perf_counter()
    summary, _ = run_monthly_momentum(
        prices=prices,
        initial_cash=args.initial_cash,
        lookback_days=args.lookback_days,
        top_n=args.top_n,
        rebalance_band_pct=args.rebalance_band_pct,
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
            "momentum_monthly",
            summary,
            strategy_elapsed,
            total_time_sec=total_elapsed,
            load_stats=load_tracker.snapshot(),
            coverage_sections=[("Daily data coverage", observations_by_code_from_frame(prices))],
        )
    )

    if args.compare_baseline == 1:
        baseline_started_at = perf_counter()
        baseline, _ = run_baseline(
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
            rebalance_band_pct=0.05,
            volatility_window=20,
            target_annual_vol=0.60,
            max_gross_exposure=1.20,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=args.fee_account,
            market=market,
            security_type=args.security_type,
        )
        baseline_elapsed = perf_counter() - baseline_started_at
        print()
        print("Baseline")
        print(build_strategy_summary_table([build_strategy_summary_row("dual_momentum", baseline, baseline_elapsed)]))
        print(f"Excess return: {summary['total_return_pct'] - baseline['total_return_pct']:.2f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
