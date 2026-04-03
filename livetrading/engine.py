from __future__ import annotations

from dataclasses import replace
import hashlib
import logging
from pathlib import Path
import threading
from typing import Any, Callable

from .account_state import AccountStateStore
from .broker import create_daily_history_provider, create_quote_broker_client, create_trade_account_client
from .config import (
    HistoryBrokerConfig,
    LiveTradingConfig,
    RealtimeQuoteBrokerConfig,
    TradeAccountConfig,
    build_livetrading_config,
    load_history_config_from_text,
    load_pool_config_from_text,
    load_quote_config_from_text,
    load_trade_account_config_from_text,
)
from .config_applier import RuntimeConfigApplier
from .event_sinks import QuoteBrokerEventSinkAdapter, TradeAccountEventSinkAdapter
from .execution import RebalancePlanner, TradeAccountState
from .history_providers.base import DailyHistoryProvider
from .models import AccountSnapshot, FillEvent, OrderUpdate, PortfolioRebalanceDecision, PositionSnapshot, QuoteUpdate, ScheduledTrigger
from .notifications import send_email_notification
from .portfolio import PortfolioCoordinator
from .quote_brokers.base import QuoteBrokerClient
from .runtime_state import LiveTradingRuntimeState
from .trade_account.base import TradeAccountClient


class ConfigFileWatcher:
    def __init__(self, path: Path | str, loader: Callable[[str], Any]) -> None:
        self.path = Path(path)
        self._loader = loader
        self._digest: str | None = None

    def load(self) -> Any:
        """读取并解析整份配置文件，同时记录当前内容摘要。"""
        payload = self.path.read_bytes()
        config = self._loader(payload.decode("utf-8"))
        self._digest = hashlib.sha256(payload).hexdigest()
        return config

    def maybe_reload(self) -> Any | None:
        """仅在文件内容摘要变化时重新解析配置。"""
        payload = self.path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest == self._digest:
            return None
        config = self._loader(payload.decode("utf-8"))
        self._digest = digest
        return config


