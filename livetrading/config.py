from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


SUPPORTED_REALTIME_QUOTE_BROKER_TYPES = frozenset({"futu", "mock"})
SUPPORTED_HISTORY_BROKER_TYPES = frozenset({"futu", "polygon"})
SUPPORTED_TRADE_BROKER_TYPES = frozenset({"futu"})


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _coerce_bool(value: Any, *, default: bool, label: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"{label} must be a boolean")


def _coerce_float(value: Any, *, default: float, label: str) -> float:
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def _coerce_port(value: Any, *, label: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if port <= 0:
        raise ValueError(f"{label} must be positive")
    return port


def _parse_broker_type(
    value: Any,
    *,
    label: str,
    default: str,
    supported_types: frozenset[str],
) -> str:
    broker_type = str(value or default).strip().lower()
    if broker_type not in supported_types:
        supported = ", ".join(sorted(supported_types))
        raise ValueError(f"unsupported broker type for {label}: {broker_type}. supported: {supported}")
    return broker_type


def _parse_market(value: Any, *, label: str) -> str:
    market = str(value or "US").strip().upper()
    if market != "US":
        raise ValueError(f"{label} must be US")
    return market


def _parse_trade_env(value: Any, *, label: str) -> str:
    trade_env = str(value or "SIMULATE").strip().upper()
    if trade_env not in {"SIMULATE", "REAL"}:
        raise ValueError(f"{label} must be SIMULATE or REAL")
    return trade_env


@dataclass(frozen=True)
class RealtimeQuoteBrokerConfig:
    type: str
    host: str
    port: int
    market: str = "US"
    extended_time: bool = False

    def connection_signature(self) -> tuple[object, ...]:
        return (
            self.type,
            self.host,
            self.port,
            self.market,
            self.extended_time,
        )

    def endpoint_summary(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class HistoryBrokerConfig:
    type: str
    host: str | None = None
    port: int | None = None
    market: str = "US"

    def connection_signature(self) -> tuple[object, ...]:
        if self.type == "polygon":
            return (
                self.type,
                self.market,
            )
        return (
            self.type,
            self.host,
            self.port,
            self.market,
        )

    def endpoint_summary(self) -> str:
        if self.type == "polygon":
            return "polygon"
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class TradeBrokerConfig:
    type: str
    host: str
    port: int
    market: str = "US"
    trade_env: str = "SIMULATE"
    account_index: int = 0
    fee_account: str | None = "futu_alt"
    security_type: str = "stock"
    account_poll_interval_seconds: float = 15.0
    position_poll_interval_seconds: float = 15.0

    def connection_signature(self) -> tuple[object, ...]:
        return (
            self.type,
            self.host,
            self.port,
            self.market,
            self.trade_env,
            self.account_index,
            self.fee_account,
            self.security_type,
            self.account_poll_interval_seconds,
            self.position_poll_interval_seconds,
        )


@dataclass(frozen=True)
class RuntimeConfig:
    config_reload_interval_seconds: float = 10.0
    log_level: str = "INFO"
    log_price_updates: bool = True
    log_account_updates: bool = True
    log_position_updates: bool = True


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StockPoolConfig:
    codes: tuple[str, ...]
    strategy: StrategyConfig


@dataclass(frozen=True)
class QuoteConfig:
    realtime_broker: RealtimeQuoteBrokerConfig
    history_broker: HistoryBrokerConfig
    runtime: RuntimeConfig
    stock_pool: StockPoolConfig


@dataclass(frozen=True)
class TradeAccountConfig:
    account_id: str
    broker: TradeBrokerConfig

    def connection_signature(self) -> tuple[object, ...]:
        return (self.account_id,) + self.broker.connection_signature()


@dataclass(frozen=True)
class TradeAccountsConfig:
    accounts: tuple[TradeAccountConfig, ...]

    def account_map(self) -> dict[str, TradeAccountConfig]:
        return {account.account_id: account for account in self.accounts}


@dataclass(frozen=True)
class LiveTradingConfig:
    quote: QuoteConfig
    trade_accounts: tuple[TradeAccountConfig, ...]

    @property
    def runtime(self) -> RuntimeConfig:
        return self.quote.runtime

    @property
    def stock_pool(self) -> StockPoolConfig:
        return self.quote.stock_pool

    @property
    def realtime_broker(self) -> RealtimeQuoteBrokerConfig:
        return self.quote.realtime_broker

    @property
    def history_broker(self) -> HistoryBrokerConfig:
        return self.quote.history_broker

    @property
    def quote_broker(self) -> RealtimeQuoteBrokerConfig:
        return self.quote.realtime_broker

    def trade_account_map(self) -> dict[str, TradeAccountConfig]:
        return {account.account_id: account for account in self.trade_accounts}

    def all_codes(self) -> tuple[str, ...]:
        return self.stock_pool.codes


def _parse_realtime_quote_broker_config(raw: Mapping[str, Any], *, label: str) -> RealtimeQuoteBrokerConfig:
    host = str(raw.get("quote_host", raw.get("host", ""))).strip()
    if not host:
        raise ValueError(f"{label}.host must not be empty")
    port = _coerce_port(raw.get("quote_port", raw.get("port")), label=f"{label}.port")
    return RealtimeQuoteBrokerConfig(
        type=_parse_broker_type(
            raw.get("type"),
            label=f"{label}.type",
            default="futu",
            supported_types=SUPPORTED_REALTIME_QUOTE_BROKER_TYPES,
        ),
        host=host,
        port=port,
        market=_parse_market(raw.get("market"), label=f"{label}.market"),
        extended_time=_coerce_bool(
            raw.get("extended_time"),
            default=False,
            label=f"{label}.extended_time",
        ),
    )


def _parse_history_broker_config(raw: Mapping[str, Any], *, label: str) -> HistoryBrokerConfig:
    broker_type = _parse_broker_type(
        raw.get("type"),
        label=f"{label}.type",
        default="futu",
        supported_types=SUPPORTED_HISTORY_BROKER_TYPES,
    )
    market = _parse_market(raw.get("market"), label=f"{label}.market")
    if broker_type == "polygon":
        host_raw = raw.get("history_host", raw.get("host"))
        port_raw = raw.get("history_port", raw.get("port"))
        host = None if host_raw is None else str(host_raw).strip() or None
        port = None if port_raw is None else _coerce_port(port_raw, label=f"{label}.port")
        return HistoryBrokerConfig(
            type=broker_type,
            host=host,
            port=port,
            market=market,
        )

    host = str(raw.get("history_host", raw.get("host", ""))).strip()
    if not host:
        raise ValueError(f"{label}.host must not be empty")
    port = _coerce_port(raw.get("history_port", raw.get("port")), label=f"{label}.port")
    return HistoryBrokerConfig(
        type=broker_type,
        host=host,
        port=port,
        market=market,
    )


def _parse_trade_broker_config(raw: Mapping[str, Any], *, label: str) -> TradeBrokerConfig:
    host = str(raw.get("trade_host", raw.get("host", ""))).strip()
    if not host:
        raise ValueError(f"{label}.host must not be empty")
    port = _coerce_port(raw.get("trade_port", raw.get("port")), label=f"{label}.port")

    try:
        account_index = int(raw.get("account_index", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}.account_index must be an integer") from exc
    if account_index < 0:
        raise ValueError(f"{label}.account_index must be >= 0")

    fee_account = raw.get("fee_account", "futu_alt")
    if fee_account is not None:
        fee_account = str(fee_account).strip() or None

    security_type = str(raw.get("security_type", "stock")).strip().lower()
    if not security_type:
        raise ValueError(f"{label}.security_type must not be empty")

    return TradeBrokerConfig(
        type=_parse_broker_type(
            raw.get("type"),
            label=f"{label}.type",
            default="futu",
            supported_types=SUPPORTED_TRADE_BROKER_TYPES,
        ),
        host=host,
        port=port,
        market=_parse_market(raw.get("market"), label=f"{label}.market"),
        trade_env=_parse_trade_env(raw.get("trade_env"), label=f"{label}.trade_env"),
        account_index=account_index,
        fee_account=fee_account,
        security_type=security_type,
        account_poll_interval_seconds=_coerce_float(
            raw.get("account_poll_interval_seconds"),
            default=15.0,
            label=f"{label}.account_poll_interval_seconds",
        ),
        position_poll_interval_seconds=_coerce_float(
            raw.get("position_poll_interval_seconds"),
            default=15.0,
            label=f"{label}.position_poll_interval_seconds",
        ),
    )


def _parse_runtime_config(raw: Mapping[str, Any]) -> RuntimeConfig:
    log_level = str(raw.get("log_level", "INFO")).strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("runtime.log_level must be a valid logging level name")

    return RuntimeConfig(
        config_reload_interval_seconds=_coerce_float(
            raw.get("config_reload_interval_seconds"),
            default=10.0,
            label="runtime.config_reload_interval_seconds",
        ),
        log_level=log_level,
        log_price_updates=_coerce_bool(
            raw.get("log_price_updates"),
            default=True,
            label="runtime.log_price_updates",
        ),
        log_account_updates=_coerce_bool(
            raw.get("log_account_updates"),
            default=True,
            label="runtime.log_account_updates",
        ),
        log_position_updates=_coerce_bool(
            raw.get("log_position_updates"),
            default=True,
            label="runtime.log_position_updates",
        ),
    )


def _parse_code(value: Any, *, label: str) -> str:
    code = str(value or "").strip().upper()
    if not code:
        raise ValueError(f"{label} must not be empty")
    if not code.startswith("US."):
        raise ValueError(f"only US symbols are supported, got: {code}")
    return code


def _parse_strategy_config(raw: Any, *, label: str) -> StrategyConfig:
    if isinstance(raw, Mapping):
        strategy_name = str(raw.get("name", "")).strip()
        params = dict(_require_mapping(raw.get("params", {}), f"{label}.params"))
    else:
        strategy_name = str(raw or "").strip()
        params = {}
    if not strategy_name:
        raise ValueError(f"{label}.name must not be empty")
    return StrategyConfig(name=strategy_name, params=params)


def _parse_stock_pool_config(raw: Mapping[str, Any]) -> StockPoolConfig:
    codes_raw = raw.get("codes")
    if not isinstance(codes_raw, list) or not codes_raw:
        raise ValueError("stock_pool.codes must be a non-empty array")
    codes = tuple(_parse_code(item, label="stock_pool.codes[]") for item in codes_raw)
    if len(set(codes)) != len(codes):
        raise ValueError("stock_pool.codes contains duplicates")
    strategy = _parse_strategy_config(raw.get("strategy"), label="stock_pool.strategy")
    return StockPoolConfig(codes=codes, strategy=strategy)


def _parse_trade_account_config(raw: Mapping[str, Any], *, index: int) -> TradeAccountConfig:
    account_id = str(raw.get("account_id", "")).strip()
    if not account_id:
        raise ValueError(f"trade_accounts[{index}].account_id must not be empty")
    broker = _parse_trade_broker_config(
        _require_mapping(raw.get("broker", {}), f"trade_accounts[{index}].broker"),
        label=f"trade_accounts[{index}].broker",
    )
    return TradeAccountConfig(account_id=account_id, broker=broker)


def load_quote_config_from_text(text: str) -> QuoteConfig:
    raw = json.loads(text)
    payload = _require_mapping(raw, "quote config")

    if "stock_pool" not in payload or payload.get("stock_pool") is None:
        raise ValueError("quote config must define stock_pool")

    shared_broker_raw = payload.get("quote_broker", payload.get("broker", {}))
    realtime_broker_raw = payload.get("realtime_broker", shared_broker_raw)
    history_broker_raw = payload.get("history_broker", shared_broker_raw)
    realtime_broker = _parse_realtime_quote_broker_config(
        _require_mapping(realtime_broker_raw, "realtime_broker"),
        label="realtime_broker",
    )
    history_broker = _parse_history_broker_config(
        _require_mapping(history_broker_raw, "history_broker"),
        label="history_broker",
    )
    runtime = _parse_runtime_config(_require_mapping(payload.get("runtime", {}), "runtime"))
    stock_pool = _parse_stock_pool_config(_require_mapping(payload.get("stock_pool", {}), "stock_pool"))
    return QuoteConfig(
        realtime_broker=realtime_broker,
        history_broker=history_broker,
        runtime=runtime,
        stock_pool=stock_pool,
    )


def load_trade_accounts_config_from_text(text: str) -> TradeAccountsConfig:
    raw = json.loads(text)
    payload = _require_mapping(raw, "trade accounts config")
    accounts_raw = payload.get("trade_accounts", payload.get("accounts"))
    if not isinstance(accounts_raw, list) or not accounts_raw:
        raise ValueError("trade_accounts must be a non-empty array")
    accounts = tuple(
        _parse_trade_account_config(_require_mapping(item, f"trade_accounts[{index}]"), index=index)
        for index, item in enumerate(accounts_raw)
    )
    account_ids = [account.account_id for account in accounts]
    if len(set(account_ids)) != len(account_ids):
        raise ValueError("trade_accounts contains duplicate account_id values")
    return TradeAccountsConfig(accounts=accounts)


def build_livetrading_config(quote_config: QuoteConfig, trade_accounts_config: TradeAccountsConfig) -> LiveTradingConfig:
    for account in trade_accounts_config.accounts:
        if account.broker.market != quote_config.realtime_broker.market:
            raise ValueError(
                f"trade account {account.account_id} market {account.broker.market} "
                f"does not match quote market {quote_config.realtime_broker.market}"
            )
    if quote_config.realtime_broker.market != quote_config.history_broker.market:
        raise ValueError(
            f"history broker market {quote_config.history_broker.market} "
            f"does not match realtime broker market {quote_config.realtime_broker.market}"
        )
    return LiveTradingConfig(
        quote=quote_config,
        trade_accounts=trade_accounts_config.accounts,
    )


def load_quote_config(path: Path | str) -> QuoteConfig:
    config_path = Path(path)
    return load_quote_config_from_text(config_path.read_text(encoding="utf-8"))


def load_trade_accounts_config(path: Path | str) -> TradeAccountsConfig:
    config_path = Path(path)
    return load_trade_accounts_config_from_text(config_path.read_text(encoding="utf-8"))


def load_livetrading_config(quote_config_path: Path | str, trade_accounts_path: Path | str) -> LiveTradingConfig:
    return build_livetrading_config(
        load_quote_config(quote_config_path),
        load_trade_accounts_config(trade_accounts_path),
    )
