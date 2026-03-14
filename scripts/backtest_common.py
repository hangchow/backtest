from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_DATA_ROOT = Path("data")


FEE_ACCOUNT_PROFILES: dict[str, dict[str, list[dict[str, Any]]]] = {
    "futu_standard": {
        "HK": [
            {"name": "commission", "basis": "notional", "rate": 0.0003, "min_fee": 3.0, "side": "both"},
            {"name": "platform_fee", "basis": "fixed", "fixed": 15.0, "side": "both"},
            {"name": "settlement_fee", "basis": "notional", "rate": 0.000042, "side": "both"},
            {
                "name": "stamp_duty",
                "basis": "notional",
                "rate": 0.001,
                "min_fee": 1.0,
                "side": "both",
                "exempt_security_types": {"etf", "warrant", "cbbc"},
            },
            {"name": "trading_fee", "basis": "notional", "rate": 0.0000565, "min_fee": 0.01, "side": "both"},
            {"name": "sfc_levy", "basis": "notional", "rate": 0.000027, "min_fee": 0.01, "side": "both"},
            {"name": "afr_levy", "basis": "notional", "rate": 0.0000015, "side": "both"},
        ],
        "US": [
            {
                "name": "commission",
                "basis": "shares",
                "rate": 0.0049,
                "min_fee": 0.99,
                "max_pct_notional": 0.005,
                "side": "both",
            },
            {
                "name": "platform_fee",
                "basis": "shares",
                "rate": 0.005,
                "min_fee": 1.0,
                "max_pct_notional": 0.005,
                "side": "both",
            },
            {"name": "settlement_fee", "basis": "shares", "rate": 0.003, "side": "both"},
            {
                "name": "taf",
                "basis": "shares",
                "rate": 0.000195,
                "min_fee": 0.01,
                "max_fee": 9.79,
                "side": "sell",
            },
        ],
    },
    "futu_alt": {},
}
FEE_ACCOUNT_PROFILES["futu_alt"] = FEE_ACCOUNT_PROFILES["futu_standard"]


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


def validate_volume_filter(volume_window: int, min_volume_ratio: float) -> None:
    if volume_window <= 0:
        raise ValueError("volume-window must be positive")
    if min_volume_ratio <= 0:
        raise ValueError("min-volume-ratio must be positive")


def compute_relative_volume(volume: pd.Series, volume_window: int) -> pd.Series:
    validate_volume_filter(volume_window, 1e-9)
    baseline = volume.shift(1).rolling(window=volume_window, min_periods=1).mean()
    relative_volume = (volume / baseline).replace([float("inf"), float("-inf")], pd.NA)
    relative_volume = relative_volume.where(volume.notna(), pd.NA)
    relative_volume = relative_volume.mask(volume.notna() & baseline.isna(), 1.0)
    return pd.to_numeric(relative_volume, errors="coerce")


def compute_volume_scale(
    volume_ratio: float,
    min_volume_ratio: float,
    min_scale: float = 0.5,
    max_scale: float = 1.25,
) -> float:
    validate_volume_filter(1, min_volume_ratio)
    if min_scale <= 0 or max_scale <= 0 or min_scale > max_scale:
        raise ValueError("volume scale bounds must be positive and ordered")
    if pd.isna(volume_ratio) or volume_ratio <= 0:
        return float(min_scale)
    normalized_ratio = float(volume_ratio) / min_volume_ratio
    return max(min_scale, min(max_scale, normalized_ratio))


def parse_eval_start(eval_start: str | None) -> pd.Timestamp | None:
    if eval_start is None:
        return None
    try:
        return pd.Timestamp(eval_start)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid eval-start: {eval_start}") from exc


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


def infer_market_from_code(code: str) -> str:
    if code.startswith("HK."):
        return "HK"
    if code.startswith("US."):
        return "US"
    raise ValueError(f"Cannot infer market from code: {code}")


def infer_market_from_codes(codes: list[str]) -> str:
    if not codes:
        raise ValueError("codes must not be empty")
    markets = {infer_market_from_code(code) for code in codes}
    if len(markets) != 1:
        raise ValueError(f"All codes must be in the same market, got: {sorted(markets)}")
    return next(iter(markets))


def compute_order_fees(
    *,
    fee_account: str | None,
    market: str,
    side: str,
    price: float,
    shares: int,
    security_type: str = "stock",
) -> tuple[float, dict[str, float]]:
    if not fee_account:
        return 0.0, {}
    if shares <= 0:
        return 0.0, {}
    if fee_account not in FEE_ACCOUNT_PROFILES:
        supported = ", ".join(sorted(FEE_ACCOUNT_PROFILES))
        raise ValueError(f"Unsupported fee-account: {fee_account}. Supported: {supported}")

    profile = FEE_ACCOUNT_PROFILES[fee_account]
    if market not in profile:
        raise ValueError(f"fee-account {fee_account} does not define market {market}")

    notional = float(price) * int(shares)
    result: dict[str, float] = {}
    total = 0.0
    for rule in profile[market]:
        rule_side = str(rule.get("side", "both"))
        if rule_side != "both" and rule_side != side:
            continue
        exempt_types = set(rule.get("exempt_security_types", set()))
        if security_type in exempt_types:
            continue

        basis = rule["basis"]
        if basis == "notional":
            fee = notional * float(rule.get("rate", 0.0))
        elif basis == "shares":
            fee = int(shares) * float(rule.get("rate", 0.0))
        elif basis == "fixed":
            fee = float(rule.get("fixed", 0.0))
        else:
            raise ValueError(f"Unsupported fee basis: {basis}")

        min_fee = rule.get("min_fee")
        max_fee = rule.get("max_fee")
        max_pct_notional = rule.get("max_pct_notional")
        if min_fee is not None:
            fee = max(fee, float(min_fee))
        if max_fee is not None:
            fee = min(fee, float(max_fee))
        if max_pct_notional is not None:
            fee = min(fee, notional * float(max_pct_notional))

        fee = round(fee, 2)
        if fee <= 0:
            continue
        result[str(rule["name"])] = fee
        total += fee

    return round(total, 2), result


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
