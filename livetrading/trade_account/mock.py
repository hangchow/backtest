from __future__ import annotations

import logging

import pandas as pd

from ..config import DEFAULT_CURRENCY, TradeAccountConfig
from ..models import AccountSnapshot, OrderIntent, OrderSubmission, PositionSnapshot
from .base import TradeAccountClient, TradeAccountEventSink


class MockTradeAccountClient(TradeAccountClient):
    """不依赖 Futu 的 mock 账户客户端：启动即把配置里的资金和持仓推给 engine。"""

    def __init__(self, config: TradeAccountConfig, event_sink: TradeAccountEventSink, logger: logging.Logger) -> None:
        self._config = config
        self._event_sink = event_sink
        self._logger = logger
        self._connected = False

    def connect(self) -> None:
        """直接用本地配置构造账户快照和持仓快照，不访问任何外部服务。"""
        self._connected = True
        snapshot = AccountSnapshot(
            timestamp=pd.Timestamp.now(tz="UTC"),
            total_assets=self._config.broker.initial_cash,
            cash=self._config.broker.initial_cash,
            available_funds=self._config.broker.initial_cash,
            buying_power=self._config.broker.initial_cash,
            currency=DEFAULT_CURRENCY,
            raw={"source": "mock"},
        )
        positions = {
            code: PositionSnapshot(
                code=code,
                qty=qty,
                can_sell_qty=qty,
                average_cost=None,
                market_val=None,
                unrealized_pl=None,
                realized_pl=None,
                currency=DEFAULT_CURRENCY,
                raw={"source": "mock"},
            )
            for code, qty in self._config.broker.initial_positions
        }
        self._event_sink.on_account(self._config.account_id, snapshot)
        self._event_sink.on_positions(self._config.account_id, positions)
        self._event_sink.on_broker_message(
            logging.INFO,
            f"account={self._config.account_id} mock account connected cash={self._config.broker.initial_cash} positions={dict(self._config.broker.initial_positions)}",
        )

    def submit_order(self, intent: OrderIntent) -> OrderSubmission:
        """mock 账户不支持 broker_submit；真正的 mock 执行器也不会调用这里。"""
        return OrderSubmission(
            account_id=self._config.account_id,
            broker_order_id=None,
            accepted=False,
            message="mock trade account does not support broker order submission",
            submitted_qty=intent.qty,
            submitted_price=intent.limit_price,
        )

    def close(self) -> None:
        self._connected = False
