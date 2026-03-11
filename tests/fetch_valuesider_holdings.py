#!/usr/bin/env python3
"""抓取 ValueSider 投资人持仓并汇总。"""

from __future__ import annotations

import argparse
import csv
import signal
import shutil
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://valuesider.com"
INVESTORS_PATH = "/value-investors"
DEFAULT_TIMEOUT = 30
DEFAULT_PUBLISH_DIR = Path("stock_select/valuesider")
MAX_HTTP_RETRIES = 3
HARD_TIMEOUT_BUFFER = 5
PUBLISH_REQUIRED_FILENAMES = (
    "all_holdings.csv",
    "summary_by_ticker.csv",
    "holder_count_by_ticker.csv",
)
PUBLISH_PRUNE_FILENAMES = (
    "data_quality_issues.csv",
    "errors.csv",
)
KNOWN_SECURITY_OVERRIDES: dict[tuple[str, str], tuple[str, str]] = {
    ("1534615D", "LOTUS BAKERIES"): ("LOTB", "LOTUS BAKERIES"),
    ("2299955D", "CONSTELLATION SOFTWARE IN-40"): ("CSU", "CONSTELLATION SOFTWARE INC"),
}
TICKER_ALIASES: dict[str, str] = {
    "GOOGL": "GOOG",
}


def parse_money(value_text: str) -> float:
    text = value_text.strip().replace("$", "").replace(",", "")
    if not text or text == "-":
        return 0.0
    return float(text)


def clean_text(text: str) -> str:
    return " ".join(text.split())


def normalize_ticker(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = clean_text(str(value))
    if not text or text.lower() == "nan":
        return ""
    return text


def normalize_stock(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = clean_text(str(value))
    if text.lower() == "nan":
        return ""
    return text


def normalize_security(ticker: object, stock: object) -> tuple[str, str]:
    normalized_ticker = normalize_ticker(ticker)
    normalized_stock = normalize_stock(stock)
    normalized_ticker = TICKER_ALIASES.get(normalized_ticker, normalized_ticker)
    return KNOWN_SECURITY_OVERRIDES.get(
        (normalized_ticker, normalized_stock),
        (normalized_ticker, normalized_stock),
    )


def is_code_like_ticker(ticker: str) -> bool:
    return bool(ticker) and ticker.isalnum() and any(char.isdigit() for char in ticker) and len(ticker) >= 8


def canonicalize_stock_name_for_ticker(
    ticker: str,
    stock: str,
    available_stocks: set[str],
) -> str:
    if not ticker or not stock:
        return stock

    suffix = f" {ticker}"
    if stock.endswith(suffix):
        base_name = stock[: -len(suffix)].strip()
        if base_name and base_name in available_stocks:
            return base_name

    return stock


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
    )
    return session


def _raise_hard_timeout(_signum: int, _frame: object) -> None:
    raise TimeoutError("请求超过硬超时限制")


def fetch_html(
    url: str,
    timeout: int,
    session: requests.Session | None = None,
) -> str:
    requester = session or requests
    last_error: Exception | None = None

    for attempt in range(1, MAX_HTTP_RETRIES + 1):
        timer_enabled = hasattr(signal, "SIGALRM") and timeout > 0
        previous_handler = None

        try:
            if timer_enabled:
                previous_handler = signal.getsignal(signal.SIGALRM)
                signal.signal(signal.SIGALRM, _raise_hard_timeout)
                signal.alarm(timeout + HARD_TIMEOUT_BUFFER)

            with requester.get(
                url,
                timeout=(10, timeout),
                headers={"Connection": "close"},
            ) as response:
                response.raise_for_status()
                return response.text
        except (requests.RequestException, TimeoutError) as exc:
            last_error = exc
            if attempt == MAX_HTTP_RETRIES:
                raise
            time.sleep(min(2 ** (attempt - 1), 5))
        finally:
            if timer_enabled:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous_handler)

    if last_error is not None:
        raise last_error

    raise RuntimeError(f"抓取失败且没有返回错误信息: {url}")


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


