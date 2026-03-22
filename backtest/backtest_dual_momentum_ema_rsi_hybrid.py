#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backtest.backtest_common import (
    add_eval_end_arg,
    add_eval_start_arg,
    add_fee_args,
    add_market_arg,
    compute_buy_quantity_with_fees,
    compute_order_fees,
    normalize_market,
    parse_eval_end,
    parse_eval_start,
    validate_market_for_symbols,
)
from backtest.backtest_rsi_reversion import compute_rsi

DEFAULT_INITIAL_CASH = 800_000.0
DEFAULT_DAILY_DATA_ROOT = Path("kline_day")
DEFAULT_MINUTE_DATA_ROOT = Path("kline_minute")
DEFAULT_LOOKBACK_DAYS = 60
DEFAULT_LONG_LOOKBACK_DAYS = 120
DEFAULT_LONG_LOOKBACK_WEIGHT = 0.2
DEFAULT_MARKET_FILTER_WINDOW = 60
DEFAULT_DAILY_VOL_WINDOW = 20
DEFAULT_MIN_MOMENTUM_SCORE = 0.02
DEFAULT_REBALANCE_DAYS = 5
DEFAULT_SWITCH_SCORE_BUFFER = 0.0
DEFAULT_MIN_HOLD_DAYS = 0
DEFAULT_TIMING_SCORE_WEIGHT = 0.2
DEFAULT_FAST_SPAN = 20
DEFAULT_SLOW_SPAN = 120
DEFAULT_RSI_PERIOD = 14
DEFAULT_ENTRY_RSI_MIN = 50.0
DEFAULT_ENTRY_RSI_MAX = 70.0
DEFAULT_EXIT_RSI_MIN = 45.0
DEFAULT_STOP_LOSS_PCT = 0.12
DEFAULT_TAKE_PROFIT_PCT = 0.2
DEFAULT_POSITION_RATIO = 0.95


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hybrid stock-pool backtest: daily dual momentum + minute EMA/RSI timing.")
    parser.add_argument("--codes", nargs="+", required=True, help="Stock pool codes.")
    parser.add_argument("--daily-data-root", type=Path, default=DEFAULT_DAILY_DATA_ROOT)
    parser.add_argument("--minute-data-root", type=Path, default=DEFAULT_MINUTE_DATA_ROOT)
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--long-lookback-days", type=int, default=DEFAULT_LONG_LOOKBACK_DAYS)
    parser.add_argument("--long-lookback-weight", type=float, default=DEFAULT_LONG_LOOKBACK_WEIGHT)
    parser.add_argument("--market-filter-window", type=int, default=DEFAULT_MARKET_FILTER_WINDOW)
    parser.add_argument("--daily-vol-window", type=int, default=DEFAULT_DAILY_VOL_WINDOW)
    parser.add_argument("--min-momentum-score", type=float, default=DEFAULT_MIN_MOMENTUM_SCORE)
    parser.add_argument("--rebalance-days", type=int, default=DEFAULT_REBALANCE_DAYS, help="Only rotate to a new symbol every N trading days.")
    parser.add_argument("--switch-score-buffer", type=float, default=DEFAULT_SWITCH_SCORE_BUFFER, help="Minimum score lead required before switching holdings.")
    parser.add_argument("--min-hold-days", type=int, default=DEFAULT_MIN_HOLD_DAYS, help="Minimum holding days before allowing symbol rotation.")
    parser.add_argument("--timing-score-weight", type=float, default=DEFAULT_TIMING_SCORE_WEIGHT, help="Weight applied to minute EMA/RSI timing score.")
    parser.add_argument("--fast-span", type=int, default=DEFAULT_FAST_SPAN)
    parser.add_argument("--slow-span", type=int, default=DEFAULT_SLOW_SPAN)
    parser.add_argument("--rsi-period", type=int, default=DEFAULT_RSI_PERIOD)
    parser.add_argument("--entry-rsi-min", type=float, default=DEFAULT_ENTRY_RSI_MIN)
    parser.add_argument("--entry-rsi-max", type=float, default=DEFAULT_ENTRY_RSI_MAX)
    parser.add_argument("--exit-rsi-min", type=float, default=DEFAULT_EXIT_RSI_MIN)
    parser.add_argument("--stop-loss-pct", type=float, default=DEFAULT_STOP_LOSS_PCT)
    parser.add_argument("--take-profit-pct", type=float, default=DEFAULT_TAKE_PROFIT_PCT)
    parser.add_argument("--position-ratio", type=float, default=DEFAULT_POSITION_RATIO)
    add_eval_start_arg(parser)
    add_eval_end_arg(parser)
    add_fee_args(parser)
    add_market_arg(parser)
    return parser.parse_args()


