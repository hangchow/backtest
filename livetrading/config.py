from __future__ import annotations

from datetime import datetime
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from .broker import (
    supported_daily_history_provider_types,
    supported_quote_broker_types,
    supported_trade_account_client_types,
)
from .pool_strategy_registry import supported_pool_strategy_names

SUPPORTED_EXECUTOR_TYPES = frozenset({"mock", "futu_simulate", "futu_real", "notify"})
SUPPORTED_ORDER_SESSIONS = frozenset({"RTH", "ETH", "ALL"})
QUOTE_CONFIG_ALLOWED_TOP_LEVEL_KEYS = frozenset({"realtime_broker", "quote_broker", "broker", "history_broker", "stock_pool", "runtime"})
HISTORY_CONFIG_ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {"history_broker", "broker", "type", "host", "port", "data_root", "history_host", "history_port", "kline_day_root"}
)
POOL_CONFIG_ALLOWED_TOP_LEVEL_KEYS = frozenset({"stock_pool", "pool", "codes", "strategy"})
TRADE_CONFIG_ALLOWED_TOP_LEVEL_KEYS = frozenset({"trade_account"})
REALTIME_BROKER_ALLOWED_KEYS = frozenset(
    {"type", "host", "port", "quote_host", "quote_port", "trigger_time", "timezone", "market_calendar", "catch_up_missed_session"}
)
REALTIME_BROKER_SHARED_ALLOWED_KEYS = REALTIME_BROKER_ALLOWED_KEYS | frozenset(
    {"history_host", "history_port", "data_root", "kline_day_root"}
)
HISTORY_BROKER_ALLOWED_KEYS = frozenset({"type", "host", "port", "data_root", "history_host", "history_port", "kline_day_root"})
HISTORY_BROKER_SHARED_ALLOWED_KEYS = HISTORY_BROKER_ALLOWED_KEYS | frozenset({"quote_host", "quote_port"})
TRADE_ACCOUNT_ALLOWED_KEYS = frozenset({"account_id", "broker", "execution", "notification"})
TRADE_BROKER_ALLOWED_KEYS = frozenset(
    {
        "type",
        "host",
        "port",
        "trade_host",
        "trade_port",
        "trade_env",
        "account_index",
        "fee_account",
        "account_poll_interval_seconds",
        "position_poll_interval_seconds",
        "initial_cash",
        "initial_positions",
    }
)
EXECUTION_ALLOWED_KEYS = frozenset({"executor", "order_session"})
NOTIFICATION_ALLOWED_KEYS = frozenset({"email"})
EMAIL_NOTIFICATION_ALLOWED_KEYS = frozenset(
    {"enabled", "smtp_host", "smtp_port", "username", "password", "password_env", "from", "to", "subject_prefix", "use_tls"}
)
DEFAULT_MARKET = "US"
DEFAULT_CURRENCY = "USD"
DEFAULT_SECURITY_TYPE = "stock"


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _validate_allowed_top_level_keys(payload: Mapping[str, Any], *, label: str, allowed_keys: frozenset[str]) -> None:
    unexpected = sorted(set(payload) - set(allowed_keys))
    if unexpected:
        raise ValueError(f"{label} contains unsupported top-level keys: {', '.join(unexpected)}")