def parse_table_layout(soup: BeautifulSoup, portfolio_url: str) -> pd.DataFrame:
    table = None
    for candidate in soup.find_all("table"):
        header_cells = [clean_text(th.get_text()) for th in candidate.find_all("th")]
        lowered = {h.lower() for h in header_cells}
        if "ticker" in lowered and "value" in lowered:
            table = candidate
            break

    if table is None:
        raise ValueError(f"未找到 table 持仓表格: {portfolio_url}")

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
        raise ValueError(f"table 持仓表为空: {portfolio_url}")

    return pd.DataFrame(rows)


def parse_div_layout(soup: BeautifulSoup, portfolio_url: str) -> pd.DataFrame:
    header_row = soup.select_one(".guru_table_header .guru_table_row")
    table_body = soup.select_one(".guru_table_body")

    if header_row is None or table_body is None:
        raise ValueError(f"未找到 div 持仓表格: {portfolio_url}")

    header_cells = header_row.find_all("div", class_="guru_table_column", recursive=False)
    headers = [clean_text(cell.get_text(" ", strip=True)) for cell in header_cells]
    lowered = {header.lower() for header in headers}
    if "ticker" not in lowered or "value" not in lowered:
        raise ValueError(f"div 持仓表头缺少 ticker/value: {portfolio_url}")

    rows: list[dict[str, str | float]] = []
    for row_div in table_body.find_all("div", class_="guru_table_row", recursive=False):
        cells = [
            clean_text(cell.get_text(" ", strip=True))
            for cell in row_div.find_all("div", class_="guru_table_column", recursive=False)
        ]
        row = {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}
        if "Ticker" not in row or "Value" not in row:
            continue

        row["Value_num"] = parse_money(str(row["Value"]))
        rows.append(row)

    if not rows:
        raise ValueError(f"div 持仓表为空: {portfolio_url}")

    return pd.DataFrame(rows)


