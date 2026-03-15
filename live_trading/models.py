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
    signal_time: pd.Timestamp
    target_weights: dict[str, float]
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)
