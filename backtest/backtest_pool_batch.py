#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

from backtest import backtest_dual_momentum as dual_momentum
from backtest import backtest_dual_momentum_ema_rsi_hybrid as hybrid
from backtest import backtest_ema_cross as ema_cross
from backtest import backtest_ema_rsi_bull_range as ema_rsi_bull_range
from backtest import backtest_ema_rsi_combo as ema_rsi_combo
from backtest import backtest_momentum_monthly as momentum_monthly
from backtest import backtest_rsi_reversion as rsi_reversion
from backtest.backtest_common import (
    add_eval_end_arg,
    add_eval_start_arg,
    add_fee_args,
    add_market_arg,
    normalize_market,
    parse_eval_end,
    parse_eval_start,
    validate_market_for_symbols,
)
from backtest.backtest_compare import default_initial_cash_for_market
from backtest.minute_pool_cache import MinutePoolFeatureCache
from backtest.reporting import (
    build_strategy_summary_row,
    build_strategy_summary_table,
    observations_by_code_from_histories,
    render_data_coverage_sections,
)
from backtest.strategy_config import add_strategy_config_arg, resolve_batch_strategy_params


DEFAULT_MINUTE_DATA_ROOT = Path("kline_minute")
DEFAULT_DAILY_DATA_ROOT = Path("kline_day")
CSV_COLUMNS = ["time_key", "open", "close", "high", "low", "volume"]
DYNAMIC_DAILY_COLUMNS = ["time_key", "close", "volume"]
STRATEGY_CHOICES = (
    "rsi_reversion",
    "ema_cross",
    "ema_rsi_combo",
    "ema_rsi_bull_range",
    "dual_momentum",
    "momentum_monthly",
    "dual_momentum_ema_rsi_hybrid",
)
DEFAULT_STRATEGIES = STRATEGY_CHOICES
DEFAULT_STRATEGY_PARAMS: dict[str, dict[str, Any]] = {
    "rsi_reversion": {
        "rsi_period": rsi_reversion.DEFAULT_RSI_PERIOD,
        "buy_threshold": rsi_reversion.DEFAULT_BUY_THRESHOLD,
        "sell_threshold": 70.0,
        "position_ratio": rsi_reversion.DEFAULT_POSITION_RATIO,
        "volume_window": rsi_reversion.DEFAULT_VOLUME_WINDOW,
        "min_volume_ratio": rsi_reversion.DEFAULT_MIN_VOLUME_RATIO,
        "flat_at_close": False,
        "max_open_positions": rsi_reversion.DEFAULT_MAX_OPEN_POSITIONS,
    },
    "ema_cross": {
        "fast_span": ema_cross.DEFAULT_FAST_SPAN,
        "slow_span": ema_cross.DEFAULT_SLOW_SPAN,
        "position_ratio": 0.15,
        "volume_window": ema_cross.DEFAULT_VOLUME_WINDOW,
        "min_volume_ratio": ema_cross.DEFAULT_MIN_VOLUME_RATIO,
        "flat_at_close": False,
        "max_open_positions": 1,
    },
    "ema_rsi_combo": {
        "fast_span": 20,
        "slow_span": 240,
        "rsi_period": 6,
        "buy_threshold": 35.0,
        "sell_threshold": 60.0,
        "position_ratio": ema_rsi_combo.DEFAULT_POSITION_RATIO,
        "volume_window": 20,
        "min_volume_ratio": 1.2,
        "flat_at_close": False,
        "max_open_positions": 1,
    },
    "ema_rsi_bull_range": {
        "fast_span": 20,
        "slow_span": 240,
        "rsi_period": 6,
        "buy_threshold": 35.0,
        "sell_threshold": 60.0,
        "position_ratio": ema_rsi_bull_range.DEFAULT_POSITION_RATIO,
        "volume_window": 20,
        "min_volume_ratio": 1.2,
        "flat_at_close": False,
        "max_open_positions": 1,
    },
    "dual_momentum": {
        "lookback_days": 40,
        "long_lookback_days": 120,
        "long_lookback_weight": 0.25,
        "top_n": 1,
        "volume_window": 20,
        "min_volume_ratio": 1.0,
        "market_filter_window": 60,
        "rebalance_band_pct": 0.05,
        "volatility_window": 20,
        "target_annual_vol": 0.60,
        "max_gross_exposure": 1.20,
    },
    "momentum_monthly": {
        "lookback_days": momentum_monthly.DEFAULT_LOOKBACK_DAYS,
        "top_n": momentum_monthly.DEFAULT_TOP_N,
        "rebalance_band_pct": momentum_monthly.DEFAULT_REBALANCE_BAND_PCT,
    },
    "dual_momentum_ema_rsi_hybrid": {
        "lookback_days": hybrid.DEFAULT_LOOKBACK_DAYS,
        "long_lookback_days": hybrid.DEFAULT_LONG_LOOKBACK_DAYS,
        "long_lookback_weight": hybrid.DEFAULT_LONG_LOOKBACK_WEIGHT,
        "market_filter_window": hybrid.DEFAULT_MARKET_FILTER_WINDOW,
        "daily_vol_window": hybrid.DEFAULT_DAILY_VOL_WINDOW,
        "min_momentum_score": hybrid.DEFAULT_MIN_MOMENTUM_SCORE,
        "rebalance_days": hybrid.DEFAULT_REBALANCE_DAYS,
        "switch_score_buffer": hybrid.DEFAULT_SWITCH_SCORE_BUFFER,
        "min_hold_days": hybrid.DEFAULT_MIN_HOLD_DAYS,
        "timing_score_weight": hybrid.DEFAULT_TIMING_SCORE_WEIGHT,
        "fast_span": hybrid.DEFAULT_FAST_SPAN,
        "slow_span": hybrid.DEFAULT_SLOW_SPAN,
        "rsi_period": hybrid.DEFAULT_RSI_PERIOD,
        "entry_rsi_min": hybrid.DEFAULT_ENTRY_RSI_MIN,
        "entry_rsi_max": hybrid.DEFAULT_ENTRY_RSI_MAX,
        "exit_rsi_min": hybrid.DEFAULT_EXIT_RSI_MIN,
        "stop_loss_pct": hybrid.DEFAULT_STOP_LOSS_PCT,
        "take_profit_pct": hybrid.DEFAULT_TAKE_PROFIT_PCT,
        "position_ratio": hybrid.DEFAULT_POSITION_RATIO,
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one evaluation window across multiple stock-pool strategies."
    )
    parser.add_argument("--codes", nargs="+", help="Stock pool codes.")
    parser.add_argument("--minute-data-root", type=Path, default=DEFAULT_MINUTE_DATA_ROOT)
    parser.add_argument("--daily-data-root", type=Path, default=DEFAULT_DAILY_DATA_ROOT)
    parser.add_argument(
        "--strategy",
        action="append",
        choices=STRATEGY_CHOICES,
        help="Repeat to select strategies. Defaults to all supported pool strategies.",
    )
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=None,
        help="Defaults to 800000 for HK and 100000 for US.",
    )
    parser.add_argument(
        "--dump-default-strategy-config",
        action="store_true",
        help="Print the default per-strategy JSON config template and exit.",
    )
    add_strategy_config_arg(parser)
    add_eval_start_arg(parser)
    add_eval_end_arg(parser)
    add_fee_args(parser)
    add_market_arg(parser)
    for action in parser._actions:
        if action.dest == "market":
            action.required = False
            break
    return parser.parse_args(argv)


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _resolve_strategy_params(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    return resolve_batch_strategy_params(DEFAULT_STRATEGY_PARAMS, path=args.strategy_config)


def _dump_default_strategy_config(selected: list[str]) -> str:
    payload = {strategy_key: DEFAULT_STRATEGY_PARAMS[strategy_key] for strategy_key in selected}
    return json.dumps(payload, indent=2, sort_keys=True)


@dataclass(frozen=True)
class BatchLoadSnapshot:
    total_load_seconds: float
    files_loaded: int
    load_operations: int


@dataclass
class BatchDataContext:
    codes: list[str]
    minute_data_root: Path
    daily_data_root: Path
    _minute_histories: dict[str, pd.DataFrame] | None = None
    _minute_pool_cache: MinutePoolFeatureCache | None = None
    _daily_histories: dict[str, pd.DataFrame] | None = None
    _daily_prices_volumes: tuple[pd.DataFrame, pd.DataFrame] | None = None
    _daily_closes: pd.DataFrame | None = None
    _hybrid_minute_indicators: dict[tuple[int, int, int], dict[str, pd.DataFrame]] = field(default_factory=dict)
    _total_load_seconds: float = 0.0
    _files_loaded: int = 0
    _load_operations: int = 0

    def snapshot(self) -> BatchLoadSnapshot:
        return BatchLoadSnapshot(
            total_load_seconds=self._total_load_seconds,
            files_loaded=self._files_loaded,
            load_operations=self._load_operations,
        )

    def _load_code_history(self, root: Path, code: str, *, usecols: list[str]) -> pd.DataFrame:
        code_dir = root / code
        if not code_dir.is_dir():
            raise FileNotFoundError(f"Missing data directory for {code}: {code_dir}")
        csv_files = sorted(code_dir.glob("*.csv"))
        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in {code_dir}")

        started_at = perf_counter()
        history_parts: list[pd.DataFrame] = []
        files_loaded = 0
        for path in csv_files:
            history = pd.read_csv(path, usecols=usecols)
            files_loaded += 1
            if history.empty:
                continue
            history_parts.append(history)
        elapsed = perf_counter() - started_at
        self._total_load_seconds += elapsed
        self._files_loaded += files_loaded
        self._load_operations += 1
        if not history_parts:
            raise FileNotFoundError(f"No readable CSV payload found in {code_dir}")

        history = pd.concat(history_parts, ignore_index=True)
        history["time_key"] = pd.to_datetime(history["time_key"])
        history = history.sort_values("time_key").drop_duplicates(subset=["time_key"], keep="last").reset_index(drop=True)
        return history

    def minute_histories(self) -> dict[str, pd.DataFrame]:
        if self._minute_histories is None:
            histories: dict[str, pd.DataFrame] = {}
            for code in self.codes:
                history = self._load_code_history(self.minute_data_root, code, usecols=CSV_COLUMNS).copy()
                history["trade_date"] = history["time_key"].dt.date
                history["is_day_end"] = history["trade_date"] != history["trade_date"].shift(-1)
                histories[code] = history
            self._minute_histories = histories
        return self._minute_histories

    def minute_pool_cache(self) -> MinutePoolFeatureCache:
        if self._minute_pool_cache is None:
            self._minute_pool_cache = MinutePoolFeatureCache(self.minute_histories())
        return self._minute_pool_cache

    def daily_histories(self) -> dict[str, pd.DataFrame]:
        if self._daily_histories is None:
            histories: dict[str, pd.DataFrame] = {}
            for code in self.codes:
                histories[code] = self._load_code_history(self.daily_data_root, code, usecols=DYNAMIC_DAILY_COLUMNS)
            self._daily_histories = histories
        return self._daily_histories

    def daily_prices_volumes(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        if self._daily_prices_volumes is None:
            price_map: dict[str, pd.Series] = {}
            volume_map: dict[str, pd.Series] = {}
            for code, history in self.daily_histories().items():
                trade_dates = history["time_key"].dt.date
                price_map[code] = pd.Series(history["close"].astype(float).to_numpy(), index=trade_dates)
                volume_map[code] = pd.Series(history["volume"].astype(float).to_numpy(), index=trade_dates)
            self._daily_prices_volumes = (
                pd.DataFrame(price_map).sort_index(),
                pd.DataFrame(volume_map).sort_index(),
            )
        return self._daily_prices_volumes

    def daily_closes(self) -> pd.DataFrame:
        if self._daily_closes is None:
            close_map: dict[str, pd.Series] = {}
            for code, history in self.daily_histories().items():
                close_map[code] = pd.Series(
                    history["close"].astype(float).to_numpy(),
                    index=history["time_key"].dt.date,
                )
            closes = pd.DataFrame(close_map).sort_index()
            if closes.empty:
                raise ValueError("empty daily close table")
            self._daily_closes = closes
        return self._daily_closes

    def hybrid_minute_indicators(self, *, fast_span: int, slow_span: int, rsi_period: int) -> dict[str, pd.DataFrame]:
        key = (fast_span, slow_span, rsi_period)
        cached = self._hybrid_minute_indicators.get(key)
        if cached is not None:
            return cached
        indicators = self.minute_pool_cache().build_day_end_indicator_frames(
            fast_span=fast_span,
            slow_span=slow_span,
            rsi_period=rsi_period,
        )
        self._hybrid_minute_indicators[key] = indicators
        return indicators

    def loaded_daily_observations(self) -> dict[str, pd.DatetimeIndex]:
        if self._daily_histories is None:
            return {}
        return observations_by_code_from_histories(self._daily_histories, date_column="time_key")

    def loaded_minute_observations(self) -> dict[str, pd.DatetimeIndex]:
        if self._minute_histories is None:
            return {}
        return observations_by_code_from_histories(self._minute_histories)


def _run_strategy(
    strategy_key: str,
    *,
    data: BatchDataContext,
    strategy_params: dict[str, dict[str, Any]],
    initial_cash: float,
    eval_start: pd.Timestamp | None,
    eval_end: pd.Timestamp | None,
    fee_account: str | None,
    market: str,
    security_type: str,
) -> dict:
    config = strategy_params[strategy_key]
    if strategy_key == "rsi_reversion":
        summary, _ = rsi_reversion.run_portfolio_backtest(
            histories=data.minute_histories(),
            pool_cache=data.minute_pool_cache(),
            initial_cash=initial_cash,
            rsi_period=config["rsi_period"],
            buy_threshold=config["buy_threshold"],
            sell_threshold=config["sell_threshold"],
            position_ratio=config["position_ratio"],
            volume_window=config["volume_window"],
            min_volume_ratio=config["min_volume_ratio"],
            flat_at_close=config["flat_at_close"],
            max_open_positions=config["max_open_positions"],
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "ema_cross":
        summary, _ = ema_cross.run_portfolio_backtest(
            histories=data.minute_histories(),
            pool_cache=data.minute_pool_cache(),
            initial_cash=initial_cash,
            fast_span=config["fast_span"],
            slow_span=config["slow_span"],
            position_ratio=config["position_ratio"],
            volume_window=config["volume_window"],
            min_volume_ratio=config["min_volume_ratio"],
            flat_at_close=config["flat_at_close"],
            max_open_positions=config["max_open_positions"],
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "ema_rsi_combo":
        summary, _ = ema_rsi_combo.run_portfolio_backtest(
            histories=data.minute_histories(),
            pool_cache=data.minute_pool_cache(),
            initial_cash=initial_cash,
            fast_span=config["fast_span"],
            slow_span=config["slow_span"],
            rsi_period=config["rsi_period"],
            buy_threshold=config["buy_threshold"],
            sell_threshold=config["sell_threshold"],
            position_ratio=config["position_ratio"],
            volume_window=config["volume_window"],
            min_volume_ratio=config["min_volume_ratio"],
            flat_at_close=config["flat_at_close"],
            max_open_positions=config["max_open_positions"],
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "ema_rsi_bull_range":
        summary, _ = ema_rsi_combo.run_portfolio_backtest(
            histories=data.minute_histories(),
            pool_cache=data.minute_pool_cache(),
            initial_cash=initial_cash,
            fast_span=config["fast_span"],
            slow_span=config["slow_span"],
            rsi_period=config["rsi_period"],
            buy_threshold=config["buy_threshold"],
            sell_threshold=config["sell_threshold"],
            position_ratio=config["position_ratio"],
            volume_window=config["volume_window"],
            min_volume_ratio=config["min_volume_ratio"],
            flat_at_close=config["flat_at_close"],
            max_open_positions=config["max_open_positions"],
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "dual_momentum":
        prices, volumes = data.daily_prices_volumes()
        summary, _ = dual_momentum.run_backtest(
            prices=prices,
            volumes=volumes,
            initial_cash=initial_cash,
            lookback_days=config["lookback_days"],
            long_lookback_days=config["long_lookback_days"],
            long_lookback_weight=config["long_lookback_weight"],
            top_n=config["top_n"],
            volume_window=config["volume_window"],
            min_volume_ratio=config["min_volume_ratio"],
            market_filter_window=config["market_filter_window"],
            rebalance_band_pct=config["rebalance_band_pct"],
            volatility_window=config["volatility_window"],
            target_annual_vol=config["target_annual_vol"],
            max_gross_exposure=config["max_gross_exposure"],
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "momentum_monthly":
        prices, _ = data.daily_prices_volumes()
        summary, _ = momentum_monthly.run_monthly_momentum(
            prices=prices,
            initial_cash=initial_cash,
            lookback_days=config["lookback_days"],
            top_n=config["top_n"],
            rebalance_band_pct=config["rebalance_band_pct"],
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    if strategy_key == "dual_momentum_ema_rsi_hybrid":
        summary, _ = hybrid.run_backtest(
            closes=data.daily_closes(),
            minute_indicators=data.hybrid_minute_indicators(
                fast_span=config["fast_span"],
                slow_span=config["slow_span"],
                rsi_period=config["rsi_period"],
            ),
            initial_cash=initial_cash,
            lookback_days=config["lookback_days"],
            long_lookback_days=config["long_lookback_days"],
            long_lookback_weight=config["long_lookback_weight"],
            market_filter_window=config["market_filter_window"],
            daily_vol_window=config["daily_vol_window"],
            min_momentum_score=config["min_momentum_score"],
            rebalance_days=config["rebalance_days"],
            switch_score_buffer=config["switch_score_buffer"],
            min_hold_days=config["min_hold_days"],
            timing_score_weight=config["timing_score_weight"],
            entry_rsi_min=config["entry_rsi_min"],
            entry_rsi_max=config["entry_rsi_max"],
            exit_rsi_min=config["exit_rsi_min"],
            stop_loss_pct=config["stop_loss_pct"],
            take_profit_pct=config["take_profit_pct"],
            position_ratio=config["position_ratio"],
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=fee_account,
            market=market,
            security_type=security_type,
        )
        return summary

    raise ValueError(f"unsupported strategy: {strategy_key}")


def _build_table(rows: list[dict]) -> str:
    return build_strategy_summary_table(
        sorted(rows, key=lambda row: (-float(row["return_pct"]), str(row["strategy"])))
    )


def main() -> int:
    args = parse_args()
    selected = _dedupe(args.strategy or list(DEFAULT_STRATEGIES))
    if args.dump_default_strategy_config:
        print(_dump_default_strategy_config(selected))
        return 0
    if args.market is None:
        raise ValueError("--market is required unless --dump-default-strategy-config is used")

    codes = _dedupe([str(code).strip().upper() for code in args.codes if str(code).strip()])
    if not codes:
        raise ValueError("--codes must include at least one code")

    market = validate_market_for_symbols(codes, normalize_market(args.market), label="--codes")
    eval_start = parse_eval_start(args.eval_start)
    eval_end = parse_eval_end(args.eval_end)
    if eval_start is not None and eval_end is not None and eval_start > eval_end:
        raise ValueError("eval-start must be earlier than or equal to eval-end")

    initial_cash = default_initial_cash_for_market(market) if args.initial_cash is None else float(args.initial_cash)
    strategy_params = _resolve_strategy_params(args)

    data = BatchDataContext(
        codes=codes,
        minute_data_root=args.minute_data_root,
        daily_data_root=args.daily_data_root,
    )

    batch_started_at = perf_counter()
    rows: list[dict] = []
    for strategy_key in selected:
        load_before = data.snapshot().total_load_seconds
        strategy_started_at = perf_counter()
        summary = _run_strategy(
            strategy_key,
            data=data,
            strategy_params=strategy_params,
            initial_cash=initial_cash,
            eval_start=eval_start,
            eval_end=eval_end,
            fee_account=args.fee_account,
            market=market,
            security_type=args.security_type,
        )
        strategy_elapsed = perf_counter() - strategy_started_at
        load_after = data.snapshot().total_load_seconds
        strategy_compute_seconds = max(0.0, strategy_elapsed - (load_after - load_before))
        rows.append(build_strategy_summary_row(strategy_key, summary, strategy_compute_seconds))

    total_elapsed = perf_counter() - batch_started_at
    stats = data.snapshot()
    print(_build_table(rows))
    print()
    print(f"Backtest total time: {total_elapsed:.2f}s")
    print(f"Evaluation window: {eval_start if eval_start is not None else 'START'} -> {eval_end if eval_end is not None else 'END'}")
    print(f"Filesystem load time: {stats.total_load_seconds:.2f}s")
    print(f"Files loaded: {stats.files_loaded}")
    print(f"Load operations: {stats.load_operations}")
    coverage_sections: list[tuple[str, dict[str, pd.DatetimeIndex]]] = []
    daily_observations = data.loaded_daily_observations()
    minute_observations = data.loaded_minute_observations()
    if daily_observations:
        coverage_sections.append(("Daily data coverage", daily_observations))
    if minute_observations:
        coverage_sections.append(("Minute data coverage", minute_observations))
    if coverage_sections:
        print()
        for line in render_data_coverage_sections(
            coverage_sections,
            expected_start=eval_start,
            expected_end=eval_end,
        ):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
