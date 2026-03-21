from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class QuoteUpdate:
    code: str
    timestamp: pd.Timestamp
    last_price: float
    volume: float | None = None
    turnover: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    prev_close_price: float | None = None
    source: str = "quote"
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class AccountSnapshot:
    timestamp: pd.Timestamp
    total_assets: float | None
    cash: float | None
    available_funds: float | None
    buying_power: float | None
    currency: str
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class PositionSnapshot:
    code: str
    qty: int
    can_sell_qty: int
    average_cost: float | None
    market_val: float | None
    unrealized_pl: float | None
    realized_pl: float | None
    currency: str
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class PortfolioRebalanceDecision:
    """引擎执行层消费的组合调仓决策。"""
    signal_time: pd.Timestamp
    target_weights: dict[str, float]
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class OrderIntent:
    """规划层产出的标准化订单意图，还没有真正发给券商。"""

    account_id: str
    code: str
    side: str
    qty: int
    reference_price: float
    limit_price: float
    reason: str
    signal_time: pd.Timestamp | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class OrderSubmission:
    """券商提单返回的受理结果，用来把本地 intent 和 broker order_id 串起来。"""

    account_id: str
    broker_order_id: str | None
    accepted: bool
    message: str | None = None
    submitted_qty: int | None = None
    submitted_price: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class OrderUpdate:
    """订单状态推送的标准化结构，重点关心状态、已成交数量和均价。"""

    account_id: str
    broker_order_id: str
    code: str | None
    side: str | None
    status: str | None
    dealt_qty: int = 0
    avg_price: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class FillEvent:
    """成交推送的标准化结构，主要用于累计真实成交数量和成交额。"""

    account_id: str
    broker_order_id: str
    code: str | None
    side: str | None
    fill_qty: int
    fill_price: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)
