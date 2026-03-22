from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .broker_registry import (
    register_daily_history_provider,
    register_quote_broker_client,
    register_trade_account_client,
    resolve_daily_history_provider_factory,
    resolve_quote_broker_factory,
    resolve_trade_account_client_factory,
    supported_daily_history_provider_types,
    supported_quote_broker_types,
    supported_trade_account_client_types,
    unregister_daily_history_provider,
    unregister_quote_broker_client,
    unregister_trade_account_client,
)

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
    """按注册表选择 realtime quote client 实现。"""
    return resolve_quote_broker_factory(config.type)(config, event_sink, logger)


def create_daily_history_provider(
    config: HistoryBrokerConfig,
    logger: logging.Logger,
) -> DailyHistoryProvider:
    """按注册表选择 warm-up 日线 provider 实现。"""
    return resolve_daily_history_provider_factory(config.type)(config, logger)


def create_trade_account_client(
    config: TradeAccountConfig,
    event_sink: TradeAccountEventSink,
    logger: logging.Logger,
) -> TradeAccountClient:
    """按注册表选择交易账户 client 实现。"""
    return resolve_trade_account_client_factory(config.broker.type)(config, event_sink, logger)


__all__ = [
    "create_daily_history_provider",
    "create_quote_broker_client",
    "create_trade_account_client",
    "register_daily_history_provider",
    "register_quote_broker_client",
    "register_trade_account_client",
    "supported_daily_history_provider_types",
    "supported_quote_broker_types",
    "supported_trade_account_client_types",
    "unregister_daily_history_provider",
    "unregister_quote_broker_client",
    "unregister_trade_account_client",
]
