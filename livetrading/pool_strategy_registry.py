from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .config import StockPoolConfig
    from .pool_strategies import PoolLiveStrategy

    PoolStrategyFactory = Callable[[StockPoolConfig], PoolLiveStrategy]
else:
    PoolStrategyFactory = Callable[..., object]

_POOL_STRATEGY_FACTORIES: dict[str, PoolStrategyFactory] = {}


def _normalize_strategy_name(name: str, *, label: str) -> str:
    normalized = str(name).strip().lower()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def register_pool_strategy(
    strategy_name: str,
    factory: PoolStrategyFactory,
    *,
    replace: bool = False,
) -> None:
    normalized = _normalize_strategy_name(strategy_name, label="pool strategy name")
    if not callable(factory):
        raise TypeError(f"pool strategy factory for {normalized} must be callable")
    if not replace and normalized in _POOL_STRATEGY_FACTORIES:
        raise ValueError(f"pool strategy already registered: {normalized}")
    _POOL_STRATEGY_FACTORIES[normalized] = factory


def unregister_pool_strategy(strategy_name: str) -> None:
    normalized = _normalize_strategy_name(strategy_name, label="pool strategy name")
    _POOL_STRATEGY_FACTORIES.pop(normalized, None)


def ensure_builtin_pool_strategy_registrations() -> None:
    from .pool_strategies import ensure_builtin_pool_strategy_registrations as ensure_registrations

    ensure_registrations()


def supported_pool_strategy_names() -> frozenset[str]:
    ensure_builtin_pool_strategy_registrations()
    return frozenset(_POOL_STRATEGY_FACTORIES)


def resolve_pool_strategy_factory(strategy_name: str) -> PoolStrategyFactory:
    ensure_builtin_pool_strategy_registrations()
    normalized = _normalize_strategy_name(strategy_name, label="pool strategy name")
    try:
        return _POOL_STRATEGY_FACTORIES[normalized]
    except KeyError as exc:
        supported = ", ".join(sorted(supported_pool_strategy_names()))
        raise ValueError(f"unsupported stock_pool strategy: {normalized}. supported: {supported}") from exc
