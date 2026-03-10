#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import pandas as pd


MINUTE_COLUMNS = [
    "time_key",
    "open",
    "close",
    "high",
    "low",
    "volume",
]


def remove_stale_daily_files(output_root: Path, expected_names: set[str]) -> int:
    if not output_root.exists():
        return 0

    removed = 0
    for path in output_root.glob("*.csv"):
        if path.name not in expected_names:
            path.unlink()
            removed += 1
    return removed


def save_daily_files(
    history: pd.DataFrame, output_root: Path, keep_existing: bool, code: str | None = None
) -> tuple[int, int]:
    existing_columns = [column for column in MINUTE_COLUMNS if column in history.columns]
    trimmed = history.loc[:, existing_columns].copy()
    trimmed["trade_date"] = trimmed["time_key"].str.slice(0, 10)
    resolved_code = (
        code
        or (str(history["code"].iloc[0]) if "code" in history.columns and not history.empty else output_root.name)
    )

    output_root.mkdir(parents=True, exist_ok=True)
    expected_names = {f"{resolved_code}_{trade_date}.csv" for trade_date in trimmed["trade_date"].unique()}
    removed_count = 0 if keep_existing else remove_stale_daily_files(output_root, expected_names)
    count = 0
    for trade_date, daily in trimmed.groupby("trade_date", sort=True):
        daily_path = output_root / f"{resolved_code}_{trade_date}.csv"
        daily.drop(columns=["trade_date"]).to_csv(daily_path, index=False)
        count += 1
    return count, removed_count