class LiveTradingEngine:
    """实盘运行主控器，负责装配协作者并维护主循环。"""

    def __init__(
        self,
        quote_config_path: Path | str,
        trade_config_path: Path | str,
        history_config_path: Path | str | None = None,
        pool_config_path: Path | str | None = None,
        *,
        quote_broker_factory: Callable[[RealtimeQuoteBrokerConfig, object, logging.Logger], QuoteBrokerClient] = create_quote_broker_client,
        history_provider_factory: Callable[[HistoryBrokerConfig, logging.Logger], DailyHistoryProvider] = create_daily_history_provider,
        trade_account_factory: Callable[[TradeAccountConfig, object, logging.Logger], TradeAccountClient] = create_trade_account_client,
        email_sender: Callable[..., None] | None = None,
        logger: logging.Logger | None = None,
        schedule_trigger_time: str | None = None,
    ) -> None:
        self._quote_config_path = Path(quote_config_path)
        self._trade_config_path = Path(trade_config_path)
        self._history_config_path = Path(history_config_path) if history_config_path is not None else None
        self._pool_config_path = Path(pool_config_path) if pool_config_path is not None else None
        self._schedule_trigger_time = schedule_trigger_time
        self._logger = logger or logging.getLogger("livetrading")
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

        self._runtime_state = LiveTradingRuntimeState()
        self._account_state_store = AccountStateStore(self._logger)
        self._account_states: dict[str, TradeAccountState] = self._account_state_store.states
        self._planner = RebalancePlanner(self._logger, self._account_state_store)
        self._portfolio_coordinator = PortfolioCoordinator(
            lock=self._lock,
            logger=self._logger,
            runtime_state=self._runtime_state,
            state_store=self._account_state_store,
            planner=self._planner,
            email_sender=email_sender or send_email_notification,
        )
        self._quote_event_sink = QuoteBrokerEventSinkAdapter(
            lock=self._lock,
            logger=self._logger,
            runtime_state=self._runtime_state,
            portfolio_coordinator=self._portfolio_coordinator,
        )
        self._trade_event_sink = TradeAccountEventSinkAdapter(
            lock=self._lock,
            logger=self._logger,
            runtime_state=self._runtime_state,
            account_state_store=self._account_state_store,
        )
        self._config_applier = RuntimeConfigApplier(
            lock=self._lock,
            logger=self._logger,
            runtime_state=self._runtime_state,
            account_state_store=self._account_state_store,
            quote_broker_factory=quote_broker_factory,
            history_provider_factory=history_provider_factory,
            trade_account_factory=trade_account_factory,
            quote_event_sink=self._quote_event_sink,
            trade_event_sink=self._trade_event_sink,
        )

    @property
    def _pool_strategy(self):
        return self._runtime_state.pool_strategy

    @property
    def _history_warmup_pending(self) -> bool:
        return self._runtime_state.history_warmup_pending

    @property
    def _warmup_unavailable_codes(self) -> tuple[str, ...]:
        return self._runtime_state.warmup_unavailable_codes

    def apply_config(self, config: LiveTradingConfig, *, force_warmup_refresh: bool = False) -> None:
        self._config_applier.apply_config(
            self._apply_runtime_overrides(config),
            force_warmup_refresh=force_warmup_refresh,
        )

    def run(self) -> None:
        """启动实盘引擎主循环，负责首次加载配置和后续热更新。"""
        quote_watcher = ConfigFileWatcher(self._quote_config_path, load_quote_config_from_text)
        trade_watcher = ConfigFileWatcher(self._trade_config_path, load_trade_account_config_from_text)
        history_watcher = (
            ConfigFileWatcher(self._history_config_path, load_history_config_from_text)
            if self._history_config_path is not None
            else None
        )
        pool_watcher = (
            ConfigFileWatcher(self._pool_config_path, load_pool_config_from_text)
            if self._pool_config_path is not None
            else None
        )
        quote_config = quote_watcher.load()
        trade_config = trade_watcher.load()
        history_config = history_watcher.load() if history_watcher is not None else None
        pool_config = pool_watcher.load() if pool_watcher is not None else None
        self.apply_config(build_livetrading_config(quote_config, trade_config, history_config, pool_config))

        while not self._stop_event.is_set():
            timeout = self._current_reload_interval()
            if self._stop_event.wait(timeout):
                break
            try:
                refreshed_quote = quote_watcher.maybe_reload()
                refreshed_trade = trade_watcher.maybe_reload()
                refreshed_history = history_watcher.maybe_reload() if history_watcher is not None else None
                refreshed_pool = pool_watcher.maybe_reload() if pool_watcher is not None else None
            except Exception as exc:
                self._logger.exception(
                    "CONFIG_RELOAD_FAILED quote_path=%s history_path=%s pool_path=%s trade_path=%s error=%s",
                    self._quote_config_path,
                    self._history_config_path,
                    self._pool_config_path,
                    self._trade_config_path,
                    exc,
                )
                continue
            if refreshed_quote is not None:
                quote_config = refreshed_quote
                self._logger.info("CONFIG_CHANGED path=%s", self._quote_config_path)
            if refreshed_history is not None:
                history_config = refreshed_history
                self._logger.info("CONFIG_CHANGED path=%s", self._history_config_path)
            if refreshed_pool is not None:
                pool_config = refreshed_pool
                self._logger.info("CONFIG_CHANGED path=%s", self._pool_config_path)
            if refreshed_trade is not None:
                trade_config = refreshed_trade
                self._logger.info("CONFIG_CHANGED path=%s", self._trade_config_path)
            retry_warmup = self._history_warmup_retry_pending()
            if refreshed_quote is not None or refreshed_history is not None or refreshed_pool is not None or refreshed_trade is not None or retry_warmup:
                if retry_warmup and refreshed_quote is None and refreshed_trade is None:
                    self._logger.error(
                        "HISTORY_WARMUP_RETRY_PENDING history=%s codes=%s",
                        self._runtime_state.current_config.history_broker.endpoint_summary()
                        if self._runtime_state.current_config is not None
                        else "N/A",
                        ",".join(self._runtime_state.warmup_unavailable_codes),
                    )
                try:
                    self.apply_config(
                        build_livetrading_config(quote_config, trade_config, history_config, pool_config),
                        force_warmup_refresh=retry_warmup,
                    )
                except Exception as exc:
                    self._logger.exception(
                        "CONFIG_APPLY_FAILED quote_path=%s history_path=%s pool_path=%s trade_path=%s error=%s",
                        self._quote_config_path,
                        self._history_config_path,
                        self._pool_config_path,
                        self._trade_config_path,
                        exc,
                    )

    def stop(self) -> None:
        self._stop_event.set()
        self._config_applier.stop()

    def on_quote(self, update: QuoteUpdate) -> None:
        self._quote_event_sink.on_quote(update)

    def on_schedule(self, trigger: ScheduledTrigger) -> None:
        self._quote_event_sink.on_schedule(trigger)

    def on_bar(self, code: str, bar: pd.Series | dict[str, object]) -> None:
        self._quote_event_sink.on_bar(code, bar)

    def on_account(self, account_id: str, snapshot: AccountSnapshot) -> None:
        self._trade_event_sink.on_account(account_id, snapshot)

    def on_positions(self, account_id: str, positions: dict[str, PositionSnapshot]) -> None:
        self._trade_event_sink.on_positions(account_id, positions)

    def on_broker_message(self, level: int, message: str) -> None:
        self._logger.log(level, message)

    def on_order_update(self, account_id: str, update: OrderUpdate) -> None:
        self._trade_event_sink.on_order_update(account_id, update)

    def on_fill(self, account_id: str, fill: FillEvent) -> None:
        self._trade_event_sink.on_fill(account_id, fill)

    def _apply_runtime_overrides(self, config: LiveTradingConfig) -> LiveTradingConfig:
        if self._schedule_trigger_time is None:
            return config
        if config.realtime_broker.type != "schedule_us":
            raise ValueError("--schedule-trigger-time requires realtime_broker.type=schedule_us")
        return replace(
            config,
            quote=replace(
                config.quote,
                realtime_broker=replace(config.realtime_broker, trigger_time=self._schedule_trigger_time),
            ),
        )

    def _current_reload_interval(self) -> float:
        with self._lock:
            if self._runtime_state.current_config is None:
                return 10.0
            return self._runtime_state.current_config.runtime.config_reload_interval_seconds

    def _history_warmup_retry_pending(self) -> bool:
        with self._lock:
            config = self._runtime_state.current_config
            if config is None:
                return False
            if config.trade_account.execution.executor == "notify" and config.realtime_broker.type == "schedule_us":
                return False
            return self._runtime_state.history_warmup_pending

    def _execute_portfolio_rebalance(self, decision: PortfolioRebalanceDecision) -> None:
        self._portfolio_coordinator.execute_portfolio_rebalance(decision)

    def _execute_portfolio_rebalance_dry_run(self, decision: PortfolioRebalanceDecision) -> None:
        self._portfolio_coordinator.execute_portfolio_rebalance(decision)

    def _callback_config(self) -> LiveTradingConfig | None:
        return self._runtime_state.callback_config()
