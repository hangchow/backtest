from __future__ import annotations

from typing import TYPE_CHECKING

from .config import (
    ExecutionConfig,
    HistoryBrokerConfig,
    LiveTradingConfig,
    QuoteConfig,
    RealtimeQuoteBrokerConfig,
    RuntimeConfig,
    StockPoolConfig,
    StrategyConfig,
    TradeAccountConfig,
    TradeBrokerConfig,
    build_livetrading_config,
    load_livetrading_config,
    load_quote_config,
    load_trade_account_config,
)

if TYPE_CHECKING:
    from .engine import LiveTradingEngine


def __getattr__(name: str):
    if name == "LiveTradingEngine":
        from .engine import LiveTradingEngine as _LiveTradingEngine

        return _LiveTradingEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "HistoryBrokerConfig",
    "LiveTradingConfig",
    "LiveTradingEngine",
    "QuoteConfig",
    "RealtimeQuoteBrokerConfig",
    "RuntimeConfig",
    "StockPoolConfig",
    "StrategyConfig",
    "TradeAccountConfig",
    "TradeBrokerConfig",
    "build_livetrading_config",
    "ExecutionConfig",
    "load_livetrading_config",
    "load_quote_config",
    "load_trade_account_config",
]
