#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
import io
import json
import os
from pathlib import Path
import ssl
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from fetch_history_1m import save_daily_files


BASE_URL = "https://www.alphavantage.co/query"
DEFAULT_OUTPUT_DIR = Path("data")
DEFAULT_INTERVAL = "1min"
DEFAULT_RATE_LIMIT_SECONDS = 1.2
CSV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
LOCAL_COLUMNS = ["time_key", "open", "close", "high", "low", "volume"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch 1-minute historical K-line data from Alpha Vantage and convert it "
            "to the repository's daily CSV layout."
        )
    )
    parser.add_argument("--symbol", required=True, help="Alpha Vantage symbol, for example MSFT.")
    parser.add_argument(
        "--code",
        default=None,
        help="Output code prefix for filenames/directories. Defaults to the symbol.",
    )
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD format.")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ALPHA_VANTAGE_API_KEY"),
        help="Alpha Vantage API key. Defaults to ALPHA_VANTAGE_API_KEY.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, choices=["1min", "5min", "15min", "30min", "60min"])
    parser.add_argument(
        "--extended-hours",
        action="store_true",
        help="Include pre-market and post-market data. By default only regular trading hours are requested.",
    )
    parser.add_argument(
        "--adjusted",
        action="store_true",
        help="Request split/dividend-adjusted intraday data. By default raw as-traded data is requested.",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Keep existing CSV files outside the requested date range instead of removing them.",
    )
    parser.add_argument(
        "--rate-limit-seconds",
        type=float,
        default=DEFAULT_RATE_LIMIT_SECONDS,
        help="Delay between month requests to avoid Alpha Vantage rate limiting.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for environments with a broken CA bundle.",
    )
    return parser.parse_args()


def resolve_dates(start: str, end: str) -> tuple[date, date]:
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if start_date > end_date:
        raise ValueError("start date must be earlier than or equal to end date")
    return start_date, end_date


def iter_months(start_date: date, end_date: date) -> list[str]:
    current_year = start_date.year
    current_month = start_date.month
    months: list[str] = []
    while (current_year, current_month) <= (end_date.year, end_date.month):
        months.append(f"{current_year:04d}-{current_month:02d}")
        if current_month == 12:
            current_year += 1
            current_month = 1
        else:
            current_month += 1
    return months


def build_query_url(
    symbol: str,
    month: str,
    interval: str,
    api_key: str,
    adjusted: bool,
    extended_hours: bool,
) -> str:
    params = {
        "function": "TIME_SERIES_INTRADAY",
        "symbol": symbol,
        "interval": interval,
        "month": month,
        "outputsize": "full",
        "extended_hours": str(extended_hours).lower(),
        "adjusted": str(adjusted).lower(),
        "datatype": "csv",
        "apikey": api_key,
    }
    return f"{BASE_URL}?{urlencode(params)}"


def open_url(url: str, insecure: bool) -> str:
    ssl_context = ssl._create_unverified_context() if insecure else None
    with urlopen(url, context=ssl_context, timeout=60) as response:
        return response.read().decode("utf-8")


def parse_csv_payload(payload: str) -> pd.DataFrame:
    stripped = payload.lstrip()
    if stripped.startswith("{"):
        response = json.loads(payload)
        detail = response.get("Information") or response.get("Note") or response.get("Error Message") or payload
        raise RuntimeError(str(detail))

    frame = pd.read_csv(io.StringIO(payload))
    missing_columns = [column for column in CSV_COLUMNS if column not in frame.columns]
    if missing_columns:
        raise RuntimeError(f"unexpected Alpha Vantage CSV columns: missing {', '.join(missing_columns)}")
    return frame


def fetch_month(
    symbol: str,
    month: str,
    interval: str,
    api_key: str,
    adjusted: bool,
    extended_hours: bool,
    insecure: bool,
) -> pd.DataFrame:
    url = build_query_url(symbol, month, interval, api_key, adjusted, extended_hours)
    payload = open_url(url, insecure=insecure)
    return parse_csv_payload(payload)


def convert_to_local_layout(history: pd.DataFrame, start_date: date, end_date: date) -> pd.DataFrame:
    renamed = history.rename(columns={"timestamp": "time_key"}).copy()
    renamed["time_key"] = pd.to_datetime(renamed["time_key"])
    renamed = renamed.sort_values("time_key").reset_index(drop=True)

    for column in ["open", "close", "high", "low"]:
        renamed[column] = renamed[column].astype(float)
    renamed["volume"] = renamed["volume"].astype(int)

    mask = (renamed["time_key"].dt.date >= start_date) & (renamed["time_key"].dt.date <= end_date)
    trimmed = renamed.loc[mask, LOCAL_COLUMNS].copy()
    trimmed["time_key"] = trimmed["time_key"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return trimmed.reset_index(drop=True)


def fetch_history(
    symbol: str,
    start_date: date,
    end_date: date,
    api_key: str,
    interval: str,
    adjusted: bool,
    extended_hours: bool,
    rate_limit_seconds: float,
    insecure: bool,
) -> pd.DataFrame:
    months = iter_months(start_date, end_date)
    frames: list[pd.DataFrame] = []
    for index, month in enumerate(months):
        frames.append(
            fetch_month(
                symbol=symbol,
                month=month,
                interval=interval,
                api_key=api_key,
                adjusted=adjusted,
                extended_hours=extended_hours,
                insecure=insecure,
            )
        )
        if index + 1 < len(months):
            time.sleep(rate_limit_seconds)

    if not frames:
        raise RuntimeError("No data returned from Alpha Vantage.")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
    return convert_to_local_layout(combined, start_date, end_date)


def main() -> int:
    args = parse_args()
    if not args.api_key:
        raise ValueError("missing Alpha Vantage API key; pass --api-key or set ALPHA_VANTAGE_API_KEY")

    start_date, end_date = resolve_dates(args.start, args.end)
    code = args.code or args.symbol
    output_root = args.output_dir / code
    history = fetch_history(
        symbol=args.symbol,
        start_date=start_date,
        end_date=end_date,
        api_key=args.api_key,
        interval=args.interval,
        adjusted=args.adjusted,
        extended_hours=args.extended_hours,
        rate_limit_seconds=args.rate_limit_seconds,
        insecure=args.insecure,
    )
    if history.empty:
        raise RuntimeError(f"No rows returned for {args.symbol} between {args.start} and {args.end}.")

    file_count, removed_count = save_daily_files(
        history=history,
        output_root=output_root,
        keep_existing=args.keep_existing,
        code=code,
    )

    print(f"Fetched {len(history)} rows for {args.symbol} from {args.start} to {args.end}.")
    print(f"Wrote {file_count} daily files to {output_root}.")
    if args.keep_existing:
        print("Kept existing CSV files outside the requested date range.")
    else:
        print(f"Removed {removed_count} stale daily files outside the requested date range.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
