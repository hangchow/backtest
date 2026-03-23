from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .config import HistoryBrokerConfig, RealtimeQuoteBrokerConfig, TradeAccountConfig
    from .history_providers.base import DailyHistoryProvider
    from .quote_brokers.base import QuoteBrokerClient, QuoteBrokerEventSink
    from .trade_account.base import TradeAccountClient, TradeAccountEventSink
    QuoteBrokerFactory = Callable[[RealtimeQuoteBrokerConfig, QuoteBrokerEventSink, logging.Logger], QuoteBrokerClient]
    DailyHistoryProviderFactory = Callable[[HistoryBrokerConfig, logging.Logger], DailyHistoryProvider]
    TradeAccountClientFactory = Callable[[TradeAccountConfig, TradeAccountEventSink, logging.Logger], TradeAccountClient]
else:
    QuoteBrokerFactory = Callable[..., object]
    DailyHistoryProviderFactory = Callable[..., object]
    TradeAccountClientFactory = Callable[..., object]

_QUOTE_BROKER_FACTORIES: dict[str, QuoteBrokerFactory] = {}
_DAILY_HISTORY_PROVIDER_FACTORIES: dict[str, DailyHistoryProviderFactory] = {}
_TRADE_ACCOUNT_CLIENT_FACTORIES: dict[str, TradeAccountClientFactory] = {}


def _normalize_type_name(type_name: str, *, label: str) -> str:
    normalized = str(type_name).strip().lower()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _register_factory(
    registry: dict[str, object],
    type_name: str,
    factory: object,
    *,
    kind: str,
    replace: bool = False,
) -> None:
    normalized = _normalize_type_name(type_name, label=f"{kind} type")
    if not callable(factory):
        raise TypeError(f"{kind} factory for {normalized} must be callable")
    if not replace and normalized in registry:
        raise ValueError(f"{kind} type already registered: {normalized}")
    registry[normalized] = factory


def _unregister_factory(registry: dict[str, object], type_name: str, *, kind: str) -> None:
    normalized = _normalize_type_name(type_name, label=f"{kind} type")
    registry.pop(normalized, None)


def _unsupported_type_error(kind: str, type_name: str, supported_types: frozenset[str]) -> ValueError:
    supported = ", ".join(sorted(supported_types))
    return ValueError(f"unsupported {kind} type: {type_name}. supported: {supported}")


def register_quote_broker_client(
    broker_type: str,
    factory: QuoteBrokerFactory,
    *,
    replace: bool = False,
) -> None:
    _register_factory(_QUOTE_BROKER_FACTORIES, broker_type, factory, kind="quote broker", replace=replace)


def unregister_quote_broker_client(broker_type: str) -> None:
    _unregister_factory(_QUOTE_BROKER_FACTORIES, broker_type, kind="quote broker")


def ensure_builtin_quote_broker_registrations() -> None:
    from .quote_brokers import ensure_builtin_quote_broker_registrations as ensure_registrations

    ensure_registrations()


def supported_quote_broker_types() -> frozenset[str]:
    ensure_builtin_quote_broker_registrations()
    return frozenset(_QUOTE_BROKER_FACTORIES)


def resolve_quote_broker_factory(broker_type: str) -> QuoteBrokerFactory:
    ensure_builtin_quote_broker_registrations()
    normalized = _normalize_type_name(broker_type, label="quote broker type")
    try:
        return _QUOTE_BROKER_FACTORIES[normalized]
    except KeyError as exc:
        raise _unsupported_type_error("quote broker", normalized, supported_quote_broker_types()) from exc


def register_daily_history_provider(
    broker_type: str,
    factory: DailyHistoryProviderFactory,
    *,
    replace: bool = False,
) -> None:
    _register_factory(_DAILY_HISTORY_PROVIDER_FACTORIES, broker_type, factory, kind="history provider", replace=replace)


def unregister_daily_history_provider(broker_type: str) -> None:
    _unregister_factory(_DAILY_HISTORY_PROVIDER_FACTORIES, broker_type, kind="history provider")


def ensure_builtin_daily_history_provider_registrations() -> None:
    from .history_providers import ensure_builtin_daily_history_provider_registrations as ensure_registrations

    ensure_registrations()


def supported_daily_history_provider_types() -> frozenset[str]:
    ensure_builtin_daily_history_provider_registrations()
    return frozenset(_DAILY_HISTORY_PROVIDER_FACTORIES)


def resolve_daily_history_provider_factory(broker_type: str) -> DailyHistoryProviderFactory:
    ensure_builtin_daily_history_provider_registrations()
    normalized = _normalize_type_name(broker_type, label="history provider type")
    try:
        return _DAILY_HISTORY_PROVIDER_FACTORIES[normalized]
    except KeyError as exc:
        raise _unsupported_type_error("history provider", normalized, supported_daily_history_provider_types()) from exc


def register_trade_account_client(
    broker_type: str,
    factory: TradeAccountClientFactory,
    *,
    replace: bool = False,
) -> None:
    _register_factory(_TRADE_ACCOUNT_CLIENT_FACTORIES, broker_type, factory, kind="trade account", replace=replace)


def unregister_trade_account_client(broker_type: str) -> None:
    _unregister_factory(_TRADE_ACCOUNT_CLIENT_FACTORIES, broker_type, kind="trade account")


def ensure_builtin_trade_account_client_registrations() -> None:
    from .trade_account import ensure_builtin_trade_account_client_registrations as ensure_registrations

    ensure_registrations()


def supported_trade_account_client_types() -> frozenset[str]:
    ensure_builtin_trade_account_client_registrations()
    return frozenset(_TRADE_ACCOUNT_CLIENT_FACTORIES)


def resolve_trade_account_client_factory(broker_type: str) -> TradeAccountClientFactory:
    ensure_builtin_trade_account_client_registrations()
    normalized = _normalize_type_name(broker_type, label="trade account type")
    try:
        return _TRADE_ACCOUNT_CLIENT_FACTORIES[normalized]
    except KeyError as exc:
        raise _unsupported_type_error("trade account", normalized, supported_trade_account_client_types()) from exc