def _validate_allowed_mapping_keys(payload: Mapping[str, Any], *, label: str, allowed_keys: frozenset[str]) -> None:
    unexpected = sorted(set(payload) - set(allowed_keys))
    if unexpected:
        raise ValueError(f"{label} contains unsupported keys: {', '.join(unexpected)}")


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
    host: str | None = None
    port: int | None = None
    trigger_time: str | None = None
    timezone: str | None = None
    market_calendar: str | None = None
    catch_up_missed_session: bool = False
    subscribe_extended_time: bool = False

    def connection_signature(self) -> tuple[object, ...]:
        return (
            self.type,
            self.host,
            self.port,
            self.trigger_time,
            self.timezone,
            self.market_calendar,
            self.catch_up_missed_session,
            self.subscribe_extended_time,
        )

    def endpoint_summary(self) -> str:
        if self.type == "schedule_us":
            return (
                f"{self.market_calendar or 'XNYS'} "
                f"{self.timezone or 'America/New_York'} "
                f"{self.trigger_time or '09:30'}"
            )
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class HistoryBrokerConfig:
    type: str
    host: str | None = None
    port: int | None = None
    data_root: str | None = None

    def effective_data_root(self) -> str:
        return self.data_root or ".kline_day"

    def connection_signature(self) -> tuple[object, ...]:
        if self.type == "polygon":
            return (
                self.type,
                self.effective_data_root(),
            )
        if self.type == "local":
            return (
                self.type,
                self.effective_data_root(),
            )
        return (
            self.type,
            self.host,
            self.port,
            self.effective_data_root(),
        )

    def endpoint_summary(self) -> str:
        if self.type == "polygon":
            return "polygon"
        if self.type == "local":
            return self.effective_data_root()
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class TradeBrokerConfig:
    type: str
    host: str
    port: int
    trade_env: str | None = None
    account_index: int = 0
    fee_account: str | None = "futu_alt"
    account_poll_interval_seconds: float = 15.0
    position_poll_interval_seconds: float = 15.0
    initial_cash: float = 100000.0
    initial_positions: tuple[tuple[str, int], ...] = field(default_factory=tuple)

    def connection_signature(self) -> tuple[object, ...]:
        return (
            self.type,
            self.host,
            self.port,
            self.trade_env,
            self.account_index,
            self.fee_account,
            self.account_poll_interval_seconds,
            self.position_poll_interval_seconds,
            self.initial_cash,
            self.initial_positions,
        )


@dataclass(frozen=True)
class ExecutionConfig:
    """描述某个账户下单时应该走哪一种执行器，以及执行层风控上限。"""

    executor: str = "mock"
    order_session: str = "RTH"


@dataclass(frozen=True)
class EmailNotificationConfig:
    enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    username: str | None = None
    password: str | None = None
    password_env: str | None = None
    from_address: str | None = None
    to_addresses: tuple[str, ...] = field(default_factory=tuple)
    subject_prefix: str = "[livetrading]"
    use_tls: bool = True


@dataclass(frozen=True)
class NotificationConfig:
    email: EmailNotificationConfig = field(default_factory=EmailNotificationConfig)


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
    notification: NotificationConfig = field(default_factory=NotificationConfig)

    def connection_signature(self) -> tuple[object, ...]:
        return (self.account_id,) + self.broker.connection_signature()


@dataclass(frozen=True)
class LiveTradingConfig:
    quote: QuoteConfig
    trade_account: TradeAccountConfig

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

    def all_codes(self) -> tuple[str, ...]:
        return self.stock_pool.codes


def _parse_realtime_quote_broker_config(
    raw: Mapping[str, Any],
    *,
    label: str,
    allow_cross_endpoint_aliases: bool = False,
) -> RealtimeQuoteBrokerConfig:
    _validate_allowed_mapping_keys(
        raw,
        label=label,
        allowed_keys=REALTIME_BROKER_SHARED_ALLOWED_KEYS if allow_cross_endpoint_aliases else REALTIME_BROKER_ALLOWED_KEYS,
    )
    broker_type = _parse_broker_type(
        raw.get("type"),
        label=f"{label}.type",
        default="futu",
        supported_types=supported_quote_broker_types(),
    )
    if broker_type == "schedule_us":
        trigger_time = str(raw.get("trigger_time", "09:30")).strip() or "09:30"
        try:
            datetime.strptime(trigger_time, "%H:%M")
        except ValueError as exc:
            raise ValueError(f"{label}.trigger_time must use HH:MM format") from exc
        timezone = str(raw.get("timezone", "America/New_York")).strip() or "America/New_York"
        market_calendar = str(raw.get("market_calendar", "XNYS")).strip().upper() or "XNYS"
        return RealtimeQuoteBrokerConfig(
            type=broker_type,
            trigger_time=trigger_time,
            timezone=timezone,
            market_calendar=market_calendar,
            catch_up_missed_session=_coerce_bool(
                raw.get("catch_up_missed_session"),
                default=False,
                label=f"{label}.catch_up_missed_session",
            ),
        )

    host = str(raw.get("quote_host", raw.get("host", ""))).strip()
    if not host:
        raise ValueError(f"{label}.host must not be empty")
    port = _coerce_port(raw.get("quote_port", raw.get("port")), label=f"{label}.port")
    return RealtimeQuoteBrokerConfig(
        type=broker_type,
        host=host,
        port=port,
    )


