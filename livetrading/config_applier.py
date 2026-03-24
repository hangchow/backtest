from __future__ import annotations

from dataclasses import dataclass, field
import logging
import threading
from typing import Callable

import pandas as pd

from .account_state import AccountStateStore
from .config import HistoryBrokerConfig, LiveTradingConfig, RealtimeQuoteBrokerConfig, TradeAccountConfig
from .history_providers.base import DailyHistoryProvider
from .pool_strategies import PoolLiveStrategy, build_pool_strategy
from .quote_brokers.base import QuoteBrokerClient, QuoteBrokerEventSink
from .runtime_state import LiveTradingRuntimeState
from .trade_account.base import TradeAccountClient, TradeAccountEventSink


@dataclass(frozen=True)
class ConfigRefreshPlan:
    config_changed: bool
    realtime_reconnect: bool
    history_refresh: bool
    strategy_refresh: bool
    tracked_account_ids: tuple[str, ...] = field(default_factory=tuple)
    warmup_bars: dict[str, int] = field(default_factory=dict)
    new_pool_strategy: PoolLiveStrategy | None = None


class RuntimeConfigApplier:
    """负责把配置 diff 应用成具体的运行时资源与策略上下文。"""

    def __init__(
        self,
        *,
        lock: threading.RLock,
        logger: logging.Logger,
        runtime_state: LiveTradingRuntimeState,
        account_state_store: AccountStateStore,
        quote_broker_factory: Callable[[RealtimeQuoteBrokerConfig, QuoteBrokerEventSink, logging.Logger], QuoteBrokerClient],
        history_provider_factory: Callable[[HistoryBrokerConfig, logging.Logger], DailyHistoryProvider],
        trade_account_factory: Callable[[TradeAccountConfig, TradeAccountEventSink, logging.Logger], TradeAccountClient],
        quote_event_sink: QuoteBrokerEventSink,
        trade_event_sink: TradeAccountEventSink,
    ) -> None:
        self._lock = lock
        self._logger = logger
        self._runtime_state = runtime_state
        self._account_state_store = account_state_store
        self._quote_broker_factory = quote_broker_factory
        self._history_provider_factory = history_provider_factory
        self._trade_account_factory = trade_account_factory
        self._quote_event_sink = quote_event_sink
        self._trade_event_sink = trade_event_sink

    def apply_config(self, config: LiveTradingConfig, *, force_warmup_refresh: bool = False) -> None:
        with self._lock:
            previous_pending_account_log_ids = self._runtime_state.pending_account_log_ids.copy()
            previous_pending_position_log_ids = self._runtime_state.pending_position_log_ids.copy()
            refresh_plan = self._build_refresh_plan(config, force_warmup_refresh=force_warmup_refresh)
            self._logger.setLevel(getattr(logging, config.runtime.log_level, logging.INFO))
            self._runtime_state.config_inflight = config
            try:
                if refresh_plan.config_changed:
                    tracked_account_ids = set(refresh_plan.tracked_account_ids)
                    self._runtime_state.pending_account_log_ids = tracked_account_ids.copy()
                    self._runtime_state.pending_position_log_ids = tracked_account_ids.copy()

                self._apply_realtime_config(config, refresh_plan)
                self._apply_history_provider(config, refresh_plan)
                warmup_histories, unavailable_codes = self._prepare_strategy_context(config, refresh_plan)
                self._apply_trade_account_config(config)
                self._commit_strategy_context(config, refresh_plan, warmup_histories, unavailable_codes)
                self._sync_shadow_state(config)
                self._runtime_state.current_config = config
                self._log_config_applied(config)
            except Exception:
                self._runtime_state.pending_account_log_ids = previous_pending_account_log_ids
                self._runtime_state.pending_position_log_ids = previous_pending_position_log_ids
                raise
            finally:
                self._runtime_state.config_inflight = None

    def stop(self) -> None:
        with self._lock:
            if self._runtime_state.quote_broker is not None:
                self._runtime_state.quote_broker.close()
                self._runtime_state.quote_broker = None
            if self._runtime_state.history_provider is not None:
                self._runtime_state.history_provider.close()
                self._runtime_state.history_provider = None
            for client in self._runtime_state.trade_account_clients.values():
                client.close()
            self._runtime_state.trade_account_clients = {}

    def _build_refresh_plan(self, config: LiveTradingConfig, *, force_warmup_refresh: bool) -> ConfigRefreshPlan:
        current_config = self._runtime_state.current_config
        config_changed = current_config is None or current_config != config
        realtime_reconnect = current_config is None or (
            current_config.realtime_broker.connection_signature() != config.realtime_broker.connection_signature()
        )
        history_refresh = current_config is None or (
            current_config.history_broker.connection_signature() != config.history_broker.connection_signature()
        )
        strategy_refresh = (
            history_refresh
            or current_config is None
            or current_config.stock_pool != config.stock_pool
            or force_warmup_refresh
            or self._runtime_state.history_warmup_pending
        )
        new_pool_strategy = None
        warmup_bars: dict[str, int] = {}
        if strategy_refresh:
            new_pool_strategy = build_pool_strategy(config.stock_pool)
            warmup_bars = {
                code: new_pool_strategy.required_daily_warmup_bars()
                for code in config.stock_pool.codes
            }
        return ConfigRefreshPlan(
            config_changed=config_changed,
            realtime_reconnect=realtime_reconnect,
            history_refresh=history_refresh,
            strategy_refresh=strategy_refresh,
            tracked_account_ids=(config.trade_account.account_id,),
            warmup_bars=warmup_bars,
            new_pool_strategy=new_pool_strategy,
        )

    def _apply_realtime_config(self, config: LiveTradingConfig, refresh_plan: ConfigRefreshPlan) -> None:
        current_config = self._runtime_state.current_config
        if refresh_plan.realtime_reconnect:
            if self._runtime_state.quote_broker is not None:
                self._runtime_state.quote_broker.close()
            self._runtime_state.quote_broker = self._quote_broker_factory(
                config.realtime_broker,
                self._quote_event_sink,
                self._logger,
            )
            self._runtime_state.quote_broker.connect(config.stock_pool.codes)
            return

        if self._runtime_state.quote_broker is not None and (
            current_config is None or current_config.stock_pool.codes != config.stock_pool.codes
        ):
            self._runtime_state.quote_broker.update_symbols(config.stock_pool.codes)

    def _apply_history_provider(self, config: LiveTradingConfig, refresh_plan: ConfigRefreshPlan) -> None:
        if not refresh_plan.history_refresh:
            return
        if self._runtime_state.history_provider is not None:
            self._runtime_state.history_provider.close()
        self._runtime_state.history_provider = self._history_provider_factory(config.history_broker, self._logger)

    def _prepare_strategy_context(
        self,
        config: LiveTradingConfig,
        refresh_plan: ConfigRefreshPlan,
    ) -> tuple[dict[str, pd.DataFrame], tuple[str, ...]]:
        if not refresh_plan.strategy_refresh:
            return {}, ()
        if self._runtime_state.history_provider is None:
            self._runtime_state.history_provider = self._history_provider_factory(config.history_broker, self._logger)
        # 这里把 warm-up 日线一次性读进来。
        # mock_signal 样例里读到的就是 config/livetrading_mock_signal_kline_day 下那组受控夹具。
        warmup_histories = self._runtime_state.history_provider.fetch_daily_histories(
            config.stock_pool.codes,
            refresh_plan.warmup_bars,
        )
        unavailable_codes = tuple(
            code
            for code in config.stock_pool.codes
            if code not in warmup_histories or warmup_histories[code] is None or warmup_histories[code].empty
        )
        return warmup_histories, unavailable_codes

    def _commit_strategy_context(
        self,
        config: LiveTradingConfig,
        refresh_plan: ConfigRefreshPlan,
        warmup_histories: dict[str, pd.DataFrame],
        unavailable_codes: tuple[str, ...],
    ) -> None:
        if not refresh_plan.strategy_refresh:
            return
        if unavailable_codes:
            self._runtime_state.pool_strategy = None
            self._runtime_state.history_warmup_pending = True
            self._runtime_state.warmup_unavailable_codes = unavailable_codes
            self._logger.error(
                "HISTORY_WARMUP_UNAVAILABLE history=%s strategy=%s codes=%s",
                config.history_broker.endpoint_summary(),
                config.stock_pool.strategy.name,
                ",".join(unavailable_codes),
            )
            return

        assert refresh_plan.new_pool_strategy is not None
        # bootstrap 后，状态机会把“warm-up 最后一根日线的 trade_date”记成当前交易日基线。
        # 对 mock_signal 样例来说，这个基线就是 2026-03-12，所以后面一旦收到 2026-03-13 09:30 bar
        # 就会被识别成换日，并吐出截至 2026-03-12 的已完成日线窗口。
        refresh_plan.new_pool_strategy.bootstrap(warmup_histories)
        self._runtime_state.pool_strategy = refresh_plan.new_pool_strategy
        self._runtime_state.history_warmup_pending = False
        self._runtime_state.warmup_unavailable_codes = ()

    def _apply_trade_account_config(self, config: LiveTradingConfig) -> None:
        account = config.trade_account
        current_config = self._runtime_state.current_config
        current_account = current_config.trade_account if current_config is not None else None
        for account_id, client in list(self._runtime_state.trade_account_clients.items()):
            if (
                account_id != account.account_id
                or current_account is None
                or current_account.account_id != account_id
                or current_account.connection_signature() != account.connection_signature()
            ):
                client.close()
                del self._runtime_state.trade_account_clients[account_id]

        reconnect = (
            account.account_id not in self._runtime_state.trade_account_clients
            or current_account is None
            or current_account.connection_signature() != account.connection_signature()
        )
        if reconnect:
            client = self._trade_account_factory(account, self._trade_event_sink, self._logger)
            self._runtime_state.trade_account_clients[account.account_id] = client
            client.connect()

    def _sync_shadow_state(self, config: LiveTradingConfig) -> None:
        active_codes = set(config.all_codes())
        active_account_ids = {config.trade_account.account_id}
        self._runtime_state.latest_quotes = {
            code: quote
            for code, quote in self._runtime_state.latest_quotes.items()
            if code in active_codes
        }
        self._runtime_state.latest_bar_prices = {
            code: price
            for code, price in self._runtime_state.latest_bar_prices.items()
            if code in active_codes
        }
        self._account_state_store.prune(active_account_ids=active_account_ids, active_codes=active_codes)
        account = config.trade_account
        self._account_state_store.sync_active_codes(account.account_id, config.all_codes())
        self._account_state_store.reconcile_from_actual(account.account_id, config.all_codes())

    def _log_config_applied(self, config: LiveTradingConfig) -> None:
        account = config.trade_account
        account_summary = (
            f"{account.account_id}@mock/{account.execution.executor}"
            if account.broker.type == "mock"
            else (
                f"{account.account_id}@{account.broker.host}:{account.broker.port}/"
                f"{account.broker.trade_env}/{account.execution.executor}"
            )
        )
        self._logger.info(
            "CONFIG_APPLIED realtime=%s history=%s strategy=%s codes=%s trade_account=%s",
            config.realtime_broker.endpoint_summary(),
            config.history_broker.endpoint_summary(),
            config.stock_pool.strategy.name,
            ",".join(config.stock_pool.codes),
            account_summary,
        )
