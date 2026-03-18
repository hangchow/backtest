#!/usr/bin/env python3
from __future__ import annotations

import argparse
from numbers import Real
from pathlib import Path
import time

import pandas as pd

try:
    from .backtest_common import (
        add_fee_args,
        add_market_arg,
        load_histories,
        normalize_market,
        parse_eval_end,
        parse_eval_start,
        validate_market_for_symbols,
    )
    from . import backtest_dual_momentum as dual_momentum
    from . import backtest_dual_momentum_ema_rsi_hybrid as hybrid
    from . import backtest_ema_cross as ema_cross
    from . import backtest_ema_rsi_bull_range as ema_rsi_bull_range
    from . import backtest_ema_rsi_combo as ema_rsi_combo
    from . import backtest_momentum_monthly as momentum_monthly
    from . import backtest_rsi_reversion as rsi_reversion
except ImportError:
    from backtest_common import (
        add_fee_args,
        add_market_arg,
        load_histories,
        normalize_market,
        parse_eval_end,
        parse_eval_start,
        validate_market_for_symbols,
    )
    import backtest_dual_momentum as dual_momentum
    import backtest_dual_momentum_ema_rsi_hybrid as hybrid
    import backtest_ema_cross as ema_cross
    import backtest_ema_rsi_bull_range as ema_rsi_bull_range
    import backtest_ema_rsi_combo as ema_rsi_combo
    import backtest_momentum_monthly as momentum_monthly
    import backtest_rsi_reversion as rsi_reversion


DEFAULT_MINUTE_DATA_ROOT = Path("kline_minute")
DEFAULT_DAILY_DATA_ROOT = Path("kline_day")
DEFAULT_EVAL_START = "2025-03-07"
DEFAULT_EVAL_END = "2026-03-06"

MINUTE_STRATEGY_KEYS = (
    "rsi_reversion",
    "ema_cross",
    "ema_rsi_combo",
    "ema_rsi_bull_range",
)
POOL_STRATEGY_KEYS = (
    "rsi_reversion",
    "ema_cross",
    "ema_rsi_combo",
    "ema_rsi_bull_range",
    "dual_momentum",
    "momentum_monthly",
    "dual_momentum_ema_rsi_hybrid",
)
NATIVE_POOL_STRATEGY_KEYS = (
    "dual_momentum",
    "momentum_monthly",
    "dual_momentum_ema_rsi_hybrid",
)
ALL_STRATEGY_KEYS = MINUTE_STRATEGY_KEYS + NATIVE_POOL_STRATEGY_KEYS
SCOPE_CHOICES = ("single", "pool")

STRATEGY_LABELS = {
    "rsi_reversion": "RSI reversion",
    "ema_cross": "EMA cross",
    "ema_rsi_combo": "EMA + RSI",
    "ema_rsi_bull_range": "EMA + RSI bull range",
    "dual_momentum": "Dual momentum",
    "momentum_monthly": "Momentum monthly",
    "dual_momentum_ema_rsi_hybrid": "Dual momentum + EMA + RSI hybrid",
}


def default_initial_cash_for_market(market: str) -> float:
    if market == "HK":
        return 800_000.0
    return 100_000.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run supported backtests for one or more symbols and print a Markdown comparison report."
    )
    parser.add_argument(
        "--code",
        action="append",
        required=True,
        help="Symbol directory under the configured data roots. Repeat this flag to compare multiple symbols.",
    )
    parser.add_argument(
        "--minute-data-root",
        "--data-root",
        dest="minute_data_root",
        type=Path,
        default=DEFAULT_MINUTE_DATA_ROOT,
        help="Minute-data root used by single-symbol and hybrid strategies. Defaults to kline_minute.",
    )
    parser.add_argument(
        "--daily-data-root",
        type=Path,
        default=DEFAULT_DAILY_DATA_ROOT,
        help="Daily-data root used by stock-pool strategies. Defaults to kline_day.",
    )
    add_fee_args(parser)
    add_market_arg(parser)
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=None,
        help="Starting cash shared by every compared strategy. Defaults to 800000 for HK and 100000 for US.",
    )
    parser.add_argument(
        "--strategy",
        action="append",
        choices=ALL_STRATEGY_KEYS,
        help=(
            "Limit the comparison to selected strategies. Repeat this flag. "
            "If omitted, defaults depend on --scope and the number of codes."
        ),
    )
    parser.add_argument(
        "--scope",
        choices=SCOPE_CHOICES,
        default="single",
        help=(
            "Which report sections to run: single or pool."
        ),
    )
    parser.add_argument(
        "--eval-start",
        default=DEFAULT_EVAL_START,
        help="Evaluation start date/time. Defaults to 2025-03-07.",
    )
    parser.add_argument(
        "--eval-end",
        default=DEFAULT_EVAL_END,
        help="Evaluation end date/time. Defaults to 2026-03-06.",
    )
    return parser.parse_args()