def parse_portfolio_table(html: str, portfolio_url: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")

    for parser in (parse_table_layout, parse_div_layout):
        try:
            return parser(soup, portfolio_url)
        except ValueError:
            continue

    raise ValueError(f"未找到可解析的持仓表格: {portfolio_url}")


def get_paginated_portfolio_urls(html: str, portfolio_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()
    current_page = parse_qs(urlparse(portfolio_url).query).get("page", ["1"])[0]

    for a_tag in soup.select("ul.pagination a[href]"):
        href = a_tag.get("href")
        if not href:
            continue
        full_url = urljoin(portfolio_url, href)
        candidate_page = parse_qs(urlparse(full_url).query).get("page", ["1"])[0]
        if "/portfolio" not in full_url or full_url == portfolio_url:
            continue
        if candidate_page == current_page:
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        urls.append(full_url)

    return urls


def fetch_portfolio_dataframe(
    portfolio_url: str,
    timeout: int,
    sleep_seconds: float,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    pending_urls = [portfolio_url]
    seen_urls: set[str] = set()
    frames: list[pd.DataFrame] = []

    while pending_urls:
        current_url = pending_urls.pop(0)
        if current_url in seen_urls:
            continue
        seen_urls.add(current_url)

        html = fetch_html(current_url, timeout=timeout, session=session)
        frames.append(parse_portfolio_table(html, current_url))

        for next_url in get_paginated_portfolio_urls(html, current_url):
            if next_url not in seen_urls and next_url not in pending_urls:
                pending_urls.append(next_url)

        if sleep_seconds > 0 and pending_urls:
            time.sleep(sleep_seconds)

    if not frames:
        raise ValueError(f"未抓取到任何持仓页: {portfolio_url}")

    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["Ticker", "Stock", "Value"], keep="first")
        .reset_index(drop=True)
    )


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


def publish_output_files(output_dir: Path, publish_dir: Path | None) -> None:
    if publish_dir is None:
        return

    publish_dir.mkdir(parents=True, exist_ok=True)

    for filename in PUBLISH_REQUIRED_FILENAMES:
        shutil.copy2(output_dir / filename, publish_dir / filename)

    for filename in PUBLISH_PRUNE_FILENAMES:
        target_path = publish_dir / filename
        if target_path.exists():
            target_path.unlink()


def apply_security_normalization(all_df: pd.DataFrame) -> pd.DataFrame:
    normalized_df = all_df.copy()
    normalized_pairs = normalized_df.apply(
        lambda row: normalize_security(row.get("ticker", ""), row.get("stock", "")),
        axis=1,
        result_type="expand",
    )
    normalized_df["ticker"] = normalized_pairs[0]
    normalized_df["stock"] = normalized_pairs[1]
    return normalized_df


def build_data_quality_issues(all_df: pd.DataFrame) -> pd.DataFrame:
    issues: list[dict[str, object]] = []
    normalized_df = apply_security_normalization(all_df)

    for _, row in normalized_df.iterrows():
        ticker = normalize_ticker(row.get("ticker", ""))
        stock = normalize_stock(row.get("stock", ""))
        value = float(row.get("value", 0.0))
        issue_types: list[str] = []

        if not ticker:
            issue_types.append("blank_ticker")
        if value <= 0:
            issue_types.append("nonpositive_value")
        if is_code_like_ticker(ticker):
            issue_types.append("code_like_ticker")

        if issue_types:
            issues.append(
                {
                    "issue_types": ";".join(issue_types),
                    "investor_slug": row.get("investor_slug", ""),
                    "ticker": ticker,
                    "stock": stock,
                    "value": value,
                    "value_text": row.get("value_text", ""),
                    "portfolio_url": row.get("portfolio_url", ""),
                }
            )

    return pd.DataFrame(issues)


def build_aggregatable_holdings(all_df: pd.DataFrame) -> pd.DataFrame:
    summary_source = apply_security_normalization(all_df)
    summary_source = summary_source[summary_source["ticker"] != ""].copy()
    summary_source = summary_source[summary_source["value"] > 0].copy()
    return summary_source


def build_representative_stock_by_ticker(summary_source: pd.DataFrame) -> pd.DataFrame:
    if summary_source.empty:
        return pd.DataFrame(columns=["ticker", "stock"])

    stock_value_df = (
        summary_source.groupby(["ticker", "stock"], dropna=False, as_index=False)["value"]
        .sum()
        .sort_values(["ticker", "value", "stock"], ascending=[True, False, True])
    )
    canonical_stock_rows: list[dict[str, object]] = []
    for ticker, group in stock_value_df.groupby("ticker", dropna=False):
        available_stocks = set(group["stock"])
        for _, row in group.iterrows():
            canonical_stock_rows.append(
                {
                    "ticker": ticker,
                    "stock": canonicalize_stock_name_for_ticker(
                        ticker=ticker,
                        stock=str(row["stock"]),
                        available_stocks=available_stocks,
                    ),
                    "value": float(row["value"]),
                }
            )

    canonical_stock_df = (
        pd.DataFrame(canonical_stock_rows)
        .groupby(["ticker", "stock"], dropna=False, as_index=False)["value"]
        .sum()
        .sort_values(["ticker", "value", "stock"], ascending=[True, False, True])
    )
    return canonical_stock_df.drop_duplicates(subset=["ticker"], keep="first").loc[:, ["ticker", "stock"]]


def build_summary_by_ticker(all_df: pd.DataFrame) -> pd.DataFrame:
    summary_source = build_aggregatable_holdings(all_df)
    if summary_source.empty:
        return pd.DataFrame(columns=["ticker", "stock", "value"])

    ticker_value_df = (
        summary_source.groupby("ticker", dropna=False, as_index=False)["value"]
        .sum()
    )
    representative_stock_df = build_representative_stock_by_ticker(summary_source)

    summary_df = ticker_value_df.merge(representative_stock_df, on="ticker", how="left")
    summary_df = summary_df.loc[:, ["ticker", "stock", "value"]]
    summary_df["value"] = summary_df["value"].round(2)
    return summary_df.sort_values("value", ascending=False).reset_index(drop=True)


def build_holder_count_by_ticker(all_df: pd.DataFrame) -> pd.DataFrame:
    summary_source = build_aggregatable_holdings(all_df)
    if summary_source.empty:
        return pd.DataFrame(columns=["ticker", "stock", "holder_count"])

    # 同一位投资人若同时持有同一标的的不同 share class（例如 GOOGL + GOOG），
    # 在经过 ticker 归一化后应只计为 1 位持有人。
    unique_holders = summary_source.drop_duplicates(subset=["ticker", "investor_slug"], keep="first")
    holder_count_df = (
        unique_holders.groupby("ticker", dropna=False, as_index=False)["investor_slug"]
        .nunique()
        .rename(columns={"investor_slug": "holder_count"})
    )
    representative_stock_df = build_representative_stock_by_ticker(summary_source)

    holder_count_df = holder_count_df.merge(representative_stock_df, on="ticker", how="left")
    holder_count_df = holder_count_df.loc[:, ["ticker", "stock", "holder_count"]]
    return holder_count_df.sort_values(
        ["holder_count", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


def run(
    output_dir: Path,
    limit: int | None,
    sleep_seconds: float,
    timeout: int,
    publish_dir: Path | None = DEFAULT_PUBLISH_DIR,
) -> None:
    investors_url = urljoin(BASE_URL, INVESTORS_PATH)
    listing_session = build_session()
    investors_html = fetch_html(investors_url, timeout=timeout, session=listing_session)
    listing_session.close()
    portfolio_urls = get_investor_portfolio_urls(investors_html, limit=limit)

    if not portfolio_urls:
        raise RuntimeError("没有在投资人列表页中找到 portfolio 链接")

    raw_dir = output_dir / "investors"
    raw_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    errors: list[dict[str, str]] = []

    for i, portfolio_url in enumerate(portfolio_urls, start=1):
        slug = investor_slug_from_url(portfolio_url)
        print(f"[{i}/{len(portfolio_urls)}] 抓取 {slug}: {portfolio_url}", flush=True)
        investor_session: requests.Session | None = None

        try:
            investor_session = build_session()
            fetch_html(investors_url, timeout=timeout, session=investor_session)
            df = fetch_portfolio_dataframe(
                portfolio_url=portfolio_url,
                timeout=timeout,
                sleep_seconds=sleep_seconds,
                session=investor_session,
            )
            investor_session.close()
            df.insert(0, "investor_slug", slug)
            df.insert(1, "portfolio_url", portfolio_url)

            out_file = raw_dir / f"{slug}.csv"
            df.to_csv(out_file, index=False)

            for _, row in df.iterrows():
                all_rows.append(
                    {
                        "investor_slug": row.get("investor_slug", ""),
                        "ticker": normalize_ticker(row.get("Ticker", "")),
                        "stock": normalize_stock(row.get("Stock", "")),
                        "value": float(row.get("Value_num", 0.0)),
                        "value_text": row.get("Value", ""),
                        "portfolio_url": row.get("portfolio_url", ""),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            errors.append({"portfolio_url": portfolio_url, "error": str(exc)})
            print(f"  -> 失败: {exc}", flush=True)
        finally:
            if investor_session is not None:
                investor_session.close()

        if sleep_seconds > 0 and i < len(portfolio_urls):
            time.sleep(sleep_seconds)

    if not all_rows:
        raise RuntimeError("没有成功抓取到任何持仓数据")

    all_df = pd.DataFrame(all_rows)
    all_df = apply_security_normalization(all_df)
    all_df = all_df.drop_duplicates(
        subset=["investor_slug", "ticker", "stock", "value", "portfolio_url"],
        keep="first",
    ).reset_index(drop=True)
    all_df.to_csv(output_dir / "all_holdings.csv", index=False)

    summary_df = build_summary_by_ticker(all_df)
    summary_df.to_csv(output_dir / "summary_by_ticker.csv", index=False)

    holder_count_df = build_holder_count_by_ticker(all_df)
    holder_count_df.to_csv(output_dir / "holder_count_by_ticker.csv", index=False)

    issues_df = build_data_quality_issues(all_df)
    if not issues_df.empty:
        issues_df.to_csv(output_dir / "data_quality_issues.csv", index=False)

    if errors:
        write_csv(output_dir / "errors.csv", errors, ["portfolio_url", "error"])

    publish_output_files(output_dir, publish_dir)

    print("\n完成。")
    print(f"投资人页面总数: {len(portfolio_urls)}")
    print(f"成功抓取页面数: {len(portfolio_urls) - len(errors)}")
    print(f"失败页面数: {len(errors)}")
    print(f"明细输出: {output_dir / 'all_holdings.csv'}")
    print(f"汇总输出: {output_dir / 'summary_by_ticker.csv'}")
    print(f"持有人数输出: {output_dir / 'holder_count_by_ticker.csv'}")
    if publish_dir is not None:
        print(f"发布输出: {publish_dir}")


def publish_from_cached_holdings(
    cached_all_holdings_path: Path,
    output_dir: Path,
    publish_dir: Path | None,
) -> None:
    if not cached_all_holdings_path.exists():
        raise FileNotFoundError(f"缓存文件不存在: {cached_all_holdings_path}")

    all_df = pd.read_csv(cached_all_holdings_path)
    all_df = apply_security_normalization(all_df)
    all_df = all_df.drop_duplicates(
        subset=["investor_slug", "ticker", "stock", "value", "portfolio_url"],
        keep="first",
    ).reset_index(drop=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    all_df.to_csv(output_dir / "all_holdings.csv", index=False)

    summary_df = build_summary_by_ticker(all_df)
    summary_df.to_csv(output_dir / "summary_by_ticker.csv", index=False)

    holder_count_df = build_holder_count_by_ticker(all_df)
    holder_count_df.to_csv(output_dir / "holder_count_by_ticker.csv", index=False)

    issues_df = build_data_quality_issues(all_df)
    if not issues_df.empty:
        issues_df.to_csv(output_dir / "data_quality_issues.csv", index=False)

    publish_output_files(output_dir, publish_dir)

    print("\n完成（缓存发布）。")
    print(f"缓存输入: {cached_all_holdings_path}")
    print(f"明细输出: {output_dir / 'all_holdings.csv'}")
    print(f"汇总输出: {output_dir / 'summary_by_ticker.csv'}")
    print(f"持有人数输出: {output_dir / 'holder_count_by_ticker.csv'}")
    if publish_dir is not None:
        print(f"发布输出: {publish_dir}")


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
    parser.add_argument(
        "--publish-dir",
        type=Path,
        default=DEFAULT_PUBLISH_DIR,
        help="同步最终统计结果到该目录（默认: stock_select/valuesider）",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="不把最终统计结果同步到 stock_select/valuesider",
    )
    parser.add_argument(
        "--publish-from-cache",
        type=Path,
        default=None,
        help="使用缓存的 all_holdings.csv 直接重算并发布（不会抓取网络）",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    publish_dir = None if args.no_publish else args.publish_dir
    if args.publish_from_cache is not None:
        publish_from_cached_holdings(
            cached_all_holdings_path=args.publish_from_cache,
            output_dir=args.output_dir,
            publish_dir=publish_dir,
        )
        return

    run(
        output_dir=args.output_dir,
        limit=args.limit,
        sleep_seconds=args.sleep_seconds,
        timeout=args.timeout,
        publish_dir=publish_dir,
    )


if __name__ == "__main__":
    main()
