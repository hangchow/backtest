#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

try:
    from fetch_futu_1m import DEFAULT_HOST, DEFAULT_PORT, MAX_COUNT, load_futu, resolve_dates
except ModuleNotFoundError:  # package-style import
    from .fetch_futu_1m import DEFAULT_HOST, DEFAULT_PORT, MAX_COUNT, load_futu, resolve_dates


DAILY_COLUMNS = ["time_key", "open", "close", "high", "low", "volume"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch daily historical K-line data for a stock via Futu OpenD."
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--code", required=True, help="Security code, for example HK.00700.")
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD format.")
    parser.add_argument("--output-dir", default="kline_day")
    return parser.parse_args()


def fetch_history(host: str, port: int, code: str, start: str, end: str) -> pd.DataFrame:
    KLType, OpenQuoteContext, RET_OK = load_futu()
    quote_ctx = OpenQuoteContext(host=host, port=port)
    frames: list[pd.DataFrame] = []
    page_req_key = None
    try:
        while True:
            ret, data, page_req_key = quote_ctx.request_history_kline(
                code,
                start=start,
                end=end,
                ktype=KLType.K_DAY,
                max_count=MAX_COUNT,
                page_req_key=page_req_key,
            )
            if ret != RET_OK:
                raise RuntimeError(f"request_history_kline failed: {data}")
            frames.append(data)
            if page_req_key is None:
                break
    finally:
        quote_ctx.close()

    if not frames:
        raise RuntimeError("No data returned from request_history_kline.")

    history = pd.concat(frames, ignore_index=True)
    if history.empty:
        raise RuntimeError("No data returned from request_history_kline.")
    history = history.loc[:, [column for column in DAILY_COLUMNS if column in history.columns]].copy()
    history["time_key"] = pd.to_datetime(history["time_key"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    history["trade_date"] = pd.to_datetime(history["time_key"]).dt.normalize()
    history["week_start"] = history["trade_date"] - pd.to_timedelta(history["trade_date"].dt.weekday, unit="D")
    return history


def merge_weekly_payload(file_path: Path, weekly: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    incoming = weekly.loc[:, columns].copy()
    if not file_path.exists():
        return incoming

    try:
        existing = pd.read_csv(file_path, usecols=lambda column: column in columns)
    except pd.errors.EmptyDataError:
        existing = pd.DataFrame(columns=columns)

    if existing.empty:
        return incoming

    merged = pd.concat([existing, incoming], ignore_index=True)
    merged["time_key"] = pd.to_datetime(merged["time_key"])
    merged = merged.sort_values("time_key").drop_duplicates(subset=["time_key"], keep="last").reset_index(drop=True)
    merged["time_key"] = merged["time_key"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return merged.loc[:, columns]


def save_weekly_files(history: pd.DataFrame, output_root: Path, code: str) -> int:
    output_root.mkdir(parents=True, exist_ok=True)
    count = 0
    for week_start, weekly in history.groupby("week_start", sort=True):
        weekly_path = output_root / f"{code}_{week_start.date().isoformat()}.csv"
        merged_weekly = merge_weekly_payload(weekly_path, weekly, DAILY_COLUMNS)
        merged_weekly.to_csv(weekly_path, index=False)
        count += 1
    return count


def main() -> int:
    args = parse_args()
    start, end = resolve_dates(args.start, args.end)
    output_root = Path(args.output_dir) / args.code

    history = fetch_history(args.host, args.port, args.code, start, end)
    file_count = save_weekly_files(history, output_root, args.code)

    print(f"Fetched {len(history)} rows for {args.code} from {start} to {end}.")
    print(f"Wrote {file_count} weekly files to {output_root}.")
    print(f"Columns: {', '.join(DAILY_COLUMNS)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
