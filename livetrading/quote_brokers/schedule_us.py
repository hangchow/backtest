from __future__ import annotations

from datetime import datetime
import logging
import threading
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from ..config import RealtimeQuoteBrokerConfig
from ..models import ScheduledTrigger
from .base import QuoteBrokerClient, QuoteBrokerEventSink


class ScheduleUSQuoteClient(QuoteBrokerClient):
    """按美股交易日历在指定时刻触发一次 schedule 事件。"""

    def __init__(
        self,
        config: RealtimeQuoteBrokerConfig,
        event_sink: QuoteBrokerEventSink,
        logger: logging.Logger,
        *,
        now_provider: Callable[[], datetime] | None = None,
        sleep_interval_seconds: float = 1.0,
    ) -> None:
        self._config = config
        self._event_sink = event_sink
        self._logger = logger
        self._timezone = ZoneInfo(config.timezone or "America/New_York")
        self._trigger_time = datetime.strptime(config.trigger_time or "09:30", "%H:%M").time()
        self._calendar = xcals.get_calendar(config.market_calendar or "XNYS")
        self._now_provider = now_provider or (lambda: datetime.now(tz=self._timezone))
        self._sleep_interval_seconds = max(float(sleep_interval_seconds), 0.1)
        self._codes: tuple[str, ...] = ()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected_at: datetime | None = None
        self._last_triggered_session: datetime.date | None = None

    def connect(self, codes: Iterable[str], *, subscribe_bars: bool = True) -> None:
        self._codes = tuple(codes)
        self._stop_event = threading.Event()
        self._connected_at = self._localized_now()
        self._thread = threading.Thread(target=self._run, name="schedule-us-broker", daemon=True)
        self._thread.start()
        self._event_sink.on_broker_message(
            logging.INFO,
            (
                "SCHEDULE_BROKER_CONNECTED type=schedule_us calendar=%s timezone=%s "
                "trigger_time=%s codes=%s subscribe_bars=%s"
            )
            % (
                self._config.market_calendar or "XNYS",
                self._config.timezone or "America/New_York",
                self._config.trigger_time or "09:30",
                ",".join(self._codes),
                str(subscribe_bars).lower(),
            ),
        )

    def update_symbols(self, codes: Iterable[str], *, subscribe_bars: bool = True) -> None:
        self._codes = tuple(codes)
        self._event_sink.on_broker_message(
            logging.INFO,
            "SCHEDULE_BROKER_UPDATED type=schedule_us codes=%s subscribe_bars=%s"
            % (",".join(self._codes), str(subscribe_bars).lower()),
        )

    def close(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            now = self._localized_now()
            due = self._current_due_trigger(now)
            if due is not None:
                trigger_timestamp, session_date, catch_up = due
                self._last_triggered_session = session_date
                self._event_sink.on_broker_message(
                    logging.INFO,
                    (
                        "SCHEDULE_TRIGGER type=schedule_us signal_time=%s session_date=%s "
                        "catch_up=%s codes=%s"
                    )
                    % (
                        pd.Timestamp(trigger_timestamp),
                        session_date,
                        str(catch_up).lower(),
                        ",".join(self._codes),
                    ),
                )
                self._event_sink.on_schedule(
                    ScheduledTrigger(
                        timestamp=pd.Timestamp(trigger_timestamp),
                        source="schedule_us",
                        raw={
                            "session_date": str(session_date),
                            "catch_up": catch_up,
                            "codes": list(self._codes),
                        },
                    )
                )
                continue
            next_trigger = self._next_trigger_after(now)
            wait_seconds = max((next_trigger - now).total_seconds(), 0.0)
            wait_seconds = min(wait_seconds, self._sleep_interval_seconds) if wait_seconds > 0 else self._sleep_interval_seconds
            self._stop_event.wait(wait_seconds)

    def _localized_now(self) -> datetime:
        now = self._now_provider()
        if now.tzinfo is None:
            return now.replace(tzinfo=self._timezone)
        return now.astimezone(self._timezone)

    def _current_due_trigger(self, now: datetime) -> tuple[datetime, datetime.date, bool] | None:
        session_date = now.date()
        session_label = pd.Timestamp(session_date)
        if not self._calendar.is_session(session_label):
            return None
        trigger_timestamp = datetime.combine(session_date, self._trigger_time, tzinfo=self._timezone)
        if now < trigger_timestamp or self._last_triggered_session == session_date:
            return None
        connected_after_trigger = self._connected_at is not None and self._connected_at.date() == session_date and self._connected_at > trigger_timestamp
        if connected_after_trigger and not self._config.catch_up_missed_session:
            return None
        return trigger_timestamp, session_date, connected_after_trigger

    def _next_trigger_after(self, now: datetime) -> datetime:
        session_date = now.date()
        session_label = pd.Timestamp(session_date)
        if self._calendar.is_session(session_label):
            today_trigger = datetime.combine(session_date, self._trigger_time, tzinfo=self._timezone)
            if now < today_trigger:
                return today_trigger
            next_session_label = self._calendar.next_session(session_label)
            return datetime.combine(pd.Timestamp(next_session_label).date(), self._trigger_time, tzinfo=self._timezone)
        next_session_label = self._calendar.date_to_session(session_label, direction="next")
        return datetime.combine(pd.Timestamp(next_session_label).date(), self._trigger_time, tzinfo=self._timezone)
