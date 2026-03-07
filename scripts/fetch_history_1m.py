#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
import os
from pathlib import Path
import sys

import pandas as pd


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11111
MAX_COUNT = 1000
MINUTE_COLUMNS = [
    "time_key",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "turnover",
    "last_close",
]


def prepare_futu_home() -> None:
    default_log_root = Path(os.environ.get("HOME", str(Path.home()))) / ".com.futunn.FutuOpenD"
    try:
        default_log_root.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        os.environ["HOME"] = str(Path.cwd())


def load_futu():
    prepare_futu_home()
    from futu import KLType, OpenQuoteContext, RET_OK

    return KLType, OpenQuoteContext, RET_OK


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch 1-minute historical K-line data for a stock via Futu OpenD."
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--code", required=True, help="Security code, for example HK.00700.")
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD format.")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Keep existing CSV files outside the requested date range instead of removing them.",
    )
    return parser.parse_args()


def resolve_dates(start: str, end: str) -> tuple[str, str]:
    end_date = date.fromisoformat(end)
    start_date = date.fromisoformat(start)
    if start_date > end_date:
        raise ValueError("start date must be earlier than or equal to end date")
    return start_date.isoformat(), end_date.isoformat()


def fetch_history(host: str, port: int, code: str, start: str, end: str):
    KLType, OpenQuoteContext, RET_OK = load_futu()
    quote_ctx = OpenQuoteContext(host=host, port=port)
    frames = []
    page_req_key = None
    try:
        while True:
            ret, data, page_req_key = quote_ctx.request_history_kline(
                code,
                start=start,
                end=end,
                ktype=KLType.K_1M,
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

    return pd.concat(frames, ignore_index=True)


def remove_stale_daily_files(output_root: Path, expected_names: set[str]) -> int:
    if not output_root.exists():
        return 0

    removed = 0
    for path in output_root.glob("*.csv"):
        if path.name not in expected_names:
            path.unlink()
            removed += 1
    return removed


def save_daily_files(history, output_root: Path, keep_existing: bool) -> tuple[int, int]:
    existing_columns = [column for column in MINUTE_COLUMNS if column in history.columns]
    trimmed = history.loc[:, existing_columns].copy()
    trimmed["trade_date"] = trimmed["time_key"].str.slice(0, 10)
    code = str(history["code"].iloc[0]) if "code" in history.columns and not history.empty else output_root.name

    output_root.mkdir(parents=True, exist_ok=True)
    expected_names = {f"{code}_{trade_date}.csv" for trade_date in trimmed["trade_date"].unique()}
    removed_count = 0 if keep_existing else remove_stale_daily_files(output_root, expected_names)
    count = 0
    for trade_date, daily in trimmed.groupby("trade_date", sort=True):
        daily_path = output_root / f"{code}_{trade_date}.csv"
        daily.drop(columns=["trade_date"]).to_csv(daily_path, index=False)
        count += 1
    return count, removed_count


def main() -> int:
    args = parse_args()
    start, end = resolve_dates(args.start, args.end)
    output_root = Path(args.output_dir) / args.code

    history = fetch_history(args.host, args.port, args.code, start, end)
    file_count, removed_count = save_daily_files(history, output_root, keep_existing=args.keep_existing)

    print(f"Fetched {len(history)} rows for {args.code} from {start} to {end}.")
    print(f"Wrote {file_count} daily files to {output_root}.")
    if args.keep_existing:
        print("Kept existing CSV files outside the requested date range.")
    else:
        print(f"Removed {removed_count} stale daily files outside the requested date range.")
    print(f"Columns: {', '.join(column for column in MINUTE_COLUMNS if column in history.columns)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
