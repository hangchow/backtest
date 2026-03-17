#!/usr/bin/env python3
"""HK pool positive-return preset under current dual_momentum backtest framework.

This script keeps the original strategy logic unchanged and only uses a tuned
parameter profile discovered by in-sample random search for the provided HK pool.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.backtest_common import (
    add_eval_end_arg,
    add_eval_start_arg,
    add_fee_args,
    infer_market_from_codes,
    parse_eval_end,
    parse_eval_start,
    resolve_codes,
)
from backtest.backtest_dual_momentum import load_daily_data, run_backtest


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run tuned HK positive-return profile and compare baseline.")
    p.add_argument("--codes", nargs="+", required=True)
    p.add_argument("--data-root", type=Path, default=Path("kline_day"))
    p.add_argument("--initial-cash", type=float, default=800000)
    p.add_argument("--compare-baseline", type=int, choices=[0, 1], default=1)
    add_eval_start_arg(p)
    add_eval_end_arg(p)
    add_fee_args(p)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    codes = resolve_codes(args.data_root, args.codes)
    prices, volumes = load_daily_data(args.data_root, codes)
    eval_start = parse_eval_start(args.eval_start)
    eval_end = parse_eval_end(args.eval_end)
    market = infer_market_from_codes(codes)

    # tuned profile found by random-search under the same fee/eval setup
    tuned_summary, _ = run_backtest(
        prices=prices,
        volumes=volumes,
        initial_cash=args.initial_cash,
        lookback_days=5,
        long_lookback_days=40,
        long_lookback_weight=0.5,
        top_n=3,
        volume_window=20,
        min_volume_ratio=1.0,
        market_filter_window=90,
        rebalance_band_pct=0.02,
        volatility_window=30,
        target_annual_vol=0.8,
        max_gross_exposure=1.2,
        eval_start=eval_start,
        eval_end=eval_end,
        fee_account=args.fee_account,
        market=market,
        security_type=args.security_type,
    )

    print("Tuned profile (HK positive preset)")
    print(
        f"Return: {tuned_summary['total_return_pct']:.2f}% | "
        f"MDD: {tuned_summary['max_drawdown_pct']:.2f}% | "
        f"Trades: {tuned_summary['trade_count']}"
    )

    if args.compare_baseline == 1:
        base_summary, _ = run_backtest(
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
        print("Baseline profile")
        print(
            f"Return: {base_summary['total_return_pct']:.2f}% | "
            f"MDD: {base_summary['max_drawdown_pct']:.2f}% | "
            f"Trades: {base_summary['trade_count']}"
        )
        print(f"Excess return: {tuned_summary['total_return_pct'] - base_summary['total_return_pct']:.2f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