def load_daily_closes(data_root: Path, codes: list[str]) -> pd.DataFrame:
    close_map: dict[str, pd.Series] = {}
    for code in codes:
        parts = []
        for path in sorted((data_root / code).glob("*.csv")):
            chunk = pd.read_csv(path, usecols=["time_key", "close"])
            if not chunk.empty:
                parts.append(chunk)
        if not parts:
            raise FileNotFoundError(f"No daily files for {code} under {data_root}")
        history = pd.concat(parts, ignore_index=True)
        history["time_key"] = pd.to_datetime(history["time_key"])
        history = history.sort_values("time_key").drop_duplicates("time_key", keep="last")
        close_map[code] = pd.Series(history["close"].astype(float).to_numpy(), index=history["time_key"].dt.date)
    closes = pd.DataFrame(close_map).sort_index()
    if closes.empty:
        raise ValueError("empty daily close table")
    return closes


def load_day_end_minute_indicators(
    data_root: Path,
    codes: list[str],
    fast_span: int,
    slow_span: int,
    rsi_period: int,
) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for code in codes:
        parts = []
        for path in sorted((data_root / code).glob("*.csv")):
            chunk = pd.read_csv(path, usecols=["time_key", "close"])
            if not chunk.empty:
                parts.append(chunk)
        if not parts:
            raise FileNotFoundError(f"No minute files for {code} under {data_root}")

        history = pd.concat(parts, ignore_index=True)
        history["time_key"] = pd.to_datetime(history["time_key"])
        history = history.sort_values("time_key").reset_index(drop=True)
        history["trade_date"] = history["time_key"].dt.date
        history["is_day_end"] = history["trade_date"] != history["trade_date"].shift(-1)
        history["ema_fast"] = history["close"].ewm(span=fast_span, adjust=False).mean()
        history["ema_slow"] = history["close"].ewm(span=slow_span, adjust=False).mean()
        history["rsi"] = compute_rsi(history["close"], period=rsi_period)

        day_end = history[history["is_day_end"]].copy()
        day_end["trade_date"] = pd.to_datetime(day_end["trade_date"])
        result[code] = day_end.set_index("trade_date")[["close", "ema_fast", "ema_slow", "rsi"]]

    return result


