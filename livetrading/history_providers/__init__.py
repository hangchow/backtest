from __future__ import annotations

import logging

from ..broker_registry import register_daily_history_provider
from ..config import HistoryBrokerConfig
from .base import DailyHistoryProvider
from .cached import CachedRemoteDailyHistoryProvider
from .common import _expected_latest_trade_date_for_market
from .futu import FutuDailyHistoryProvider
from .local import LocalDataDailyHistoryProvider
from .polygon import PolygonCacheDailyHistoryProvider

_BUILTINS_REGISTERED = False


def _create_local_data_daily_history_provider(
    config: HistoryBrokerConfig,
    logger: logging.Logger,
) -> LocalDataDailyHistoryProvider:
    return LocalDataDailyHistoryProvider(
        config,
        logger,
        kline_day_root=config.data_root or ".kline_day",
    )


def ensure_builtin_daily_history_provider_registrations() -> None:
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return
    register_daily_history_provider("futu", FutuDailyHistoryProvider)
    register_daily_history_provider("polygon", PolygonCacheDailyHistoryProvider)
    register_daily_history_provider("local", _create_local_data_daily_history_provider)
    _BUILTINS_REGISTERED = True

__all__ = [
    "CachedRemoteDailyHistoryProvider",
    "DailyHistoryProvider",
    "FutuDailyHistoryProvider",
    "LocalDataDailyHistoryProvider",
    "PolygonCacheDailyHistoryProvider",
    "_expected_latest_trade_date_for_market",
    "ensure_builtin_daily_history_provider_registrations",
]
