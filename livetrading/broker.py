from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import HistoryBrokerConfig, RealtimeQuoteBrokerConfig, TradeAccountConfig
    from .history_providers.base import DailyHistoryProvider
    from .quote_brokers.base import QuoteBrokerClient, QuoteBrokerEventSink
    from .trade_accounts.base import TradeAccountClient, TradeAccountEventSink


def create_quote_broker_client(
    config: RealtimeQuoteBrokerConfig,
    event_sink: QuoteBrokerEventSink,
    logger: logging.Logger,
) -> QuoteBrokerClient:
    """按配置选择 realtime quote client 实现。"""
    if config.type == "futu":
        from .quote_brokers.futu import FutuRealtimeQuoteClient

        return FutuRealtimeQuoteClient(config, event_sink, logger)
    if config.type == "mock":
        from .quote_brokers.mock import MockRealtimeQuoteClient

        return MockRealtimeQuoteClient(config, event_sink, logger)
    raise ValueError(f"unsupported broker type: {config.type}")


def create_daily_history_provider(
    config: HistoryBrokerConfig,
    logger: logging.Logger,
) -> DailyHistoryProvider:
    """按配置选择 warm-up 日线 provider 实现。"""
    if config.type == "polygon":
        from .history_providers.polygon import PolygonCacheDailyHistoryProvider

        return PolygonCacheDailyHistoryProvider(config, logger)
    if config.type == "local":
        from .history_providers.local import LocalDataDailyHistoryProvider

        return LocalDataDailyHistoryProvider(
            config,
            logger,
            kline_day_root=config.data_root or ".kline_day",
        )
    if config.type == "futu":
        from .history_providers.futu import FutuDailyHistoryProvider

        return FutuDailyHistoryProvider(config, logger)
    raise ValueError(f"unsupported broker type: {config.type}")


def create_trade_account_client(
    config: TradeAccountConfig,
    event_sink: TradeAccountEventSink,
    logger: logging.Logger,
) -> TradeAccountClient:
    """按配置选择交易账户 client 实现。"""
    if config.broker.type == "futu":
        from .trade_accounts.futu import FutuTradeAccountClient

        return FutuTradeAccountClient(config, event_sink, logger)
    if config.broker.type == "mock":
        from .trade_accounts.mock import MockTradeAccountClient

        return MockTradeAccountClient(config, event_sink, logger)
    raise ValueError(f"unsupported broker type: {config.broker.type}")
