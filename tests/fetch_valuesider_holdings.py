#!/usr/bin/env python3
"""抓取 ValueSider 投资人持仓并汇总。"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://valuesider.com"
INVESTORS_PATH = "/value-investors"
DEFAULT_TIMEOUT = 30


def parse_money(value_text: str) -> float:
    text = value_text.strip().replace("$", "").replace(",", "")
    if not text or text == "-":
        return 0.0
    return float(text)


def clean_text(text: str) -> str:
    return " ".join(text.split())


def fetch_html(url: str, timeout: int) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def get_investor_portfolio_urls(html: str, limit: int | None = None) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()

    for a_tag in soup.select('a[href*="/guru/"]'):
        href = a_tag.get("href")
        if not href:
            continue
        if "/portfolio" not in href:
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        urls.append(full_url)
        if limit and len(urls) >= limit:
            break

    return urls


def parse_portfolio_table(html: str, portfolio_url: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")
    table = None

    for candidate in soup.find_all("table"):
        header_cells = [clean_text(th.get_text()) for th in candidate.find_all("th")]
        lowered = {h.lower() for h in header_cells}
        if "ticker" in lowered and "value" in lowered:
            table = candidate
            break

    if table is None:
        raise ValueError(f"未找到持仓表格: {portfolio_url}")

    rows: list[dict[str, str | float]] = []
    headers = [clean_text(th.get_text()) for th in table.find_all("th")]

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        cells = [clean_text(td.get_text(" ", strip=True)) for td in tds]
        row = {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}
        if "Ticker" not in row or "Value" not in row:
            continue

        row["Value_num"] = parse_money(str(row["Value"]))
        rows.append(row)

    if not rows:
        raise ValueError(f"持仓表为空: {portfolio_url}")

    df = pd.DataFrame(rows)
    return df


def investor_slug_from_url(portfolio_url: str) -> str:
    parts = [p for p in portfolio_url.split("/") if p]
    if "guru" in parts:
        idx = parts.index("guru")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return parts[-1].replace("portfolio", "unknown")


def write_csv(path: Path, rows: Iterable[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(output_dir: Path, limit: int | None, sleep_seconds: float, timeout: int) -> None:
    investors_url = urljoin(BASE_URL, INVESTORS_PATH)
    investors_html = fetch_html(investors_url, timeout=timeout)
    portfolio_urls = get_investor_portfolio_urls(investors_html, limit=limit)

    if not portfolio_urls:
        raise RuntimeError("没有在投资人列表页中找到 portfolio 链接")

    raw_dir = output_dir / "investors"
    raw_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    errors: list[dict[str, str]] = []

    for i, portfolio_url in enumerate(portfolio_urls, start=1):
        slug = investor_slug_from_url(portfolio_url)
        print(f"[{i}/{len(portfolio_urls)}] 抓取 {slug}: {portfolio_url}")

        try:
            html = fetch_html(portfolio_url, timeout=timeout)
            df = parse_portfolio_table(html, portfolio_url)
            df.insert(0, "investor_slug", slug)
            df.insert(1, "portfolio_url", portfolio_url)

            out_file = raw_dir / f"{slug}.csv"
            df.to_csv(out_file, index=False)

            for _, row in df.iterrows():
                all_rows.append(
                    {
                        "investor_slug": row.get("investor_slug", ""),
                        "ticker": row.get("Ticker", ""),
                        "stock": row.get("Stock", ""),
                        "value": float(row.get("Value_num", 0.0)),
                        "value_text": row.get("Value", ""),
                        "portfolio_url": row.get("portfolio_url", ""),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            errors.append({"portfolio_url": portfolio_url, "error": str(exc)})
            print(f"  -> 失败: {exc}")

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    if not all_rows:
        raise RuntimeError("没有成功抓取到任何持仓数据")

    all_df = pd.DataFrame(all_rows)
    all_df.to_csv(output_dir / "all_holdings.csv", index=False)

    summary_df = (
        all_df.groupby(["ticker", "stock"], dropna=False, as_index=False)["value"]
        .sum()
        .sort_values("value", ascending=False)
    )
    summary_df["value"] = summary_df["value"].round(2)
    summary_df.to_csv(output_dir / "summary_by_ticker.csv", index=False)

    if errors:
        write_csv(output_dir / "errors.csv", errors, ["portfolio_url", "error"])

    print("\n完成。")
    print(f"投资人页面总数: {len(portfolio_urls)}")
    print(f"成功抓取页面数: {len(portfolio_urls) - len(errors)}")
    print(f"失败页面数: {len(errors)}")
    print(f"明细输出: {output_dir / 'all_holdings.csv'}")
    print(f"汇总输出: {output_dir / 'summary_by_ticker.csv'}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="抓取 ValueSider 投资人持仓，并按 ticker 汇总 Value 总和"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/valuesider"),
        help="输出目录（默认: output/valuesider）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="限制抓取的投资人数量（默认: 全部）",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.5,
        help="每个请求之间的休眠秒数（默认: 0.5）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP 超时秒数（默认: {DEFAULT_TIMEOUT}）",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    run(
        output_dir=args.output_dir,
        limit=args.limit,
        sleep_seconds=args.sleep_seconds,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    main()
