from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


SUPPORTED_REALTIME_QUOTE_BROKER_TYPES = frozenset({"futu", "mock"})
SUPPORTED_HISTORY_BROKER_TYPES = frozenset({"futu", "polygon", "local"})
SUPPORTED_TRADE_BROKER_TYPES = frozenset({"futu", "mock"})
SUPPORTED_EXECUTOR_TYPES = frozenset({"mock", "futu_simulate", "futu_real"})
SUPPORTED_ORDER_SESSIONS = frozenset({"RTH", "ETH", "ALL", "OVERNIGHT"})
QUOTE_CONFIG_ALLOWED_TOP_LEVEL_KEYS = frozenset({"realtime_broker", "quote_broker", "broker", "history_broker", "stock_pool", "runtime"})
HISTORY_CONFIG_ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {"history_broker", "broker", "type", "host", "port", "market", "data_root", "history_host", "history_port", "kline_day_root"}
)
POOL_CONFIG_ALLOWED_TOP_LEVEL_KEYS = frozenset({"stock_pool", "pool", "codes", "strategy"})
TRADE_CONFIG_ALLOWED_TOP_LEVEL_KEYS = frozenset({"trade_accounts", "accounts"})


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _validate_allowed_top_level_keys(payload: Mapping[str, Any], *, label: str, allowed_keys: frozenset[str]) -> None:
    unexpected = sorted(set(payload) - set(allowed_keys))
    if unexpected:
        raise ValueError(f"{label} contains unsupported top-level keys: {', '.join(unexpected)}")


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


def _coerce_optional_float(value: Any, *, label: str) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def _coerce_optional_int(value: Any, *, label: str) -> int | None:
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
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


def _parse_trade_env(value: Any, *, label: str, default: str | None = "SIMULATE") -> str | None:
    if value is None:
        return default
    trade_env = str(value).strip().upper()
    if not trade_env:
        return default
    if trade_env not in {"SIMULATE", "REAL"}:
        raise ValueError(f"{label} must be SIMULATE or REAL")
    return trade_env


def _parse_executor_type(value: Any, *, label: str) -> str:
    executor = str(value or "mock").strip().lower()
    if executor not in SUPPORTED_EXECUTOR_TYPES:
        supported = ", ".join(sorted(SUPPORTED_EXECUTOR_TYPES))
        raise ValueError(f"{label} must be one of: {supported}")
    return executor


def _parse_order_session(value: Any, *, label: str, default: str = "RTH") -> str:
    session = str(value or default).strip().upper()
    if session not in SUPPORTED_ORDER_SESSIONS:
        supported = ", ".join(sorted(SUPPORTED_ORDER_SESSIONS))
        raise ValueError(f"{label} must be one of: {supported}")
    return session


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
    data_root: str | None = None

    def connection_signature(self) -> tuple[object, ...]:
        if self.type == "polygon":
            return (
                self.type,
                self.market,
            )
        if self.type == "local":
            return (
                self.type,
                self.market,
                self.data_root,
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
        if self.type == "local":
            return self.data_root or ".kline_day"
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class TradeBrokerConfig:
    type: str
    host: str
    port: int
    market: str = "US"
    trade_env: str | None = None
    account_index: int = 0
    fee_account: str | None = "futu_alt"
    security_type: str = "stock"
    account_poll_interval_seconds: float = 15.0
    position_poll_interval_seconds: float = 15.0
    initial_cash: float = 100000.0
    initial_positions: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    currency: str = "USD"

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
            self.initial_cash,
            self.initial_positions,
            self.currency,
        )


@dataclass(frozen=True)
class ExecutionConfig:
    """描述某个账户下单时应该走哪一种执行器，以及执行层风控上限。"""

    executor: str = "mock"
    enable_real_trading: bool = False
    allow_extended_hours_trading: bool = False
    order_session: str = "RTH"
    max_order_notional: float | None = None
    max_order_qty: int | None = None


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
    history_broker: HistoryBrokerConfig | None
    runtime: RuntimeConfig
    stock_pool: StockPoolConfig | None