def dedupe_keys(keys: tuple[str, ...] | list[str]) -> list[str]:
    ordered: list[str] = []
    for key in keys:
        if key not in ordered:
            ordered.append(key)
    return ordered


def resolve_requested_strategies(raw_keys: list[str] | None, code_count: int, scope: str = "single") -> list[str]:
    if raw_keys:
        return dedupe_keys(raw_keys)

    if scope == "single":
        return list(MINUTE_STRATEGY_KEYS)
    if scope == "pool":
        if code_count <= 1:
            return list(NATIVE_POOL_STRATEGY_KEYS)
        return list(POOL_STRATEGY_KEYS)

    return list(MINUTE_STRATEGY_KEYS)


def resolve_report_scope(scope: str, code_count: int) -> tuple[bool, bool]:
    if scope == "single":
        return True, False
    if scope == "pool":
        return False, True
    return True, False


def build_pool_label(codes: list[str], market: str) -> str:
    return f"{market} pool ({len(codes)})"


def format_strategy_list(strategy_keys: list[str]) -> str:
    ordered = dedupe_keys(strategy_keys)
    return ", ".join(STRATEGY_LABELS[key] for key in ordered)


def format_dataset_heading(dataset_name: str, strategies: str | None = None) -> str:
    if strategies:
        return f"### {dataset_name}（{strategies}）"
    return f"### {dataset_name}"


def summarize_history(code: str, history: pd.DataFrame) -> dict[str, object]:
    return {
        "code": code,
        "rows": len(history),
        "days": int(history["trade_date"].nunique()),
        "start": str(history.iloc[0]["time_key"]),
        "end": str(history.iloc[-1]["time_key"]),
    }


def summarize_histories(histories: dict[str, pd.DataFrame], codes: list[str]) -> pd.DataFrame:
    return pd.DataFrame([summarize_history(code, histories[code]) for code in codes])


