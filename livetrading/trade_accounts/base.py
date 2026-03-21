from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from ..models import AccountSnapshot, FillEvent, OrderIntent, OrderSubmission, OrderUpdate, PositionSnapshot


class TradeAccountEventSink(Protocol):
    """trade account client 通过这个回调接口把资金、持仓、订单和成交推回 engine。"""

    def on_account(self, account_id: str, snapshot: AccountSnapshot) -> None:
        raise NotImplementedError

    def on_positions(self, account_id: str, positions: dict[str, PositionSnapshot]) -> None:
        raise NotImplementedError

    def on_order_update(self, account_id: str, update: OrderUpdate) -> None:
        raise NotImplementedError

    def on_fill(self, account_id: str, fill: FillEvent) -> None:
        raise NotImplementedError

    def on_broker_message(self, level: int, message: str) -> None:
        raise NotImplementedError


class TradeAccountClient(ABC):
    @abstractmethod
    def connect(self) -> None:
        """建立账户连接，并开始同步账户资金和持仓状态。"""
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, intent: OrderIntent) -> OrderSubmission:
        """提交一笔订单，并返回 broker 层的受理结果。"""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
