#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
from datetime import date, time
import json
import os
from pathlib import Path
import ssl
import sys
import time as sleep_time
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pandas as pd

try:
    from minute_csv_utils import save_daily_files
except ModuleNotFoundError:  # package-style import
    from .minute_csv_utils import save_daily_files


BASE_URL = "https://api.polygon.io/v2/aggs/ticker"
DEFAULT_OUTPUT_DIR = Path("data")
DEFAULT_RATE_LIMIT_SECONDS = 13.0
NEW_YORK = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE_EXCLUSIVE = time(16, 0)
LOCAL_COLUMNS = ["time_key", "open", "close", "high", "low", "volume"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch 1-minute historical bars from Polygon and convert them to the "
            "repository's daily CSV layout."
        )
    )
    parser.add_argument("--symbol", required=True, help="Polygon stock ticker, for example MSFT.")
    parser.add_argument(
        "--code",
        default=None,
        help="Output code prefix for filenames/directories. Defaults to the symbol.",
    )
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD format.")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("POLYGON_API_KEY"),
        help="Polygon API key. Defaults to POLYGON_API_KEY.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--adjusted",
        action="store_true",
        help="Request split-adjusted data. By default raw as-traded prices are requested.",
    )
    parser.add_argument(
        "--include-extended-hours",
        action="store_true",
        help="Keep pre-market and post-market bars. By default only 09:30-16:00 ET is kept.",
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
        help="Delay between requests. Polygon Stocks Basic currently allows 5 API calls per minute.",
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


def iter_month_ranges(start_date: date, end_date: date) -> list[tuple[date, date]]:
    current = date(start_date.year, start_date.month, 1)
    ranges: list[tuple[date, date]] = []
    while current <= end_date:
        last_day = calendar.monthrange(current.year, current.month)[1]
        month_end = date(current.year, current.month, last_day)
        ranges.append((max(start_date, current), min(end_date, month_end)))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return ranges


def build_url(symbol: str, start_date: date, end_date: date, adjusted: bool, api_key: str) -> str:
    query = urlencode({"adjusted": str(adjusted).lower(), "sort": "asc", "limit": 50000, "apiKey": api_key})
    return f"{BASE_URL}/{symbol}/range/1/minute/{start_date.isoformat()}/{end_date.isoformat()}?{query}"


def with_api_key(url: str, api_key: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("apiKey", api_key)
    return urlunparse(parsed._replace(query=urlencode(query)))


def open_json(url: str, insecure: bool) -> dict:
    ssl_context = ssl._create_unverified_context() if insecure else None
    with urlopen(url, context=ssl_context, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_range(symbol: str, start_date: date, end_date: date, adjusted: bool, api_key: str, insecure: bool) -> pd.DataFrame:
    url = build_url(symbol, start_date, end_date, adjusted, api_key)
    results: list[dict] = []
    while url:
        payload = open_json(url, insecure=insecure)
        status = payload.get("status")
        if status not in {"OK", "DELAYED"}:
            detail = payload.get("error") or payload.get("message") or payload
            raise RuntimeError(str(detail))
        results.extend(payload.get("results", []))
        next_url = payload.get("next_url")
        url = with_api_key(next_url, api_key) if next_url else ""
    return pd.DataFrame(results)


def convert_to_local_layout(history: pd.DataFrame, include_extended_hours: bool) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=LOCAL_COLUMNS)

    renamed = history.rename(columns={"o": "open", "c": "close", "h": "high", "l": "low", "v": "volume"}).copy()
    renamed["time_key"] = pd.to_datetime(renamed["t"], unit="ms", utc=True).dt.tz_convert(NEW_YORK)
    renamed = renamed.sort_values("time_key").reset_index(drop=True)
    renamed["volume"] = renamed["volume"].astype(int)

    if not include_extended_hours:
        local_time = renamed["time_key"].dt.time
        mask = (local_time >= REGULAR_OPEN) & (local_time < REGULAR_CLOSE_EXCLUSIVE)
        renamed = renamed.loc[mask].reset_index(drop=True)

    renamed["time_key"] = renamed["time_key"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return renamed.loc[:, LOCAL_COLUMNS]


def fetch_history(
    symbol: str,
    start_date: date,
    end_date: date,
    adjusted: bool,
    include_extended_hours: bool,
    api_key: str,
    rate_limit_seconds: float,
    insecure: bool,
) -> pd.DataFrame:
    month_ranges = iter_month_ranges(start_date, end_date)
    frames: list[pd.DataFrame] = []
    for index, (range_start, range_end) in enumerate(month_ranges):
        frames.append(fetch_range(symbol, range_start, range_end, adjusted, api_key, insecure))
        if index + 1 < len(month_ranges):
            sleep_time.sleep(rate_limit_seconds)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if combined.empty:
        return pd.DataFrame(columns=LOCAL_COLUMNS)
    combined = combined.drop_duplicates(subset=["t"]).reset_index(drop=True)
    return convert_to_local_layout(combined, include_extended_hours=include_extended_hours)


def main() -> int:
    args = parse_args()
    if not args.api_key:
        raise ValueError("missing Polygon API key; pass --api-key or set POLYGON_API_KEY")

    start_date, end_date = resolve_dates(args.start, args.end)
    code = args.code or args.symbol
    output_root = args.output_dir / code
    history = fetch_history(
        symbol=args.symbol,
        start_date=start_date,
        end_date=end_date,
        adjusted=args.adjusted,
        include_extended_hours=args.include_extended_hours,
        api_key=args.api_key,
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
    print(f"Columns: {', '.join(LOCAL_COLUMNS)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
