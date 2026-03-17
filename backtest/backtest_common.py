from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategy.fees import FEE_ACCOUNT_PROFILES, compute_order_fees
from strategy.volume import compute_relative_volume, compute_volume_scale, validate_volume_filter


DEFAULT_DATA_ROOT = Path("kline_minute")
SUPPORTED_BACKTEST_MARKETS = ("HK", "US")


def add_data_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory with minute CSV files. Cannot be used with --codes.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="Base directory for per-code datasets when using --codes.",
    )
    parser.add_argument(
        "--codes",
        nargs="+",
        default=None,
        help="Optional stock pool codes under --data-root, for example US.MSFT US.NVDA.",
    )


def add_fee_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fee-account",
        type=str,
        default=None,
        help=(
            "Optional fee account profile. Supported values: "
            + ", ".join(sorted(FEE_ACCOUNT_PROFILES))
            + "."
        ),
    )
    parser.add_argument(
        "--security-type",
        type=str,
        default="stock",
        help="Security type used by fee rules (stock/etf/warrant/cbbc).",
    )


def normalize_market(market: str, *, label: str = "market") -> str:
    normalized = str(market or "").strip().upper()
    if normalized not in SUPPORTED_BACKTEST_MARKETS:
        supported = ", ".join(SUPPORTED_BACKTEST_MARKETS)
        raise ValueError(f"{label} must be one of: {supported}")
    return normalized


def extract_market_from_symbol(symbol: str) -> str | None:
    normalized = str(symbol or "").strip().upper()
    if normalized.startswith("HK."):
        return "HK"
    if normalized.startswith("US."):
        return "US"
    return None


def validate_market_for_symbols(symbols: list[str], market: str, *, label: str) -> str:
    normalized_market = normalize_market(market)
    encoded_markets = sorted({item for symbol in symbols if (item := extract_market_from_symbol(symbol)) is not None})
    if len(encoded_markets) > 1:
        raise ValueError(f"{label} must all belong to the same market, got: {', '.join(encoded_markets)}")
    if encoded_markets and encoded_markets[0] != normalized_market:
        raise ValueError(f"{label} encode market {encoded_markets[0]} but --market is {normalized_market}")
    return normalized_market


def validate_market_for_symbol(symbol: str, market: str, *, label: str) -> str:
    return validate_market_for_symbols([symbol], market, label=label)


def add_market_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--market",
        type=normalize_market,
        required=True,
        help="Trading market used by the backtest. Required; backtest scripts do not infer a default market.",
    )


def add_volume_filter_args(
    parser: argparse.ArgumentParser,
    default_volume_window: int,
    default_min_volume_ratio: float,
    label: str = "buy",
) -> None:
    parser.add_argument(
        "--volume-window",
        type=int,
        default=default_volume_window,
        help=f"Rolling window used to compare current volume against recent average volume for {label} signals.",
    )
    parser.add_argument(
        "--min-volume-ratio",
        type=float,
        default=default_min_volume_ratio,
        help=f"Minimum current-volume / recent-average-volume ratio required for {label} signals.",
    )


def add_eval_start_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--eval-start",
        default=None,
        help=(
            "Optional evaluation start date/time. Bars before this point are used only "
            "for indicator warm-up and are excluded from trades and PnL statistics."
        ),
    )


def add_eval_end_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--eval-end",
        default=None,
        help=(
            "Optional evaluation end date/time. Bars after this point are excluded "
            "from trades and PnL statistics."
        ),
    )


def resolve_data_dir(data_dir: Path | None) -> Path:
    if data_dir is not None:
        return data_dir
    raise ValueError("either --data-dir or --codes must be provided")


def resolve_codes(data_root: Path, codes: list[str] | None) -> list[str]:
    if not codes:
        return []

    normalized = [item.strip() for item in codes if item and item.strip()]
    if not normalized:
        raise ValueError("--codes must include at least one non-empty code")

    missing = [code for code in normalized if not (data_root / code).is_dir()]
    if missing:
        missing_text = ", ".join(missing)
        raise FileNotFoundError(f"Missing code directories under {data_root}: {missing_text}")
    return normalized


def normalize_max_open_positions(max_open_positions: int, universe_size: int) -> int:
    if universe_size <= 0:
        raise ValueError("universe_size must be positive")
    if max_open_positions == -1:
        return universe_size
    if max_open_positions <= 0:
        raise ValueError("max-open-positions must be positive or -1 for unlimited")
    return min(max_open_positions, universe_size)


def parse_eval_start(eval_start: str | None) -> pd.Timestamp | None:
    if eval_start is None:
        return None
    try:
        return pd.Timestamp(eval_start)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid eval-start: {eval_start}") from exc


def parse_eval_end(eval_end: str | None) -> pd.Timestamp | None:
    if eval_end is None:
        return None
    try:
        parsed = pd.Timestamp(eval_end)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid eval-end: {eval_end}") from exc
    if isinstance(eval_end, str):
        normalized = eval_end.strip()
        if normalized and " " not in normalized and "T" not in normalized:
            return parsed + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    return parsed


def resolve_eval_window(
    values,
    eval_start: pd.Timestamp | None = None,
    eval_end: pd.Timestamp | None = None,
) -> tuple[list[bool], Any, Any, Any]:
    raw_values = list(values)
    if not raw_values:
        raise ValueError("cannot resolve evaluation window from empty values")
    if eval_start is not None and eval_end is not None and eval_start > eval_end:
        raise ValueError("eval-start must be earlier than or equal to eval-end")

    comparable = pd.to_datetime(raw_values)
    mask = pd.Series(True, index=range(len(raw_values)))
    if eval_start is not None:
        mask &= comparable >= eval_start
    if eval_end is not None:
        mask &= comparable <= eval_end

    selected_positions = [idx for idx, include in enumerate(mask.tolist()) if include]
    if not selected_positions:
        raise ValueError("evaluation window does not overlap the available data range")

    return (
        mask.tolist(),
        raw_values[0],
        raw_values[selected_positions[0]],
        raw_values[selected_positions[-1]],
    )


def load_histories(data_root: Path, codes: list[str]) -> dict[str, pd.DataFrame]:
    if not codes:
        raise ValueError("codes must not be empty")
    return {code: load_history(data_root / code) for code in codes}


def load_history(data_dir: Path) -> pd.DataFrame:
    files = sorted(data_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")

    frames = [pd.read_csv(path) for path in files]
    history = pd.concat(frames, ignore_index=True)
    history["time_key"] = pd.to_datetime(history["time_key"])
    history = history.sort_values("time_key").reset_index(drop=True)
    history["trade_date"] = history["time_key"].dt.date
    history["is_day_end"] = history["trade_date"] != history["trade_date"].shift(-1)
    return history


def compute_buy_quantity_with_fees(
    *,
    budget: float,
    price: float,
    fee_account: str | None,
    market: str,
    security_type: str,
) -> tuple[int, float, dict[str, float]]:
    qty = int(float(budget) // float(price))
    while qty > 0:
        fee_total, breakdown = compute_order_fees(
            fee_account=fee_account,
            market=market,
            side="buy",
            price=price,
            shares=qty,
            security_type=security_type,
        )
        total_cost = qty * float(price) + fee_total
        if total_cost <= budget:
            return qty, fee_total, breakdown
        qty -= 1
    return 0, 0.0, {}