def summarize_daily_prices(prices: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for code in codes:
        series = prices[code].dropna()
        if series.empty:
            continue
        rows.append(
            {
                "code": code,
                "rows": len(series),
                "days": len(series),
                "start": str(series.index[0]),
                "end": str(series.index[-1]),
            }
        )
    return pd.DataFrame(rows)


def annotate_dataset_summary(
    summary: pd.DataFrame,
    dataset_name: str,
    strategy_keys: list[str],
) -> pd.DataFrame:
    if summary.empty:
        return summary
    return summary.assign(
        dataset=dataset_name,
        strategies=format_strategy_list(strategy_keys),
    )


def format_duration_mmss(duration_seconds: float) -> str:
    total_seconds = max(0, int(round(duration_seconds)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def format_cell(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def is_numeric_column(frame: pd.DataFrame, column: str) -> bool:
    has_non_null = False
    for value in frame[column]:
        if pd.isna(value):
            continue
        has_non_null = True
        if isinstance(value, bool) or not isinstance(value, Real):
            return False
    return has_non_null


def markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    column_values = {column: [format_cell(value) for value in frame[column]] for column in columns}
    numeric_columns = {column: is_numeric_column(frame, column) for column in columns}
    widths = {
        column: max(len(column), *(len(value) for value in column_values[column]))
        for column in columns
    }

    def align(value: str, column: str) -> str:
        if numeric_columns[column]:
            return value.rjust(widths[column])
        return value.ljust(widths[column])

    header = "| " + " | ".join(align(column, column) for column in columns) + " |"
    divider = "| " + " | ".join(
        ("-" * max(widths[column] - 1, 1) + ":") if numeric_columns[column] else "-" * widths[column]
        for column in columns
    ) + " |"
    rows = []
    for row_index in range(len(frame)):
        rows.append(
            "| " + " | ".join(align(column_values[column][row_index], column) for column in columns) + " |"
        )
    return "\n".join([header, divider, *rows])


def _run_minute_strategy(
    strategy_key: str,
    history: pd.DataFrame,
    market: str,
    initial_cash: float,
    eval_start: pd.Timestamp | None,
    eval_end: pd.Timestamp | None,
    fee_account: str | None,
    security_type: str,
) -> dict:
    if strategy_key == "rsi_reversion":
        summary, _ = rsi_reversion.run_backtest(
            history=history,
            initial_cash=initial_cash,
            rsi_period=rsi_reversion.DEFAULT_RSI_PERIOD,
            buy_threshold=rsi_reversion.DEFAULT_BUY_THRESHOLD,
            sell_threshold=rsi_reversion.DEFAULT_SELL_THRESHOLD,
            position_ratio=rsi_reversion.DEFAULT_POSITION_RATIO,
            volume_window=rsi_reversion.DEFAULT_VOLUME_WINDOW,
            min_volume_ratio=rsi_reversion.DEFAULT_MIN_VOLUME_RATIO,
            flat_at_close=False,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "ema_cross":
        summary, _ = ema_cross.run_backtest(
            history=history,
            initial_cash=initial_cash,
            fast_span=ema_cross.DEFAULT_FAST_SPAN,
            slow_span=ema_cross.DEFAULT_SLOW_SPAN,
            position_ratio=ema_cross.DEFAULT_POSITION_RATIO,
            volume_window=ema_cross.DEFAULT_VOLUME_WINDOW,
            min_volume_ratio=ema_cross.DEFAULT_MIN_VOLUME_RATIO,
            flat_at_close=True,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "ema_rsi_combo":
        summary, _ = ema_rsi_combo.run_backtest(
            history=history,
            initial_cash=initial_cash,
            fast_span=ema_rsi_combo.DEFAULT_FAST_SPAN,
            slow_span=ema_rsi_combo.DEFAULT_SLOW_SPAN,
            rsi_period=ema_rsi_combo.DEFAULT_RSI_PERIOD,
            buy_threshold=ema_rsi_combo.DEFAULT_BUY_THRESHOLD,
            sell_threshold=ema_rsi_combo.DEFAULT_SELL_THRESHOLD,
            position_ratio=ema_rsi_combo.DEFAULT_POSITION_RATIO,
            volume_window=ema_rsi_combo.DEFAULT_VOLUME_WINDOW,
            min_volume_ratio=ema_rsi_combo.DEFAULT_MIN_VOLUME_RATIO,
            flat_at_close=False,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "ema_rsi_bull_range":
        summary, _ = ema_rsi_bull_range.run_backtest(
            history=history,
            initial_cash=initial_cash,
            fast_span=ema_rsi_bull_range.DEFAULT_FAST_SPAN,
            slow_span=ema_rsi_bull_range.DEFAULT_SLOW_SPAN,
            rsi_period=ema_rsi_bull_range.DEFAULT_RSI_PERIOD,
            buy_threshold=ema_rsi_bull_range.DEFAULT_BUY_THRESHOLD,
            sell_threshold=ema_rsi_bull_range.DEFAULT_SELL_THRESHOLD,
            position_ratio=ema_rsi_bull_range.DEFAULT_POSITION_RATIO,
            volume_window=ema_rsi_bull_range.DEFAULT_VOLUME_WINDOW,
            min_volume_ratio=ema_rsi_bull_range.DEFAULT_MIN_VOLUME_RATIO,
            flat_at_close=False,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    raise ValueError(f"unsupported minute strategy: {strategy_key}")


def _run_pool_minute_strategy(
    strategy_key: str,
    histories: dict[str, pd.DataFrame],
    market: str,
    initial_cash: float,
    eval_start: pd.Timestamp | None,
    eval_end: pd.Timestamp | None,
    fee_account: str | None,
    security_type: str,
) -> dict:
    if strategy_key == "rsi_reversion":
        summary, _ = rsi_reversion.run_portfolio_backtest(
            histories=histories,
            initial_cash=initial_cash,
            rsi_period=rsi_reversion.DEFAULT_RSI_PERIOD,
            buy_threshold=rsi_reversion.DEFAULT_BUY_THRESHOLD,
            sell_threshold=rsi_reversion.DEFAULT_SELL_THRESHOLD,
            position_ratio=rsi_reversion.DEFAULT_POSITION_RATIO,
            volume_window=rsi_reversion.DEFAULT_VOLUME_WINDOW,
            min_volume_ratio=rsi_reversion.DEFAULT_MIN_VOLUME_RATIO,
            flat_at_close=False,
            max_open_positions=rsi_reversion.DEFAULT_MAX_OPEN_POSITIONS,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "ema_cross":
        summary, _ = ema_cross.run_portfolio_backtest(
            histories=histories,
            initial_cash=initial_cash,
            fast_span=ema_cross.DEFAULT_FAST_SPAN,
            slow_span=ema_cross.DEFAULT_SLOW_SPAN,
            position_ratio=ema_cross.DEFAULT_POSITION_RATIO,
            volume_window=ema_cross.DEFAULT_VOLUME_WINDOW,
            min_volume_ratio=ema_cross.DEFAULT_MIN_VOLUME_RATIO,
            flat_at_close=True,
            max_open_positions=ema_cross.DEFAULT_MAX_OPEN_POSITIONS,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "ema_rsi_combo":
        summary, _ = ema_rsi_combo.run_portfolio_backtest(
            histories=histories,
            initial_cash=initial_cash,
            fast_span=ema_rsi_combo.DEFAULT_FAST_SPAN,
            slow_span=ema_rsi_combo.DEFAULT_SLOW_SPAN,
            rsi_period=ema_rsi_combo.DEFAULT_RSI_PERIOD,
            buy_threshold=ema_rsi_combo.DEFAULT_BUY_THRESHOLD,
            sell_threshold=ema_rsi_combo.DEFAULT_SELL_THRESHOLD,
            position_ratio=ema_rsi_combo.DEFAULT_POSITION_RATIO,
            volume_window=ema_rsi_combo.DEFAULT_VOLUME_WINDOW,
            min_volume_ratio=ema_rsi_combo.DEFAULT_MIN_VOLUME_RATIO,
            flat_at_close=False,
            max_open_positions=ema_rsi_combo.DEFAULT_MAX_OPEN_POSITIONS,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "ema_rsi_bull_range":
        summary, _ = ema_rsi_combo.run_portfolio_backtest(
            histories=histories,
            initial_cash=initial_cash,
            fast_span=ema_rsi_bull_range.DEFAULT_FAST_SPAN,
            slow_span=ema_rsi_bull_range.DEFAULT_SLOW_SPAN,
            rsi_period=ema_rsi_bull_range.DEFAULT_RSI_PERIOD,
            buy_threshold=ema_rsi_bull_range.DEFAULT_BUY_THRESHOLD,
            sell_threshold=ema_rsi_bull_range.DEFAULT_SELL_THRESHOLD,
            position_ratio=ema_rsi_bull_range.DEFAULT_POSITION_RATIO,
            volume_window=ema_rsi_bull_range.DEFAULT_VOLUME_WINDOW,
            min_volume_ratio=ema_rsi_bull_range.DEFAULT_MIN_VOLUME_RATIO,
            flat_at_close=False,
            max_open_positions=ema_rsi_bull_range.DEFAULT_MAX_OPEN_POSITIONS,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    raise ValueError(f"unsupported pool minute strategy: {strategy_key}")


def run_single_symbol_strategies(
    codes: list[str],
    minute_data_root: Path,
    market: str,
    initial_cash: float,
    strategy_keys: list[str],
    eval_start: pd.Timestamp | None,
    eval_end: pd.Timestamp | None,
    fee_account: str | None,
    security_type: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    unsupported = [key for key in strategy_keys if key not in MINUTE_STRATEGY_KEYS]
    if unsupported:
        raise ValueError(f"single scope does not support strategies: {', '.join(unsupported)}")
    selected = [key for key in strategy_keys if key in MINUTE_STRATEGY_KEYS]
    if not selected:
        return pd.DataFrame(), pd.DataFrame()

    data_rows: list[dict] = []
    result_rows: list[dict] = []

    for code in codes:
        history = rsi_reversion.load_history(minute_data_root / code)
        data_row = summarize_history(code, history)
        data_rows.append(data_row)

        for strategy_key in selected:
            strategy_start = time.perf_counter()
            summary = _run_minute_strategy(
                strategy_key,
                history,
                market,
                initial_cash,
                eval_start,
                eval_end,
                fee_account,
                security_type,
            )
            duration = format_duration_mmss(time.perf_counter() - strategy_start)
            result_rows.append(
                {
                    **data_row,
                    "strategy": STRATEGY_LABELS[strategy_key],
                    "final_value": summary["final_value"],
                    "return_pct": summary["total_return_pct"],
                    "max_drawdown_pct": summary["max_drawdown_pct"],
                    "trade_count": summary["trade_count"],
                    "duration": duration,
                }
            )

    data_summary = annotate_dataset_summary(pd.DataFrame(data_rows), "kline_minute", selected)
    return data_summary, pd.DataFrame(result_rows)


def run_stock_pool_strategies(
    codes: list[str],
    daily_data_root: Path,
    minute_data_root: Path,
    market: str,
    initial_cash: float,
    strategy_keys: list[str],
    eval_start: pd.Timestamp | None,
    eval_end: pd.Timestamp | None,
    fee_account: str | None,
    security_type: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(codes) <= 1:
        requested_minute_pool = [key for key in strategy_keys if key in MINUTE_STRATEGY_KEYS]
        if requested_minute_pool:
            joined = ", ".join(requested_minute_pool)
            raise ValueError(f"pool minute strategies require at least 2 codes: {joined}")

    selected: list[str] = []
    for key in strategy_keys:
        if key in NATIVE_POOL_STRATEGY_KEYS:
            selected.append(key)
        elif len(codes) > 1 and key in MINUTE_STRATEGY_KEYS:
            selected.append(key)
    if not selected:
        return pd.DataFrame(), pd.DataFrame()

    pool_label = build_pool_label(codes, market)
    result_rows: list[dict] = []
    prices: pd.DataFrame | None = None
    volumes: pd.DataFrame | None = None
    hybrid_closes: pd.DataFrame | None = None
    minute_histories: dict[str, pd.DataFrame] | None = None
    dataset_frames: list[pd.DataFrame] = []

    if any(key in ("dual_momentum", "momentum_monthly") for key in selected):
        prices, volumes = dual_momentum.load_daily_data(daily_data_root, codes)
        daily_summary = summarize_daily_prices(prices, codes)
        if not daily_summary.empty:
            dataset_frames.append(
                annotate_dataset_summary(
                    daily_summary,
                    "kline_day",
                    [key for key in selected if key in ("dual_momentum", "momentum_monthly", "dual_momentum_ema_rsi_hybrid")],
                )
            )
        hybrid_closes = prices
    elif "dual_momentum_ema_rsi_hybrid" in selected:
        hybrid_closes = hybrid.load_daily_closes(daily_data_root, codes)
        daily_summary = summarize_daily_prices(hybrid_closes, codes)
        if not daily_summary.empty:
            dataset_frames.append(annotate_dataset_summary(daily_summary, "kline_day", ["dual_momentum_ema_rsi_hybrid"]))

    if any(key in MINUTE_STRATEGY_KEYS for key in selected) or "dual_momentum_ema_rsi_hybrid" in selected:
        dataset_histories = load_histories(minute_data_root, codes)
        minute_summary = summarize_histories(dataset_histories, codes)
        if not minute_summary.empty:
            dataset_frames.append(
                annotate_dataset_summary(
                    minute_summary,
                    "kline_minute",
                    [key for key in selected if key in MINUTE_STRATEGY_KEYS or key == "dual_momentum_ema_rsi_hybrid"],
                )
            )
        if any(key in MINUTE_STRATEGY_KEYS for key in selected):
            minute_histories = dataset_histories

    if "rsi_reversion" in selected:
        assert minute_histories is not None
        strategy_start = time.perf_counter()
        summary = _run_pool_minute_strategy(
            "rsi_reversion",
            minute_histories,
            market,
            initial_cash,
            eval_start,
            eval_end,
            fee_account,
            security_type,
        )
        duration = format_duration_mmss(time.perf_counter() - strategy_start)
        result_rows.append(
            {
                "pool": pool_label,
                "strategy": STRATEGY_LABELS["rsi_reversion"],
                "final_value": summary["final_value"],
                "return_pct": summary["total_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "trade_count": summary["trade_count"],
                "duration": duration,
            }
        )

    if "ema_cross" in selected:
        assert minute_histories is not None
        strategy_start = time.perf_counter()
        summary = _run_pool_minute_strategy(
            "ema_cross",
            minute_histories,
            market,
            initial_cash,
            eval_start,
            eval_end,
            fee_account,
            security_type,
        )
        duration = format_duration_mmss(time.perf_counter() - strategy_start)
        result_rows.append(
            {
                "pool": pool_label,
                "strategy": STRATEGY_LABELS["ema_cross"],
                "final_value": summary["final_value"],
                "return_pct": summary["total_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "trade_count": summary["trade_count"],
                "duration": duration,
            }
        )

    if "ema_rsi_combo" in selected:
        assert minute_histories is not None
        strategy_start = time.perf_counter()
        summary = _run_pool_minute_strategy(
            "ema_rsi_combo",
            minute_histories,
            market,
            initial_cash,
            eval_start,
            eval_end,
            fee_account,
            security_type,
        )
        duration = format_duration_mmss(time.perf_counter() - strategy_start)
        result_rows.append(
            {
                "pool": pool_label,
                "strategy": STRATEGY_LABELS["ema_rsi_combo"],
                "final_value": summary["final_value"],
                "return_pct": summary["total_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "trade_count": summary["trade_count"],
                "duration": duration,
            }
        )

    if "ema_rsi_bull_range" in selected:
        assert minute_histories is not None
        strategy_start = time.perf_counter()
        summary = _run_pool_minute_strategy(
            "ema_rsi_bull_range",
            minute_histories,
            market,
            initial_cash,
            eval_start,
            eval_end,
            fee_account,
            security_type,
        )
        duration = format_duration_mmss(time.perf_counter() - strategy_start)
        result_rows.append(
            {
                "pool": pool_label,
                "strategy": STRATEGY_LABELS["ema_rsi_bull_range"],
                "final_value": summary["final_value"],
                "return_pct": summary["total_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "trade_count": summary["trade_count"],
                "duration": duration,
            }
        )

    if "dual_momentum" in selected:
        assert prices is not None
        assert volumes is not None
        strategy_start = time.perf_counter()
        summary, _ = dual_momentum.run_backtest(
            prices=prices,
            volumes=volumes,
            initial_cash=initial_cash,
            lookback_days=dual_momentum.DEFAULT_LOOKBACK_DAYS,
            long_lookback_days=dual_momentum.DEFAULT_LONG_LOOKBACK_DAYS,
            long_lookback_weight=dual_momentum.DEFAULT_LONG_LOOKBACK_WEIGHT,
            top_n=dual_momentum.DEFAULT_TOP_N,
            volume_window=dual_momentum.DEFAULT_VOLUME_WINDOW,
            min_volume_ratio=dual_momentum.DEFAULT_MIN_VOLUME_RATIO,
            market_filter_window=dual_momentum.DEFAULT_MARKET_FILTER_WINDOW,
            rebalance_band_pct=dual_momentum.DEFAULT_REBALANCE_BAND_PCT,
            volatility_window=dual_momentum.DEFAULT_VOLATILITY_WINDOW,
            target_annual_vol=dual_momentum.DEFAULT_TARGET_ANNUAL_VOL,
            max_gross_exposure=dual_momentum.DEFAULT_MAX_GROSS_EXPOSURE,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        duration = format_duration_mmss(time.perf_counter() - strategy_start)
        result_rows.append(
            {
                "pool": pool_label,
                "strategy": STRATEGY_LABELS["dual_momentum"],
                "final_value": summary["final_value"],
                "return_pct": summary["total_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "trade_count": summary["trade_count"],
                "duration": duration,
            }
        )

    if "momentum_monthly" in selected:
        assert prices is not None
        strategy_start = time.perf_counter()
        summary, _ = momentum_monthly.run_monthly_momentum(
            prices=prices,
            initial_cash=initial_cash,
            lookback_days=momentum_monthly.DEFAULT_LOOKBACK_DAYS,
            top_n=momentum_monthly.DEFAULT_TOP_N,
            rebalance_band_pct=momentum_monthly.DEFAULT_REBALANCE_BAND_PCT,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        duration = format_duration_mmss(time.perf_counter() - strategy_start)
        result_rows.append(
            {
                "pool": pool_label,
                "strategy": STRATEGY_LABELS["momentum_monthly"],
                "final_value": summary["final_value"],
                "return_pct": summary["total_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "trade_count": summary["trade_count"],
                "duration": duration,
            }
        )

    if "dual_momentum_ema_rsi_hybrid" in selected:
        assert hybrid_closes is not None
        strategy_start = time.perf_counter()
        minute_indicators = hybrid.load_day_end_minute_indicators(
            minute_data_root,
            codes,
            fast_span=hybrid.DEFAULT_FAST_SPAN,
            slow_span=hybrid.DEFAULT_SLOW_SPAN,
            rsi_period=hybrid.DEFAULT_RSI_PERIOD,
        )
        summary, _ = hybrid.run_backtest(
            closes=hybrid_closes,
            minute_indicators=minute_indicators,
            initial_cash=initial_cash,
            lookback_days=hybrid.DEFAULT_LOOKBACK_DAYS,
            long_lookback_days=hybrid.DEFAULT_LONG_LOOKBACK_DAYS,
            long_lookback_weight=hybrid.DEFAULT_LONG_LOOKBACK_WEIGHT,
            market_filter_window=hybrid.DEFAULT_MARKET_FILTER_WINDOW,
            daily_vol_window=hybrid.DEFAULT_DAILY_VOL_WINDOW,
            min_momentum_score=hybrid.DEFAULT_MIN_MOMENTUM_SCORE,
            rebalance_days=hybrid.DEFAULT_REBALANCE_DAYS,
            switch_score_buffer=hybrid.DEFAULT_SWITCH_SCORE_BUFFER,
            min_hold_days=hybrid.DEFAULT_MIN_HOLD_DAYS,
            timing_score_weight=hybrid.DEFAULT_TIMING_SCORE_WEIGHT,
            entry_rsi_min=hybrid.DEFAULT_ENTRY_RSI_MIN,
            entry_rsi_max=hybrid.DEFAULT_ENTRY_RSI_MAX,
            exit_rsi_min=hybrid.DEFAULT_EXIT_RSI_MIN,
            stop_loss_pct=hybrid.DEFAULT_STOP_LOSS_PCT,
            take_profit_pct=hybrid.DEFAULT_TAKE_PROFIT_PCT,
            position_ratio=hybrid.DEFAULT_POSITION_RATIO,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        duration = format_duration_mmss(time.perf_counter() - strategy_start)
        result_rows.append(
            {
                "pool": pool_label,
                "strategy": STRATEGY_LABELS["dual_momentum_ema_rsi_hybrid"],
                "final_value": summary["final_value"],
                "return_pct": summary["total_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "trade_count": summary["trade_count"],
                "duration": duration,
            }
        )

    dataset_summary = pd.concat(dataset_frames, ignore_index=True) if dataset_frames else pd.DataFrame()
    return dataset_summary, pd.DataFrame(result_rows)


def run_all(
    codes: list[str],
    minute_data_root: Path,
    daily_data_root: Path,
    market: str,
    initial_cash: float | None = None,
    strategy_keys: list[str] | None = None,
    scope: str = "single",
    eval_start: pd.Timestamp | None = None,
    eval_end: pd.Timestamp | None = None,
    fee_account: str | None = None,
    security_type: str = "stock",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if scope not in SCOPE_CHOICES:
        raise ValueError(f"scope must be one of: {', '.join(SCOPE_CHOICES)}")
    market = validate_market_for_symbols(codes, normalize_market(market), label="--code")
    if eval_start is not None and eval_end is not None and eval_start > eval_end:
        raise ValueError("eval-start must be earlier than or equal to eval-end")
    effective_initial_cash = default_initial_cash_for_market(market) if initial_cash is None else float(initial_cash)
    selected = resolve_requested_strategies(strategy_keys, len(codes), scope=scope)
    run_single, run_pool = resolve_report_scope(scope, len(codes))

    if run_single:
        minute_data_summary, minute_results = run_single_symbol_strategies(
            codes,
            minute_data_root,
            market,
            effective_initial_cash,
            selected,
            eval_start,
            eval_end,
            fee_account,
            security_type,
        )
    else:
        minute_data_summary, minute_results = pd.DataFrame(), pd.DataFrame()

    if run_pool:
        pool_data_summary, pool_results = run_stock_pool_strategies(
            codes,
            daily_data_root,
            minute_data_root,
            market,
            effective_initial_cash,
            selected,
            eval_start,
            eval_end,
            fee_account,
            security_type,
        )
    else:
        pool_data_summary, pool_results = pd.DataFrame(), pd.DataFrame()
    return minute_data_summary, minute_results, pool_data_summary, pool_results


def build_report(
    minute_data_summary: pd.DataFrame,
    minute_results: pd.DataFrame,
    pool_data_summary: pd.DataFrame,
    pool_results: pd.DataFrame,
) -> str:
    sections: list[str] = []

    dataset_tables: list[str] = []
    dataset_frames: list[pd.DataFrame] = []
    for summary in (minute_data_summary, pool_data_summary):
        if summary.empty:
            continue
        if "dataset" in summary.columns:
            dataset_frames.append(summary.copy())
        else:
            dataset_frames.append(summary.assign(dataset="kline_minute", strategies=""))
    if dataset_frames:
        combined_datasets = pd.concat(dataset_frames, ignore_index=True)
        for dataset_name in ("kline_minute", "kline_day"):
            subset = combined_datasets[combined_datasets["dataset"] == dataset_name]
            if subset.empty:
                continue
            strategies = ""
            if "strategies" in subset.columns:
                strategy_labels: list[str] = []
                for value in subset["strategies"]:
                    for label in str(value).split(", "):
                        if label and label not in strategy_labels:
                            strategy_labels.append(label)
                strategies = ", ".join(strategy_labels)
            dataset_tables.append(
                format_dataset_heading(dataset_name, strategies) + "\n\n"
                + markdown_table(
                    subset.loc[:, ["code", "rows", "days", "start", "end"]],
                    ["code", "rows", "days", "start", "end"],
                )
            )

    if dataset_tables:
        sections.append("## 回测数据集\n\n" + "\n\n".join(dataset_tables))

    if not minute_results.empty:
        single_comparison = minute_results.copy()
        if "duration" not in single_comparison.columns:
            single_comparison["duration"] = ""
        single_comparison = single_comparison.sort_values(
            ["code", "return_pct", "strategy"],
            ascending=[True, False, True],
        )
        sections.append(
            "## 单标策略对比\n\n"
            + markdown_table(
                single_comparison,
                ["code", "strategy", "final_value", "return_pct", "max_drawdown_pct", "trade_count", "duration"],
            )
        )

    if not pool_results.empty:
        pool_comparison = pool_results.sort_values(["return_pct", "strategy"], ascending=[False, True])
        sections.append(
            "## 股票池策略对比\n\n"
            + markdown_table(
                pool_comparison,
                ["pool", "strategy", "final_value", "return_pct", "max_drawdown_pct", "trade_count", "duration"],
            )
        )

    return "\n\n".join(sections)


def main() -> int:
    args = parse_args()
    eval_start = parse_eval_start(args.eval_start)
    eval_end = parse_eval_end(args.eval_end)
    minute_data_summary, minute_results, pool_data_summary, pool_results = run_all(
        codes=args.code,
        minute_data_root=args.minute_data_root,
        daily_data_root=args.daily_data_root,
        market=args.market,
        initial_cash=args.initial_cash,
        strategy_keys=args.strategy,
        scope=args.scope,
        eval_start=eval_start,
        eval_end=eval_end,
        fee_account=args.fee_account,
        security_type=args.security_type,
    )
    print(build_report(minute_data_summary, minute_results, pool_data_summary, pool_results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
