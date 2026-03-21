from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from ..models import AccountSnapshot, PositionSnapshot


class TradeAccountEventSink(Protocol):
    def on_account(self, account_id: str, snapshot: AccountSnapshot) -> None:
        raise NotImplementedError

    def on_positions(self, account_id: str, positions: dict[str, PositionSnapshot]) -> None:
        raise NotImplementedError

    def on_broker_message(self, level: int, message: str) -> None:
        raise NotImplementedError


class TradeAccountClient(ABC):
    @abstractmethod
    def connect(self) -> None:
        """建立账户连接，并开始同步账户资金和持仓状态。"""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
