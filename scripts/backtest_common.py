from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


DEFAULT_DATA_ROOT = Path("data")


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