def _parse_history_broker_config(
    raw: Mapping[str, Any],
    *,
    label: str,
    allow_cross_endpoint_aliases: bool = False,
) -> HistoryBrokerConfig:
    _validate_allowed_mapping_keys(
        raw,
        label=label,
        allowed_keys=HISTORY_BROKER_SHARED_ALLOWED_KEYS if allow_cross_endpoint_aliases else HISTORY_BROKER_ALLOWED_KEYS,
    )
    broker_type = _parse_broker_type(
        raw.get("type"),
        label=f"{label}.type",
        default="futu",
        supported_types=supported_daily_history_provider_types(),
    )
    data_root = str(raw.get("data_root", raw.get("kline_day_root", ".kline_day"))).strip() or ".kline_day"
    if broker_type == "polygon":
        host_raw = raw.get("history_host", raw.get("host"))
        port_raw = raw.get("history_port", raw.get("port"))
        host = None if host_raw is None else str(host_raw).strip() or None
        port = None if port_raw is None else _coerce_port(port_raw, label=f"{label}.port")
        return HistoryBrokerConfig(
            type=broker_type,
            host=host,
            port=port,
            data_root=data_root,
        )
    if broker_type == "local":
        return HistoryBrokerConfig(
            type=broker_type,
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
        data_root=data_root,
    )


