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
        help="Directory with minute CSV files. Overrides --code when both are set.",
    )
    parser.add_argument("--code", help="Security code to load from --data-root, for example HK.00700.")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="Base directory for per-code datasets when using --code.",
    )


def resolve_data_dir(data_dir: Path | None, code: str | None, data_root: Path) -> Path:
    if data_dir is not None:
        return data_dir
    if code:
        return data_root / code
    raise ValueError("either --data-dir or --code must be provided")


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
