from __future__ import annotations

from ..broker_registry import register_trade_account_client
from .base import TradeAccountClient, TradeAccountEventSink
from .futu import FutuTradeAccountClient
from .mock import MockTradeAccountClient

_BUILTINS_REGISTERED = False


def ensure_builtin_trade_account_client_registrations() -> None:
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return
    register_trade_account_client("futu", FutuTradeAccountClient)
    register_trade_account_client("mock", MockTradeAccountClient)
    _BUILTINS_REGISTERED = True


__all__ = [
    "FutuTradeAccountClient",
    "MockTradeAccountClient",
    "TradeAccountClient",
    "TradeAccountEventSink",
    "ensure_builtin_trade_account_client_registrations",
]
