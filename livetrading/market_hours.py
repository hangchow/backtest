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
US_EXTENDED_OPEN = datetime_time(4, 0)
US_EXTENDED_CLOSE = datetime_time(20, 0)
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
MARKET_EXTENDED_TIME_WINDOWS: dict[str, tuple[datetime_time, datetime_time] | None] = {
    # 这里对齐仓库里 minute 数据脚本的美股常规时段定义：
    # 默认 RTH 为 09:30-16:00；开启 extended 时放宽到 04:00-20:00。
    "US": (US_EXTENDED_OPEN, US_EXTENDED_CLOSE),
    # 当前仓库没有港股盘前盘后分钟线约定，这里先保持和常规时段一致。
    "HK": None,
}


def normalize_market(market: str | None) -> str:
    return (market or "US").strip().upper()


def market_timezone(market: str | None) -> ZoneInfo:
    session = _market_session(market)
    return session[0] if session is not None else NEW_YORK


def normalize_market_timestamp(value: object, market: str | None) -> pd.Timestamp:
    """把任意输入时间戳标准化成目标市场时区的 aware Timestamp。"""
    timezone = market_timezone(market)
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(timezone)
    return timestamp.tz_convert(timezone)


def market_trade_date_for_timestamp(value: object, market: str | None) -> date:
    """按市场本地时区计算这根 bar 应归属的 trade_date。"""
    localized = normalize_market_timestamp(value, market)
    calendar = _market_calendar(market)
    if calendar is None:
        return localized.date()
    session_label = pd.Timestamp(localized.date())
    if calendar.is_session(session_label):
        return session_label.date()
    # 非交易日 bar 正常不会进入 live 策略；这里保留市场本地日期，避免静默映射到别的交易日。
    return localized.date()


def _market_session(market: str | None) -> tuple[ZoneInfo, datetime_time] | None:
    return MARKET_SESSIONS.get(normalize_market(market))


def _default_now_provider_for_market(market: str | None) -> Callable[[], datetime]:
    timezone = market_timezone(market)
    return lambda: datetime.now(tz=timezone)


@lru_cache(maxsize=None)
def _market_calendar(market: str | None):
    calendar_name = MARKET_CALENDAR_NAMES.get(normalize_market(market))
    if calendar_name is None:
        return None
    return xcals.get_calendar(calendar_name)


def _expected_latest_trade_date_for_market(market: str | None, now: datetime) -> date | None:
    session = _market_session(market)
    if session is None:
        return None
    timezone, _ = session
    calendar = _market_calendar(market)
    if calendar is None:
        return None
    current = now
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone)
    current = current.astimezone(timezone)
    current_session_label = pd.Timestamp(current.date())
    ready_delay = MARKET_DAILY_BAR_READY_DELAYS.get(normalize_market(market), timedelta())
    if calendar.is_session(current_session_label):
        current_session_close = calendar.session_close(current_session_label).tz_convert(timezone)
        if current >= current_session_close + ready_delay:
            return current.date()
        return pd.Timestamp(calendar.previous_session(current_session_label)).date()
    return pd.Timestamp(calendar.date_to_session(current_session_label, direction="previous")).date()


def _regular_session_bounds_for_timestamp(timestamp: object, market: str | None) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    localized = normalize_market_timestamp(timestamp, market)
    calendar = _market_calendar(market)
    if calendar is None:
        return None
    session_label = pd.Timestamp(localized.date())
    if not calendar.is_session(session_label):
        return None
    timezone = market_timezone(market)
    return (
        calendar.session_open(session_label).tz_convert(timezone),
        calendar.session_close(session_label).tz_convert(timezone),
    )


def is_realtime_bar_allowed_for_market(
    timestamp: object,
    *,
    market: str | None,
    subscribe_extended_time: bool,
) -> bool:
    """判断某根分钟 bar 是否应该被当前 realtime 订阅配置接收。

    这层语义对齐 quote 订阅，而不是下单会话：
    - `subscribe_extended_time=False` 时，仅接受常规时段 bar
    - `subscribe_extended_time=True` 时，尽量贴近真实行情源的扩展时段准入
    """
    localized = normalize_market_timestamp(timestamp, market)
    regular_bounds = _regular_session_bounds_for_timestamp(localized, market)
    if regular_bounds is None:
        return False
    regular_open, regular_close = regular_bounds
    if regular_open <= localized <= regular_close:
        return True
    if not subscribe_extended_time:
        return False

    extended_window = MARKET_EXTENDED_TIME_WINDOWS.get(normalize_market(market))
    if extended_window is None:
        return False
    extended_open, extended_close = extended_window
    extended_start = pd.Timestamp(datetime.combine(localized.date(), extended_open, tzinfo=localized.tzinfo))
    extended_end = pd.Timestamp(datetime.combine(localized.date(), extended_close, tzinfo=localized.tzinfo))
    return extended_start <= localized <= extended_end