def run_backtest(
    closes: pd.DataFrame,
    minute_indicators: dict[str, pd.DataFrame],
    *,
    initial_cash: float = DEFAULT_INITIAL_CASH,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    long_lookback_days: int = DEFAULT_LONG_LOOKBACK_DAYS,
    long_lookback_weight: float = DEFAULT_LONG_LOOKBACK_WEIGHT,
    market_filter_window: int = DEFAULT_MARKET_FILTER_WINDOW,
    daily_vol_window: int = DEFAULT_DAILY_VOL_WINDOW,
    min_momentum_score: float = DEFAULT_MIN_MOMENTUM_SCORE,
    rebalance_days: int = DEFAULT_REBALANCE_DAYS,
    switch_score_buffer: float = DEFAULT_SWITCH_SCORE_BUFFER,
    min_hold_days: int = DEFAULT_MIN_HOLD_DAYS,
    timing_score_weight: float = DEFAULT_TIMING_SCORE_WEIGHT,
    entry_rsi_min: float = DEFAULT_ENTRY_RSI_MIN,
    entry_rsi_max: float = DEFAULT_ENTRY_RSI_MAX,
    exit_rsi_min: float = DEFAULT_EXIT_RSI_MIN,
    stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
    take_profit_pct: float = DEFAULT_TAKE_PROFIT_PCT,
    position_ratio: float = DEFAULT_POSITION_RATIO,
    eval_start: pd.Timestamp | None = None,
    eval_end: pd.Timestamp | None = None,
    fee_account: str | None = None,
    market: str,
    security_type: str = "stock",
) -> tuple[dict, pd.DataFrame]:
    market = normalize_market(market)
    missing_codes = sorted(set(closes.columns) - set(minute_indicators))
    if missing_codes:
        raise ValueError(f"minute indicators missing for codes: {', '.join(missing_codes)}")

    blended_return = (1 - long_lookback_weight) * closes.pct_change(lookback_days) + long_lookback_weight * closes.pct_change(
        long_lookback_days
    )
    daily_vol = closes.pct_change().rolling(daily_vol_window).std()
    score = blended_return / daily_vol.replace(0.0, pd.NA)
    market_proxy = closes.mean(axis=1)
    market_risk_on = market_proxy > market_proxy.rolling(market_filter_window).mean()

    trade_dates = [pd.Timestamp(d) for d in closes.index]
    if eval_start is not None:
        trade_dates = [d for d in trade_dates if d >= eval_start]
    if eval_end is not None:
        trade_dates = [d for d in trade_dates if d <= eval_end]
    if not trade_dates:
        raise ValueError("evaluation window has no overlap")

    cash = float(initial_cash)
    hold_code: str | None = None
    hold_qty = 0
    hold_entry_price = 0.0
    hold_days = 0
    hold_score = float("-inf")
    peak_equity = cash
    max_drawdown_pct = 0.0
    trades: list[dict[str, object]] = []

    for idx, trade_dt in enumerate(trade_dates):
        date_key = trade_dt.date()
        score_row = score.loc[date_key].dropna() if date_key in score.index else pd.Series(dtype=float)
        if len(score_row) > 0:
            timing_score: dict[str, float] = {}
            for code in score_row.index:
                if trade_dt in minute_indicators[code].index:
                    minute_row = minute_indicators[code].loc[trade_dt]
                    ema_component = 1.0 if minute_row["ema_fast"] > minute_row["ema_slow"] else -1.0
                    rsi = float(minute_row["rsi"])
                    rsi_component = 1.0 if entry_rsi_min <= rsi <= entry_rsi_max else (-1.0 if rsi < exit_rsi_min else 0.0)
                    timing_score[code] = ema_component + 0.5 * rsi_component
                else:
                    timing_score[code] = -1.0
            combined_score = score_row + timing_score_weight * pd.Series(timing_score)
            top_code = str(combined_score.idxmax())
            top_score = float(combined_score.max())
        else:
            top_code = None
            top_score = float("-inf")

        rebalance_due = idx % max(rebalance_days, 1) == 0
        candidate = hold_code
        if (
            rebalance_due
            and top_code is not None
            and top_score >= min_momentum_score
            and bool(market_risk_on.get(date_key, False))
            and (
                hold_code is None
                or hold_days >= min_hold_days
                and (top_code != hold_code and top_score >= hold_score + switch_score_buffer)
            )
        ):
            candidate = top_code

        if hold_code is not None and trade_dt in minute_indicators[hold_code].index:
            row = minute_indicators[hold_code].loc[trade_dt]
            pnl_pct = float(row["close"]) / hold_entry_price - 1 if hold_entry_price > 0 else 0.0
            should_exit = hold_code != candidate or pnl_pct <= -stop_loss_pct or pnl_pct >= take_profit_pct
            if should_exit:
                price = float(row["close"])
                fee_total, fee_breakdown = compute_order_fees(
                    fee_account=fee_account,
                    market=market,
                    side="sell",
                    price=price,
                    shares=hold_qty,
                    security_type=security_type,
                )
                cash += hold_qty * price - fee_total
                trades.append(
                    {
                        "time_key": trade_dt,
                        "code": hold_code,
                        "action": "SELL",
                        "price": price,
                        "shares": hold_qty,
                        "fee_total": fee_total,
                        "fee_breakdown": fee_breakdown,
                        "cash_after": cash,
                    }
                )
                hold_code = None
                hold_qty = 0
                hold_entry_price = 0.0
                hold_days = 0
                hold_score = float("-inf")

        if hold_code is None and candidate is not None and trade_dt in minute_indicators[candidate].index:
            row = minute_indicators[candidate].loc[trade_dt]
            qty, fee_total, fee_breakdown = compute_buy_quantity_with_fees(
                budget=cash * position_ratio,
                price=float(row["close"]),
                fee_account=fee_account,
                market=market,
                security_type=security_type,
            )
            if qty > 0:
                cash -= qty * float(row["close"]) + fee_total
                hold_code = candidate
                hold_qty = qty
                hold_entry_price = float(row["close"])
                hold_days = 0
                hold_score = top_score if candidate == top_code else hold_score
                trades.append(
                    {
                        "time_key": trade_dt,
                        "code": candidate,
                        "action": "BUY",
                        "price": float(row["close"]),
                        "shares": qty,
                        "fee_total": fee_total,
                        "fee_breakdown": fee_breakdown,
                        "cash_after": cash,
                    }
                )

        if hold_code is not None:
            hold_days += 1
            if top_code == hold_code:
                hold_score = top_score

        equity = cash
        if hold_code is not None and trade_dt in minute_indicators[hold_code].index:
            equity += hold_qty * float(minute_indicators[hold_code].loc[trade_dt, "close"])
        peak_equity = max(peak_equity, equity)
        max_drawdown_pct = min(max_drawdown_pct, (equity - peak_equity) / peak_equity * 100)

    if hold_code is not None:
        liquidation_rows = minute_indicators[hold_code].loc[: trade_dates[-1]]
        if liquidation_rows.empty:
            raise ValueError(f"no minute bar available to liquidate within evaluation window for {hold_code}")
        last_row = liquidation_rows.iloc[-1]
        last_price = float(last_row["close"])
        fee_total, fee_breakdown = compute_order_fees(
            fee_account=fee_account,
            market=market,
            side="sell",
            price=last_price,
            shares=hold_qty,
            security_type=security_type,
        )
        cash += hold_qty * last_price - fee_total
        trades.append(
            {
                "time_key": pd.Timestamp(liquidation_rows.index[-1]),
                "code": hold_code,
                "action": "SELL",
                "price": last_price,
                "shares": hold_qty,
                "fee_total": fee_total,
                "fee_breakdown": fee_breakdown,
                "cash_after": cash,
            }
        )
        hold_code = None

    trades_frame = pd.DataFrame(trades)
    summary = {
        "start_time": trade_dates[0],
        "end_time": trade_dates[-1],
        "initial_cash": initial_cash,
        "codes": list(closes.columns),
        "trade_count": len(trades),
        "buy_count": sum(1 for trade in trades if trade["action"] == "BUY"),
        "sell_count": sum(1 for trade in trades if trade["action"] == "SELL"),
        "final_value": cash,
        "total_return_pct": (cash / initial_cash - 1) * 100,
        "max_drawdown_pct": max_drawdown_pct,
        "market": market,
        "security_type": security_type,
        "fee_account": fee_account,
    }
    return summary, trades_frame


