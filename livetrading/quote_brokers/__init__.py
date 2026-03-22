from __future__ import annotations

from ..broker_registry import register_quote_broker_client
from .base import QuoteBrokerClient, QuoteBrokerEventSink
from .futu import FutuRealtimeQuoteClient
from .mock import MockRealtimeQuoteClient

_BUILTINS_REGISTERED = False


def ensure_builtin_quote_broker_registrations() -> None:
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return
    register_quote_broker_client("futu", FutuRealtimeQuoteClient)
    register_quote_broker_client("mock", MockRealtimeQuoteClient)
    _BUILTINS_REGISTERED = True


__all__ = [
    "FutuRealtimeQuoteClient",
    "MockRealtimeQuoteClient",
    "QuoteBrokerClient",
    "QuoteBrokerEventSink",
    "ensure_builtin_quote_broker_registrations",
]
