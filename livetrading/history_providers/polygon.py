from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from .common import HISTORY_COLUMNS, NEW_YORK, CachedRemoteDailyHistoryProvider


class PolygonCacheDailyHistoryProvider(CachedRemoteDailyHistoryProvider):
    def _fetch_remote_daily_history(self, code: str, bars: int) -> pd.DataFrame:
        if self._remote_daily_fetcher is not None:
            return self._remote_daily_fetcher(code, bars)

        api_key = os.environ.get("POLYGON_API_KEY", "").strip()
        if not api_key:
            self._logger.error("POLYGON_API_KEY is not set; cannot fetch remote daily history for %s", code)
            return pd.DataFrame(columns=HISTORY_COLUMNS)

        ticker = code.split(".", 1)[1] if "." in code else code
        end_date = self._expected_latest_trade_date() or self._now_provider().astimezone(NEW_YORK).date()
        window_days = self._estimate_polygon_daily_window_days(bars)
        max_window_days = 3650
        results: list[dict[str, object]] = []
        previous_result_count = -1
        while window_days <= max_window_days:
            start_date = end_date - timedelta(days=window_days)
            results = self._request_polygon_daily_results(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key,
                code=code,
                bars=bars,
            )
            if len(results) >= bars or window_days == max_window_days:
                break
            if len(results) <= previous_result_count:
                self._logger.info(
                    "warm-up polygon daily fetch stalled code=%s target_bars=%d returned_rows=%d window_days=%d",
                    code,
                    bars,
                    len(results),
                    window_days,
                )
                break
            previous_result_count = len(results)
            window_days = min(window_days + max(14, bars // 3), max_window_days)
        if not results:
            return pd.DataFrame(columns=HISTORY_COLUMNS)

        rows: list[dict[str, object]] = []
        for item in results:
            trade_date = datetime.fromtimestamp(item["t"] / 1000, tz=NEW_YORK).date()
            rows.append(
                {
                    "code": code,
                    "time_key": pd.Timestamp(trade_date),
                    "open": item["o"],
                    "close": item["c"],
                    "high": item["h"],
                    "low": item["l"],
                    "volume": item["v"],
                }
            )
        return pd.DataFrame(rows, columns=HISTORY_COLUMNS)

    def _estimate_polygon_daily_window_days(self, bars: int) -> int:
        trading_days_as_calendar = max((bars * 7 + 4) // 5, bars)
        return max(trading_days_as_calendar + 14, 30)

    def _request_polygon_daily_results(
        self,
        *,
        ticker: str,
        start_date: date,
        end_date: date,
        api_key: str,
        code: str,
        bars: int,
    ) -> list[dict[str, object]]:
        query = urlencode(
            {
                "adjusted": "true",
                "sort": "asc",
                "limit": 50000,
                "apiKey": api_key,
            }
        )
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start_date.isoformat()}/{end_date.isoformat()}?{query}"
        max_attempts = 3
        payload: dict[str, object] | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                with urlopen(url, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                try:
                    if exc.code != 429 or attempt >= max_attempts:
                        raise
                    retry_after = self._polygon_retry_delay_seconds(exc, attempt)
                    self._logger.warning(
                        "warm-up polygon daily fetch rate limited code=%s target_bars=%d start=%s end=%s attempt=%d/%d retry_after=%.2fs",
                        code,
                        bars,
                        start_date,
                        end_date,
                        attempt,
                        max_attempts,
                        retry_after,
                    )
                    time.sleep(retry_after)
                finally:
                    exc.close()
        if payload is None:
            return []
        status = payload.get("status")
        if status not in {"OK", "DELAYED"}:
            detail = payload.get("error") or payload.get("message") or payload
            raise RuntimeError(f"polygon daily fetch failed for {code}: {detail}")
        results = payload.get("results", [])
        self._logger.info(
            "warm-up polygon daily fetch code=%s target_bars=%d start=%s end=%s returned_rows=%d",
            code,
            bars,
            start_date,
            end_date,
            len(results),
        )
        return results

    def _polygon_retry_delay_seconds(self, exc: HTTPError, attempt: int) -> float:
        retry_after_raw = exc.headers.get("Retry-After") if exc.headers is not None else None
        if retry_after_raw:
            try:
                retry_after = float(retry_after_raw)
            except (TypeError, ValueError):
                retry_after = 0.0
            else:
                return max(0.5, min(retry_after, 5.0))
        return float(min(2 ** (attempt - 1), 5))
