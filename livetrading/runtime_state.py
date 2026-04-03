from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import LiveTradingConfig
from .history_providers.base import DailyHistoryProvider
from .models import QuoteUpdate
from .pool_strategies import PoolLiveStrategy
from .quote_brokers.base import QuoteBrokerClient
from .trade_account.base import TradeAccountClient


@dataclass
class LiveTradingRuntimeState:
    current_config: LiveTradingConfig | None = None
    config_inflight: LiveTradingConfig | None = None
    quote_broker: QuoteBrokerClient | None = None
    history_provider: DailyHistoryProvider | None = None
    trade_account_clients: dict[str, TradeAccountClient] = field(default_factory=dict)
    pool_strategy: PoolLiveStrategy | None = None
    latest_quotes: dict[str, QuoteUpdate] = field(default_factory=dict)
    latest_bar_prices: dict[str, float] = field(default_factory=dict)
    history_warmup_pending: bool = False
    warmup_unavailable_codes: tuple[str, ...] = ()
    pending_account_log_ids: set[str] = field(default_factory=set)
    pending_position_log_ids: set[str] = field(default_factory=set)

    def callback_config(self) -> LiveTradingConfig | None:
        """返回当前回调应该读取的配置快照。"""
        return self.config_inflight or self.current_config

    def resolve_reference_price(self, code: str) -> float | None:
        if code in self.latest_quotes:
            return self.latest_quotes[code].last_price
        if code in self.latest_bar_prices:
            return self.latest_bar_prices[code]
        return None

    def active_prices_for_codes(self, codes: tuple[str, ...]) -> dict[str, float]:
        prices: dict[str, float] = {}
        for code in codes:
            # 执行层只认运行时收到过的最新价格，不会回头去 warm-up 日线里取收盘价。
            # 这就是 mock_signal 文档里为什么要先补一次 AAPL/MSFT 参考价。
            price = self.resolve_reference_price(code)
            if price is not None and price > 0:
                prices[code] = price
        return prices