def main() -> int:
    args = parse_args()
    market = validate_market_for_symbols(args.codes, args.market, label="--codes")
    eval_start = parse_eval_start(args.eval_start)
    eval_end = parse_eval_end(args.eval_end)
    closes = load_daily_closes(args.daily_data_root, args.codes)
    minute_indicators = load_day_end_minute_indicators(
        args.minute_data_root,
        args.codes,
        fast_span=args.fast_span,
        slow_span=args.slow_span,
        rsi_period=args.rsi_period,
    )
    summary, _ = run_backtest(
        closes=closes,
        minute_indicators=minute_indicators,
        initial_cash=args.initial_cash,
        lookback_days=args.lookback_days,
        long_lookback_days=args.long_lookback_days,
        long_lookback_weight=args.long_lookback_weight,
        market_filter_window=args.market_filter_window,
        daily_vol_window=args.daily_vol_window,
        min_momentum_score=args.min_momentum_score,
        rebalance_days=args.rebalance_days,
        switch_score_buffer=args.switch_score_buffer,
        min_hold_days=args.min_hold_days,
        timing_score_weight=args.timing_score_weight,
        entry_rsi_min=args.entry_rsi_min,
        entry_rsi_max=args.entry_rsi_max,
        exit_rsi_min=args.exit_rsi_min,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        position_ratio=args.position_ratio,
        eval_start=eval_start,
        eval_end=eval_end,
        fee_account=args.fee_account,
        market=market,
        security_type=args.security_type,
    )
    print(f"Eval range: {summary['start_time']} -> {summary['end_time']}")
    print(f"Trades: {summary['trade_count']} (BUY {summary['buy_count']}, SELL {summary['sell_count']})")
    print(f"Final value: {summary['final_value']:.2f}")
    print(f"Total return: {summary['total_return_pct']:.2f}%")
    print(f"Max drawdown: {summary['max_drawdown_pct']:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
