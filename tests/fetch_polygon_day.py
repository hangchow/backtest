#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import ssl
import sys
import time as sleep_time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pandas as pd


BASE_URL = "https://api.polygon.io/v2/aggs/ticker"
DEFAULT_OUTPUT_DIR = Path("kline_day")
DEFAULT_RATE_LIMIT_SECONDS = 13.0
DEFAULT_SYMBOLS = ["AAPL", "AMZN", "GOOG", "MSFT", "NVDA", "TSLA", "V", "VOO"]
NEW_YORK = ZoneInfo("America/New_York")
LOCAL_COLUMNS = ["time_key", "open", "close", "high", "low", "volume"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch daily historical bars from Polygon for the repository's US stock pool "
            "and write natural-week CSV files under kline_day/."
        )
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_SYMBOLS,
        help="US stock tickers to fetch. Defaults to the repository's 8-symbol US pool.",
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
        "--raw",
        action="store_true",
        help="Request raw as-traded prices instead of Polygon's split-adjusted daily bars.",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Keep existing weekly CSV files outside the requested date range instead of removing them.",
    )
    parser.add_argument(
        "--rate-limit-seconds",
        type=float,
        default=DEFAULT_RATE_LIMIT_SECONDS,
        help="Delay between symbol requests. Polygon Stocks Basic currently allows 5 API calls per minute.",
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


def build_url(symbol: str, start_date: date, end_date: date, adjusted: bool, api_key: str) -> str:
    query = urlencode({"adjusted": str(adjusted).lower(), "sort": "asc", "limit": 50000, "apiKey": api_key})
    return f"{BASE_URL}/{symbol}/range/1/day/{start_date.isoformat()}/{end_date.isoformat()}?{query}"


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


def convert_to_local_layout(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=LOCAL_COLUMNS)

    rows: list[dict[str, object]] = []
    for item in history.sort_values("t").to_dict("records"):
        trade_date = datetime.fromtimestamp(item["t"] / 1000, tz=NEW_YORK).date()
        rows.append(
            {
                "time_key": pd.Timestamp(trade_date).strftime("%Y-%m-%d %H:%M:%S"),
                "open": item["o"],
                "close": item["c"],
                "high": item["h"],
                "low": item["l"],
                "volume": int(item["v"]),
            }
        )
    local = pd.DataFrame(rows, columns=LOCAL_COLUMNS)
    local = local.drop_duplicates(subset=["time_key"], keep="last").reset_index(drop=True)
    return local


def fetch_history(
    symbol: str,
    start_date: date,
    end_date: date,
    adjusted: bool,
    api_key: str,
    insecure: bool,
) -> pd.DataFrame:
    history = fetch_range(symbol, start_date, end_date, adjusted, api_key, insecure)
    return convert_to_local_layout(history)


def remove_stale_weekly_files(output_root: Path, code: str, keep_names: set[str]) -> int:
    removed_count = 0
    for path in output_root.glob(f"{code}_*.csv"):
        if path.name in keep_names:
            continue
        path.unlink()
        removed_count += 1
    return removed_count


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


def save_weekly_files(history: pd.DataFrame, output_root: Path, code: str, keep_existing: bool) -> tuple[int, int]:
    output_root.mkdir(parents=True, exist_ok=True)
    dated = history.copy()
    dated["trade_date"] = pd.to_datetime(dated["time_key"]).dt.normalize()
    dated["week_start"] = dated["trade_date"] - pd.to_timedelta(dated["trade_date"].dt.weekday, unit="D")

    written_names: set[str] = set()
    file_count = 0
    for week_start, weekly in dated.groupby("week_start", sort=True):
        weekly_path = output_root / f"{code}_{week_start.date().isoformat()}.csv"
        merged_weekly = merge_weekly_payload(weekly_path, weekly, LOCAL_COLUMNS)
        merged_weekly.to_csv(weekly_path, index=False)
        written_names.add(weekly_path.name)
        file_count += 1

    removed_count = 0 if keep_existing else remove_stale_weekly_files(output_root, code, written_names)
    return file_count, removed_count


def normalize_symbols(symbols: list[str]) -> list[str]:
    normalized = [symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()]
    if not normalized:
        raise ValueError("symbols must include at least one non-empty ticker")
    return normalized


def main() -> int:
    args = parse_args()
    if not args.api_key:
        raise ValueError("missing Polygon API key; pass --api-key or set POLYGON_API_KEY")

    start_date, end_date = resolve_dates(args.start, args.end)
    adjusted = not args.raw
    symbols = normalize_symbols(args.symbols)

    for index, symbol in enumerate(symbols):
        code = f"US.{symbol}"
        output_root = args.output_dir / code
        history = fetch_history(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            adjusted=adjusted,
            api_key=args.api_key,
            insecure=args.insecure,
        )
        if history.empty:
            raise RuntimeError(f"No rows returned for {symbol} between {args.start} and {args.end}.")

        file_count, removed_count = save_weekly_files(
            history=history,
            output_root=output_root,
            code=code,
            keep_existing=args.keep_existing,
        )

        print(f"Fetched {len(history)} rows for {code} from {args.start} to {args.end}.")
        print(f"Actual returned range: {history.iloc[0]['time_key'][:10]} -> {history.iloc[-1]['time_key'][:10]}.")
        print(f"Wrote {file_count} weekly files to {output_root}.")
        if args.keep_existing:
            print("Kept existing weekly CSV files outside the requested date range.")
        else:
            print(f"Removed {removed_count} stale weekly CSV files outside the requested date range.")
        print(f"Columns: {', '.join(LOCAL_COLUMNS)}")

        if index + 1 < len(symbols):
            sleep_time.sleep(args.rate_limit_seconds)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
