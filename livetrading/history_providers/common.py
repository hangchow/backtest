from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta
from functools import lru_cache
from typing import Callable
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd


HISTORY_COLUMNS = ["code", "time_key", "open", "close", "high", "low", "volume"]
CSV_COLUMNS = ["time_key", "open", "close", "high", "low", "volume"]
NEW_YORK = ZoneInfo("America/New_York")
HONG_KONG = ZoneInfo("Asia/Hong_Kong")
US_MARKET_CLOSE = datetime_time(16, 0)
HK_MARKET_CLOSE = datetime_time(16, 0)
MARKET_SESSIONS: dict[str, tuple[ZoneInfo, datetime_time]] = {
    "US": (NEW_YORK, US_MARKET_CLOSE),
    "HK": (HONG_KONG, HK_MARKET_CLOSE),
}
MARKET_CALENDAR_NAMES: dict[str, str] = {
    "US": "XNYS",
    "HK": "XHKG",
}
MARKET_DAILY_BAR_READY_DELAYS: dict[str, timedelta] = {
    "US": timedelta(hours=2),
    "HK": timedelta(hours=2),
}


def _market_session(market: str | None) -> tuple[ZoneInfo, datetime_time] | None:
    normalized_market = (market or "US").strip().upper()
    return MARKET_SESSIONS.get(normalized_market)


def _default_now_provider_for_market(market: str | None) -> Callable[[], datetime]:
    session = _market_session(market)
    timezone = session[0] if session is not None else NEW_YORK
    return lambda: datetime.now(tz=timezone)


@lru_cache(maxsize=None)
def _market_calendar(market: str | None):
    normalized_market = (market or "US").strip().upper()
    calendar_name = MARKET_CALENDAR_NAMES.get(normalized_market)
    if calendar_name is None:
        return None
    return xcals.get_calendar(calendar_name)


def _expected_latest_trade_date_for_market(market: str | None, now: datetime) -> date | None:
    session = _market_session(market)
    if session is None:
        return None
    timezone, market_close = session
    calendar = _market_calendar(market)
    if calendar is None:
        return None
    current = now
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone)
    current = current.astimezone(timezone)
    current_session_label = pd.Timestamp(current.date())
    ready_delay = MARKET_DAILY_BAR_READY_DELAYS.get((market or "US").strip().upper(), timedelta())
    if calendar.is_session(current_session_label):
        current_session_close = calendar.session_close(current_session_label).tz_convert(timezone)
        if current >= current_session_close + ready_delay:
            return current.date()
        return pd.Timestamp(calendar.previous_session(current_session_label)).date()
    return pd.Timestamp(calendar.date_to_session(current_session_label, direction="previous")).date()