@dataclass(frozen=True)
class TradeAccountConfig:
    account_id: str
    broker: TradeBrokerConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

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
    if broker_type == "local":
        data_root = str(raw.get("data_root", raw.get("kline_day_root", ".kline_day"))).strip() or ".kline_day"
        return HistoryBrokerConfig(
            type=broker_type,
            market=market,
            data_root=data_root,
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
    broker_type = _parse_broker_type(
        raw.get("type"),
        label=f"{label}.type",
        default="futu",
        supported_types=SUPPORTED_TRADE_BROKER_TYPES,
    )
    if broker_type == "mock":
        host = str(raw.get("trade_host", raw.get("host", "mock"))).strip() or "mock"
        port_raw = raw.get("trade_port", raw.get("port", 1))
        try:
            port = int(port_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}.port must be an integer") from exc
        if port < 0:
            raise ValueError(f"{label}.port must be >= 0")
        # mock 账户不连 Futu，trade_env 在这里没有语义，统一记成 None，避免日志误导成 SIMULATE。
        trade_env = None
    else:
        host = str(raw.get("trade_host", raw.get("host", ""))).strip()
        if not host:
            raise ValueError(f"{label}.host must not be empty")
        port = _coerce_port(raw.get("trade_port", raw.get("port")), label=f"{label}.port")
        trade_env = _parse_trade_env(raw.get("trade_env"), label=f"{label}.trade_env")

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
    currency = str(raw.get("currency", "USD")).strip().upper()
    if not currency:
        raise ValueError(f"{label}.currency must not be empty")
    initial_cash = _coerce_float(
        raw.get("initial_cash"),
        default=100000.0,
        label=f"{label}.initial_cash",
    )
    initial_positions = _parse_initial_positions(raw.get("initial_positions", {}), label=f"{label}.initial_positions")

    return TradeBrokerConfig(
        type=broker_type,
        host=host,
        port=port,
        market=_parse_market(raw.get("market"), label=f"{label}.market"),
        trade_env=trade_env,
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
        initial_cash=initial_cash,
        initial_positions=initial_positions,
        currency=currency,
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


def _parse_execution_config(raw: Mapping[str, Any], *, label: str) -> ExecutionConfig:
    """把 execution 段解析成统一的执行器配置。"""
    allow_extended_hours_trading = _coerce_bool(
        raw.get("allow_extended_hours_trading"),
        default=False,
        label=f"{label}.allow_extended_hours_trading",
    )
    order_session = _parse_order_session(
        raw.get("order_session"),
        label=f"{label}.order_session",
        default="ETH" if allow_extended_hours_trading else "RTH",
    )
    if allow_extended_hours_trading and order_session == "RTH":
        raise ValueError(f"{label}.order_session must be ETH/ALL/OVERNIGHT when allow_extended_hours_trading=true")
    if not allow_extended_hours_trading and order_session != "RTH":
        raise ValueError(f"{label}.order_session requires allow_extended_hours_trading=true")
    return ExecutionConfig(
        executor=_parse_executor_type(raw.get("executor"), label=f"{label}.executor"),
        enable_real_trading=_coerce_bool(
            raw.get("enable_real_trading"),
            default=False,
            label=f"{label}.enable_real_trading",
        ),
        allow_extended_hours_trading=allow_extended_hours_trading,
        order_session=order_session,
        max_order_notional=_coerce_optional_float(
            raw.get("max_order_notional"),
            label=f"{label}.max_order_notional",
        ),
        max_order_qty=_coerce_optional_int(
            raw.get("max_order_qty"),
            label=f"{label}.max_order_qty",
        ),
    )


def _parse_code(value: Any, *, label: str) -> str:
    code = str(value or "").strip().upper()
    if not code:
        raise ValueError(f"{label} must not be empty")
    if not code.startswith("US."):
        raise ValueError(f"only US symbols are supported, got: {code}")
    return code


def _parse_initial_positions(value: Any, *, label: str) -> tuple[tuple[str, int], ...]:
    """把 mock 账户初始持仓解析成稳定、可比较的元组结构。"""
    if value in (None, {}):
        return ()
    payload = _require_mapping(value, label)
    result: list[tuple[str, int]] = []
    for raw_code, raw_qty in payload.items():
        code = _parse_code(raw_code, label=f"{label}.{raw_code}")
        try:
            qty = int(raw_qty)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}.{code} must be an integer") from exc
        if qty < 0:
            raise ValueError(f"{label}.{code} must be >= 0")
        result.append((code, qty))
    return tuple(sorted(result))


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


def load_pool_config_from_text(text: str) -> StockPoolConfig:
    """把股票池配置 JSON 文本解析成 StockPoolConfig。"""
    raw = json.loads(text)
    payload = _require_mapping(raw, "pool config")
    _validate_allowed_top_level_keys(payload, label="pool config", allowed_keys=POOL_CONFIG_ALLOWED_TOP_LEVEL_KEYS)
    if "stock_pool" in payload and "pool" in payload:
        raise ValueError("pool config must not define both stock_pool and pool")
    has_wrapper = "stock_pool" in payload or "pool" in payload
    has_inline_fields = "codes" in payload or "strategy" in payload
    if has_wrapper and has_inline_fields:
        raise ValueError("pool config must use either stock_pool wrapper or top-level codes/strategy, not both")
    pool_raw = payload.get("stock_pool", payload.get("pool", payload))
    return _parse_stock_pool_config(
        _require_mapping(pool_raw, "stock_pool"),
    )


def _parse_trade_account_config(raw: Mapping[str, Any], *, index: int) -> TradeAccountConfig:
    account_id = str(raw.get("account_id", "")).strip()
    if not account_id:
        raise ValueError(f"trade_accounts[{index}].account_id must not be empty")
    broker = _parse_trade_broker_config(
        _require_mapping(raw.get("broker", {}), f"trade_accounts[{index}].broker"),
        label=f"trade_accounts[{index}].broker",
    )
    execution = _parse_execution_config(
        _require_mapping(raw.get("execution", {}), f"trade_accounts[{index}].execution"),
        label=f"trade_accounts[{index}].execution",
    )
    return TradeAccountConfig(account_id=account_id, broker=broker, execution=execution)


def load_quote_config_from_text(text: str) -> QuoteConfig:
    """把行情配置 JSON 文本解析成 QuoteConfig。"""
    raw = json.loads(text)
    payload = _require_mapping(raw, "quote config")
    _validate_allowed_top_level_keys(payload, label="quote config", allowed_keys=QUOTE_CONFIG_ALLOWED_TOP_LEVEL_KEYS)

    shared_broker_raw = payload.get("quote_broker", payload.get("broker"))
    realtime_broker_raw = payload.get("realtime_broker", shared_broker_raw)
    history_broker_raw = payload.get("history_broker")
    if history_broker_raw is None and shared_broker_raw is not None:
        history_broker_raw = shared_broker_raw
    realtime_broker = _parse_realtime_quote_broker_config(
        _require_mapping(realtime_broker_raw, "realtime_broker"),
        label="realtime_broker",
    )
    history_broker = None
    if history_broker_raw is not None:
        history_broker = _parse_history_broker_config(
            _require_mapping(history_broker_raw, "history_broker"),
            label="history_broker",
        )
    runtime = _parse_runtime_config(_require_mapping(payload.get("runtime", {}), "runtime"))
    stock_pool_raw = payload.get("stock_pool")
    stock_pool = None
    if stock_pool_raw is not None:
        stock_pool = _parse_stock_pool_config(_require_mapping(stock_pool_raw, "stock_pool"))
    return QuoteConfig(
        realtime_broker=realtime_broker,
        history_broker=history_broker,
        runtime=runtime,
        stock_pool=stock_pool,
    )


def load_trade_accounts_config_from_text(text: str) -> TradeAccountsConfig:
    """把交易账户配置 JSON 文本解析成 TradeAccountsConfig。"""
    raw = json.loads(text)
    payload = _require_mapping(raw, "trade accounts config")
    _validate_allowed_top_level_keys(payload, label="trade accounts config", allowed_keys=TRADE_CONFIG_ALLOWED_TOP_LEVEL_KEYS)
    if "trade_accounts" in payload and "accounts" in payload:
        raise ValueError("trade accounts config must not define both trade_accounts and accounts")
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


def load_history_config_from_text(text: str) -> HistoryBrokerConfig:
    """把历史 warm-up 配置 JSON 文本解析成 HistoryBrokerConfig。"""
    raw = json.loads(text)
    payload = _require_mapping(raw, "history config")
    _validate_allowed_top_level_keys(payload, label="history config", allowed_keys=HISTORY_CONFIG_ALLOWED_TOP_LEVEL_KEYS)
    if "history_broker" in payload and "broker" in payload:
        raise ValueError("history config must not define both history_broker and broker")
    has_wrapper = "history_broker" in payload or "broker" in payload
    has_inline_fields = any(
        key in payload
        for key in ("type", "host", "port", "market", "data_root", "history_host", "history_port", "kline_day_root")
    )
    if has_wrapper and has_inline_fields:
        raise ValueError("history config must use either history_broker wrapper or top-level broker fields, not both")
    broker_raw = payload.get("history_broker", payload.get("broker", payload))
    return _parse_history_broker_config(
        _require_mapping(broker_raw, "history_broker"),
        label="history_broker",
    )


def build_livetrading_config(
    quote_config: QuoteConfig,
    trade_accounts_config: TradeAccountsConfig,
    history_config: HistoryBrokerConfig | None = None,
    pool_config: StockPoolConfig | None = None,
) -> LiveTradingConfig:
    """合并 quote/history/pool/trade 配置，并校验关键字段是否一致。"""
    if history_config is not None and quote_config.history_broker is not None:
        raise ValueError("history broker config overlaps between quote config and --history-config")
    if pool_config is not None and quote_config.stock_pool is not None:
        raise ValueError("stock pool config overlaps between quote config and --pool-config")
    final_history_broker = history_config or quote_config.history_broker
    if final_history_broker is None:
        raise ValueError("history broker config must be provided either inline in quote config or via --history-config")
    final_stock_pool = pool_config or quote_config.stock_pool
    if final_stock_pool is None:
        raise ValueError("stock pool config must be provided either inline in quote config or via --pool-config")
    for account in trade_accounts_config.accounts:
        if account.broker.market != quote_config.realtime_broker.market:
            raise ValueError(
                f"trade account {account.account_id} market {account.broker.market} "
                f"does not match quote market {quote_config.realtime_broker.market}"
            )
        if account.execution.allow_extended_hours_trading:
            if account.broker.type != "futu":
                raise ValueError(
                    f"trade account {account.account_id} allow_extended_hours_trading only supports broker.type=futu"
                )
            if account.execution.executor == "mock":
                raise ValueError(
                    f"trade account {account.account_id} allow_extended_hours_trading requires a futu submit executor"
                )
        if account.execution.executor == "futu_simulate" and account.broker.trade_env != "SIMULATE":
            raise ValueError(
                f"trade account {account.account_id} executor futu_simulate requires broker.trade_env=SIMULATE"
            )
        if account.broker.type == "mock" and account.execution.executor != "mock":
            raise ValueError(
                f"trade account {account.account_id} broker.type=mock only supports execution.executor=mock"
            )
        if account.execution.executor == "futu_real":
            if account.broker.trade_env != "REAL":
                raise ValueError(
                    f"trade account {account.account_id} executor futu_real requires broker.trade_env=REAL"
                )
            if not account.execution.enable_real_trading:
                raise ValueError(
                    f"trade account {account.account_id} executor futu_real requires execution.enable_real_trading=true"
                )
    if quote_config.realtime_broker.market != final_history_broker.market:
        raise ValueError(
            f"history broker market {final_history_broker.market} "
            f"does not match realtime broker market {quote_config.realtime_broker.market}"
        )
    return LiveTradingConfig(
        quote=QuoteConfig(
            realtime_broker=quote_config.realtime_broker,
            history_broker=final_history_broker,
            runtime=quote_config.runtime,
            stock_pool=final_stock_pool,
        ),
        trade_accounts=trade_accounts_config.accounts,
    )


def load_quote_config(path: Path | str) -> QuoteConfig:
    config_path = Path(path)
    return load_quote_config_from_text(config_path.read_text(encoding="utf-8"))


def load_trade_accounts_config(path: Path | str) -> TradeAccountsConfig:
    config_path = Path(path)
    return load_trade_accounts_config_from_text(config_path.read_text(encoding="utf-8"))


def load_history_config(path: Path | str) -> HistoryBrokerConfig:
    config_path = Path(path)
    return load_history_config_from_text(config_path.read_text(encoding="utf-8"))


def load_pool_config(path: Path | str) -> StockPoolConfig:
    config_path = Path(path)
    return load_pool_config_from_text(config_path.read_text(encoding="utf-8"))


def load_livetrading_config(
    quote_config_path: Path | str,
    trade_accounts_path: Path | str,
    history_config_path: Path | str | None = None,
    pool_config_path: Path | str | None = None,
) -> LiveTradingConfig:
    """从 quote / history / pool / trade 配置路径读取并构建完整的 LiveTradingConfig。"""
    return build_livetrading_config(
        load_quote_config(quote_config_path),
        load_trade_accounts_config(trade_accounts_path),
        load_history_config(history_config_path) if history_config_path is not None else None,
        load_pool_config(pool_config_path) if pool_config_path is not None else None,
    )