def _parse_trade_broker_config(raw: Mapping[str, Any], *, label: str) -> TradeBrokerConfig:
    _validate_allowed_mapping_keys(raw, label=label, allowed_keys=TRADE_BROKER_ALLOWED_KEYS)
    broker_type = _parse_broker_type(
        raw.get("type"),
        label=f"{label}.type",
        default="futu",
        supported_types=supported_trade_account_client_types(),
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
        trade_env=trade_env,
        account_index=account_index,
        fee_account=fee_account,
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


def _parse_execution_config(
    raw: Mapping[str, Any],
    *,
    label: str,
    broker: TradeBrokerConfig | None = None,
) -> ExecutionConfig:
    """把 execution 段解析成统一的执行器配置。"""
    _validate_allowed_mapping_keys(raw, label=label, allowed_keys=EXECUTION_ALLOWED_KEYS)
    executor = _parse_executor_type(raw.get("executor"), label=f"{label}.executor")
    default_order_session = (
        "ETH"
        if (
            broker is not None
            and broker.type == "futu"
            and broker.trade_env == "REAL"
            and executor == "futu_real"
        )
        else "RTH"
    )
    order_session = _parse_order_session(
        raw.get("order_session"),
        label=f"{label}.order_session",
        default=default_order_session,
    )
    if order_session != "RTH" and broker is not None:
        if executor != "mock" and broker.type != "futu":
            raise ValueError(f"{label}.order_session only supports broker.type=futu")
    return ExecutionConfig(
        executor=executor,
        order_session=order_session,
    )


def _parse_email_recipients(value: Any, *, label: str) -> tuple[str, ...]:
    if value in (None, []):
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    recipients = tuple(str(item).strip() for item in value if str(item).strip())
    if not recipients:
        raise ValueError(f"{label} must not be empty")
    return recipients


def _parse_email_notification_config(raw: Mapping[str, Any], *, label: str) -> EmailNotificationConfig:
    _validate_allowed_mapping_keys(raw, label=label, allowed_keys=EMAIL_NOTIFICATION_ALLOWED_KEYS)
    enabled = _coerce_bool(raw.get("enabled"), default=False, label=f"{label}.enabled")
    smtp_host = str(raw.get("smtp_host", "")).strip() or None
    smtp_port = _coerce_port(raw.get("smtp_port", 587), label=f"{label}.smtp_port")
    username = raw.get("username")
    if username is not None:
        username = str(username).strip() or None
    password = raw.get("password")
    if password is not None:
        password = str(password) or None
    password_env = raw.get("password_env")
    if password_env is not None:
        password_env = str(password_env).strip() or None
    from_address = raw.get("from")
    if from_address is not None:
        from_address = str(from_address).strip() or None
    to_addresses = _parse_email_recipients(raw.get("to"), label=f"{label}.to")
    subject_prefix = str(raw.get("subject_prefix", "[livetrading]")).strip() or "[livetrading]"
    use_tls = _coerce_bool(raw.get("use_tls"), default=True, label=f"{label}.use_tls")
    if enabled:
        if not smtp_host:
            raise ValueError(f"{label}.smtp_host must not be empty when email notification is enabled")
        if not to_addresses:
            raise ValueError(f"{label}.to must not be empty when email notification is enabled")
        if username is not None and password is None and password_env is None:
            raise ValueError(f"{label}.password or {label}.password_env must be provided when {label}.username is set")
        if from_address is None:
            from_address = username
        if from_address is None:
            raise ValueError(f"{label}.from must not be empty when email notification is enabled")
    return EmailNotificationConfig(
        enabled=enabled,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        username=username,
        password=password,
        password_env=password_env,
        from_address=from_address,
        to_addresses=to_addresses,
        subject_prefix=subject_prefix,
        use_tls=use_tls,
    )


def _parse_notification_config(raw: Mapping[str, Any], *, label: str) -> NotificationConfig:
    _validate_allowed_mapping_keys(raw, label=label, allowed_keys=NOTIFICATION_ALLOWED_KEYS)
    return NotificationConfig(
        email=_parse_email_notification_config(
            _require_mapping(raw.get("email", {}), f"{label}.email"),
            label=f"{label}.email",
        )
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
        strategy_name = str(raw.get("name", "")).strip().lower()
        params = dict(_require_mapping(raw.get("params", {}), f"{label}.params"))
    else:
        strategy_name = str(raw or "").strip().lower()
        params = {}
    if not strategy_name:
        raise ValueError(f"{label}.name must not be empty")
    supported_names = supported_pool_strategy_names()
    if strategy_name not in supported_names:
        supported = ", ".join(sorted(supported_names))
        raise ValueError(f"{label}.name must be one of: {supported}")
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


def _parse_trade_account_config(raw: Mapping[str, Any], *, label: str = "trade_account") -> TradeAccountConfig:
    _validate_allowed_mapping_keys(raw, label=label, allowed_keys=TRADE_ACCOUNT_ALLOWED_KEYS)
    account_id = str(raw.get("account_id", "")).strip()
    if not account_id:
        raise ValueError(f"{label}.account_id must not be empty")
    broker = _parse_trade_broker_config(
        _require_mapping(raw.get("broker", {}), f"{label}.broker"),
        label=f"{label}.broker",
    )
    execution = _parse_execution_config(
        _require_mapping(raw.get("execution", {}), f"{label}.execution"),
        label=f"{label}.execution",
        broker=broker,
    )
    notification = _parse_notification_config(
        _require_mapping(raw.get("notification", {}), f"{label}.notification"),
        label=f"{label}.notification",
    )
    return TradeAccountConfig(account_id=account_id, broker=broker, execution=execution, notification=notification)


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
    using_shared_broker_fallback = (
        shared_broker_raw is not None
        and realtime_broker_raw is shared_broker_raw
        and history_broker_raw is shared_broker_raw
    )
    realtime_broker = _parse_realtime_quote_broker_config(
        _require_mapping(realtime_broker_raw, "realtime_broker"),
        label="realtime_broker",
        allow_cross_endpoint_aliases=using_shared_broker_fallback,
    )
    history_broker = None
    if history_broker_raw is not None:
        history_broker = _parse_history_broker_config(
            _require_mapping(history_broker_raw, "history_broker"),
            label="history_broker",
            allow_cross_endpoint_aliases=using_shared_broker_fallback,
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


def load_trade_account_config_from_text(text: str) -> TradeAccountConfig:
    """把单账户交易配置 JSON 文本解析成 TradeAccountConfig。"""
    raw = json.loads(text)
    payload = _require_mapping(raw, "trade account config")
    _validate_allowed_top_level_keys(payload, label="trade account config", allowed_keys=TRADE_CONFIG_ALLOWED_TOP_LEVEL_KEYS)
    account_raw = payload.get("trade_account")
    return _parse_trade_account_config(
        _require_mapping(account_raw, "trade_account"),
        label="trade_account",
    )


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
        for key in ("type", "host", "port", "data_root", "history_host", "history_port", "kline_day_root")
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
    trade_account_config: TradeAccountConfig,
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
    sole_account = trade_account_config
    if sole_account.execution.order_session != "RTH":
        if sole_account.execution.executor != "mock" and sole_account.broker.type != "futu":
            raise ValueError(
                f"trade account {sole_account.account_id} order_session only supports broker.type=futu"
            )
    if sole_account.execution.executor == "futu_simulate" and sole_account.broker.trade_env != "SIMULATE":
        raise ValueError(
            f"trade account {sole_account.account_id} executor futu_simulate requires broker.trade_env=SIMULATE"
        )
    if sole_account.execution.executor == "notify" and sole_account.broker.type != "mock":
        raise ValueError(
            f"trade account {sole_account.account_id} executor notify requires broker.type=mock"
        )
    if sole_account.broker.type == "mock" and sole_account.execution.executor not in {"mock", "notify"}:
        raise ValueError(
            f"trade account {sole_account.account_id} broker.type=mock only supports execution.executor=mock or notify"
        )
    if sole_account.execution.executor == "futu_real" and sole_account.broker.trade_env != "REAL":
        raise ValueError(
            f"trade account {sole_account.account_id} executor futu_real requires broker.trade_env=REAL"
        )
    final_realtime_broker = replace(
        quote_config.realtime_broker,
        subscribe_extended_time=sole_account.execution.order_session != "RTH",
    )
    return LiveTradingConfig(
        quote=QuoteConfig(
            realtime_broker=final_realtime_broker,
            history_broker=final_history_broker,
            runtime=quote_config.runtime,
            stock_pool=final_stock_pool,
        ),
        trade_account=sole_account,
    )


def load_quote_config(path: Path | str) -> QuoteConfig:
    config_path = Path(path)
    return load_quote_config_from_text(config_path.read_text(encoding="utf-8"))


def load_trade_account_config(path: Path | str) -> TradeAccountConfig:
    config_path = Path(path)
    return load_trade_account_config_from_text(config_path.read_text(encoding="utf-8"))


def load_history_config(path: Path | str) -> HistoryBrokerConfig:
    config_path = Path(path)
    return load_history_config_from_text(config_path.read_text(encoding="utf-8"))


def load_pool_config(path: Path | str) -> StockPoolConfig:
    config_path = Path(path)
    return load_pool_config_from_text(config_path.read_text(encoding="utf-8"))


def load_livetrading_config(
    quote_config_path: Path | str,
    trade_account_path: Path | str,
    history_config_path: Path | str | None = None,
    pool_config_path: Path | str | None = None,
) -> LiveTradingConfig:
    """从 quote / history / pool / trade 配置路径读取并构建完整的 LiveTradingConfig。"""
    return build_livetrading_config(
        load_quote_config(quote_config_path),
        load_trade_account_config(trade_account_path),
        load_history_config(history_config_path) if history_config_path is not None else None,
        load_pool_config(pool_config_path) if pool_config_path is not None else None,
    )
