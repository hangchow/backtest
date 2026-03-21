from __future__ import annotations

from typing import Iterator

import pandas as pd

from ..models import QuoteUpdate


def iter_quote_updates(frame: pd.DataFrame) -> Iterator[QuoteUpdate]:
    if frame.empty:
        return
    for row in frame.itertuples(index=False):
        timestamp = pd.Timestamp(f"{row.data_date} {row.data_time}")
        yield QuoteUpdate(
            code=str(row.code),
            timestamp=timestamp,
            last_price=float(row.last_price),
            volume=float(row.volume) if not pd.isna(row.volume) else None,
            turnover=float(row.turnover) if not pd.isna(row.turnover) else None,
            open_price=float(row.open_price) if not pd.isna(row.open_price) else None,
            high_price=float(row.high_price) if not pd.isna(row.high_price) else None,
            low_price=float(row.low_price) if not pd.isna(row.low_price) else None,
            prev_close_price=float(row.prev_close_price) if not pd.isna(row.prev_close_price) else None,
            source="quote",
        )


def iter_kline_bars(frame: pd.DataFrame) -> Iterator[tuple[str, dict[str, object]]]:
    if frame.empty:
        return
    normalized = frame.copy()
    normalized["time_key"] = pd.to_datetime(normalized["time_key"])
    for row in normalized.sort_values("time_key").itertuples(index=False):
        code = str(row.code)
        yield (
            code,
            {
                "code": code,
                "time_key": pd.Timestamp(row.time_key),
                "open": float(row.open),
                "close": float(row.close),
                "high": float(row.high),
                "low": float(row.low),
                "volume": float(row.volume) if not pd.isna(row.volume) else 0.0,
            },
        )
