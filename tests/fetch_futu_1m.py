#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
import os
from pathlib import Path
import sys

import pandas as pd

try:
    from minute_csv_utils import MINUTE_COLUMNS, save_daily_files
except ModuleNotFoundError:  # package-style import
    from .minute_csv_utils import MINUTE_COLUMNS, save_daily_files


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11111
MAX_COUNT = 1000
FUTU_RUNTIME_ENV = "FUTU_RUNTIME_HOME"
DEFAULT_FUTU_RUNTIME_DIRNAME = ".futu_runtime"


def prepare_futu_home() -> Path:
    runtime_home = Path(
        os.environ.get(FUTU_RUNTIME_ENV, str(Path.cwd() / DEFAULT_FUTU_RUNTIME_DIRNAME))
    ).resolve()
    runtime_log_root = runtime_home / ".com.futunn.FutuOpenD" / "Log"
    runtime_log_root.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(runtime_home)
    return runtime_home


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
    parser.add_argument("--output-dir", default="kline_minute")
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

def main() -> int:
    args = parse_args()
    start, end = resolve_dates(args.start, args.end)
    output_root = Path(args.output_dir) / args.code

    history = fetch_history(args.host, args.port, args.code, start, end)
    file_count, removed_count = save_daily_files(
        history,
        output_root,
        keep_existing=args.keep_existing,
        code=args.code,
    )

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
