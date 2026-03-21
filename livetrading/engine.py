from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import threading
from typing import Any, Callable

import pandas as pd

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
    load_trade_accounts_config_from_text,
)
from .execution import RebalancePlanner, TradeAccountState, create_order_executor
from .history_providers.base import DailyHistoryProvider
from .models import AccountSnapshot, FillEvent, OrderUpdate, PortfolioRebalanceDecision, PositionSnapshot, QuoteUpdate
from .pool_strategies import build_pool_strategy
from .quote_brokers.base import QuoteBrokerClient
from .trade_accounts.base import TradeAccountClient


class ConfigFileWatcher:
    def __init__(self, path: Path | str, loader: Callable[[str], Any]) -> None:
        self.path = Path(path)
        self._loader = loader
        self._digest: str | None = None

    def load(self) -> Any:
        """读取配置文件内容，解析并记录当前文件摘要。"""
        payload = self.path.read_bytes()
        config = self._loader(payload.decode("utf-8"))
        self._digest = hashlib.sha256(payload).hexdigest()
        return config

    def maybe_reload(self) -> Any | None:
        """若文件摘要变化则重新解析配置，否则返回 None。"""
        payload = self.path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest == self._digest:
            return None
        config = self._loader(payload.decode("utf-8"))
        self._digest = digest
        return config

class LiveTradingEngine:
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
        logger: logging.Logger | None = None,
    ) -> None:
        self._quote_config_path = Path(quote_config_path)
        self._trade_config_path = Path(trade_config_path)
        self._history_config_path = Path(history_config_path) if history_config_path is not None else None
        self._pool_config_path = Path(pool_config_path) if pool_config_path is not None else None
        self._quote_broker_factory = quote_broker_factory
        self._history_provider_factory = history_provider_factory
        self._trade_account_factory = trade_account_factory
        self._logger = logger or logging.getLogger("livetrading")
        self._current_config: LiveTradingConfig | None = None
        self._config_inflight: LiveTradingConfig | None = None
        self._quote_broker: QuoteBrokerClient | None = None
        self._history_provider: DailyHistoryProvider | None = None
        self._trade_account_clients: dict[str, TradeAccountClient] = {}
        self._pool_strategy = None
        self._latest_quotes: dict[str, QuoteUpdate] = {}
        self._latest_bar_prices: dict[str, float] = {}
        self._account_state_store = AccountStateStore(self._logger)
        self._account_states: dict[str, TradeAccountState] = self._account_state_store.states
        self._planner = RebalancePlanner(self._logger, self._account_state_store)
        self._history_warmup_pending = False
        self._warmup_unavailable_codes: tuple[str, ...] = ()
        self._pending_account_log_ids: set[str] = set()
        self._pending_position_log_ids: set[str] = set()
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

    def apply_config(self, config: LiveTradingConfig, *, force_warmup_refresh: bool = False) -> None:
        """按新配置重建依赖、执行 warm-up，并同步影子状态。"""
        with self._lock:
            previous_pending_account_log_ids = self._pending_account_log_ids.copy()
            previous_pending_position_log_ids = self._pending_position_log_ids.copy()
            config_changed = self._current_config is None or self._current_config != config
            self._logger.setLevel(getattr(logging, config.runtime.log_level, logging.INFO))
            realtime_reconnect = self._current_config is None or (
                self._current_config.realtime_broker.connection_signature() != config.realtime_broker.connection_signature()
            )
            history_refresh = self._current_config is None or (
                self._current_config.history_broker.connection_signature() != config.history_broker.connection_signature()
            )
            strategy_refresh = (
                history_refresh
                or self._current_config is None
                or self._current_config.stock_pool != config.stock_pool
                or force_warmup_refresh
                or self._history_warmup_pending
            )
            warmup_histories: dict[str, pd.DataFrame] = {}
            warmup_bars: dict[str, int] = {}
            unavailable_codes: tuple[str, ...] = ()
            new_pool_strategy = self._pool_strategy
            if strategy_refresh:
                new_pool_strategy = build_pool_strategy(config.stock_pool)
                warmup_bars = {code: new_pool_strategy.required_daily_warmup_bars() for code in config.stock_pool.codes}
            self._config_inflight = config
            try:
                if config_changed:
                    tracked_account_ids = set(config.trade_account_map())
                    self._pending_account_log_ids = tracked_account_ids.copy()
                    self._pending_position_log_ids = tracked_account_ids.copy()

                if realtime_reconnect:
                    if self._quote_broker is not None:
                        self._quote_broker.close()
                    self._quote_broker = self._quote_broker_factory(config.realtime_broker, self, self._logger)
                    self._quote_broker.connect(config.stock_pool.codes)
                elif self._quote_broker is not None and (
                    self._current_config is None or self._current_config.stock_pool.codes != config.stock_pool.codes
                ):
                    self._quote_broker.update_symbols(config.stock_pool.codes)

                if history_refresh:
                    if self._history_provider is not None:
                        self._history_provider.close()
                    self._history_provider = self._history_provider_factory(config.history_broker, self._logger)

                if strategy_refresh:
                    if self._history_provider is None:
                        self._history_provider = self._history_provider_factory(config.history_broker, self._logger)
                    warmup_histories = self._history_provider.fetch_daily_histories(config.stock_pool.codes, warmup_bars)
                    unavailable_codes = self._unavailable_warmup_codes(config.stock_pool.codes, warmup_histories)

                self._apply_trade_accounts_config(config)

                if strategy_refresh:
                    if unavailable_codes:
                        self._pool_strategy = None
                        self._history_warmup_pending = True
                        self._warmup_unavailable_codes = unavailable_codes
                        self._logger.error(
                            "HISTORY_WARMUP_UNAVAILABLE history=%s strategy=%s codes=%s",
                            config.history_broker.endpoint_summary(),
                            config.stock_pool.strategy.name,
                            ",".join(unavailable_codes),
                        )
                    else:
                        self._pool_strategy = new_pool_strategy
                        self._pool_strategy.bootstrap(warmup_histories)
                        self._history_warmup_pending = False
                        self._warmup_unavailable_codes = ()

                self._sync_shadow_state(config)
                self._current_config = config
                accounts_summary = ",".join(
                    (
                        f"{account.account_id}@mock/{account.execution.executor}"
                        if account.broker.type == "mock"
                        else (
                            f"{account.account_id}@{account.broker.host}:{account.broker.port}/"
                            f"{account.broker.trade_env}/{account.execution.executor}"
                        )
                    )
                    for account in config.trade_accounts
                )
                self._logger.info(
                    "CONFIG_APPLIED realtime=%s history=%s strategy=%s codes=%s trade_accounts=%s",
                    config.realtime_broker.endpoint_summary(),
                    config.history_broker.endpoint_summary(),
                    config.stock_pool.strategy.name,
                    ",".join(config.stock_pool.codes),
                    accounts_summary,
                )
            except Exception:
                self._pending_account_log_ids = previous_pending_account_log_ids
                self._pending_position_log_ids = previous_pending_position_log_ids
                raise
            finally:
                self._config_inflight = None

    def run(self) -> None:
        """启动配置加载与热更新主循环。"""
        quote_watcher = ConfigFileWatcher(self._quote_config_path, load_quote_config_from_text)
        trade_watcher = ConfigFileWatcher(self._trade_config_path, load_trade_accounts_config_from_text)
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
                        self._current_config.history_broker.endpoint_summary() if self._current_config is not None else "N/A",
                        ",".join(self._warmup_unavailable_codes),
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
        """停止 quote/history/trade 侧后台资源。"""
        self._stop_event.set()
        with self._lock:
            if self._quote_broker is not None:
                self._quote_broker.close()
                self._quote_broker = None
            if self._history_provider is not None:
                self._history_provider.close()
                self._history_provider = None
            for client in self._trade_account_clients.values():
                client.close()
            self._trade_account_clients = {}

    def on_quote(self, update: QuoteUpdate) -> None:
        """接收实时 quote 事件，更新最新参考价缓存。"""
        with self._lock:
            self._latest_quotes[update.code] = update
            runtime = self._current_config.runtime if self._current_config is not None else None
        if runtime is not None and runtime.log_price_updates:
            self._logger.info(
                "QUOTE code=%s time=%s last=%.4f volume=%s turnover=%s",
                update.code,
                update.timestamp,
                update.last_price,
                update.volume,
                update.turnover,
            )

    def on_bar(self, code: str, bar: pd.Series | dict[str, object]) -> None:
        """接收分钟 bar，更新价格缓存并驱动策略判断是否调仓。"""
        bar_row = pd.Series(bar)
        with self._lock:
            self._latest_bar_prices[code] = float(bar_row["close"])
            pool_strategy = self._pool_strategy
        if pool_strategy is None:
            return

        decision = pool_strategy.on_bar(code, bar_row)
        if decision is not None:
            self._execute_portfolio_rebalance(decision)

    def on_account(self, account_id: str, snapshot: AccountSnapshot) -> None:
        """同步账户资金快照，并在首次可用时初始化 shadow_cash。"""
        with self._lock:
            config = self._callback_config()
            if config is None or account_id not in config.trade_account_map():
                return
            state = self._account_state_store.upsert_actual_account(account_id, snapshot)
            self._account_state_store.sync_active_codes(account_id, config.all_codes())
            self._account_state_store.reconcile_from_actual(account_id, config.all_codes())
            runtime = config.runtime
            should_log = runtime.log_account_updates and account_id in self._pending_account_log_ids
            if should_log:
                self._pending_account_log_ids.discard(account_id)
        if should_log:
            self._logger.info(
                "ACCOUNT account_id=%s total_assets=%s cash=%s available_funds=%s buying_power=%s currency=%s",
                account_id,
                snapshot.total_assets,
                snapshot.cash,
                snapshot.available_funds,
                snapshot.buying_power,
                snapshot.currency,
            )

    def on_positions(self, account_id: str, positions: dict[str, PositionSnapshot]) -> None:
        """同步实际持仓，并补齐股票池对应的 shadow_positions。"""
        with self._lock:
            config = self._callback_config()
            if config is None or account_id not in config.trade_account_map():
                return
            active_codes = config.all_codes()
            state = self._account_state_store.upsert_actual_positions(account_id, positions)
            self._account_state_store.sync_active_codes(account_id, active_codes)
            self._account_state_store.reconcile_from_actual(account_id, active_codes)
            runtime = config.runtime
            should_log = runtime.log_position_updates and account_id in self._pending_position_log_ids
            if should_log:
                self._pending_position_log_ids.discard(account_id)

        if should_log:
            summary = [
                f"{code}:actual_qty={positions.get(code).qty if code in positions else 0},shadow_qty={state.shadow_positions.get(code, 0)}"
                for code in sorted(active_codes)
            ]
            self._logger.info("POSITIONS account_id=%s %s", account_id, " | ".join(summary))

    def on_broker_message(self, level: int, message: str) -> None:
        """统一转发 broker 层日志到引擎 logger。"""
        self._logger.log(level, message)

    def on_order_update(self, account_id: str, update: OrderUpdate) -> None:
        """接收订单状态更新，并推进 pending / expected 状态。"""
        with self._lock:
            config = self._callback_config()
            if config is None:
                return
            trade_account_map = config.trade_account_map()
            account = trade_account_map.get(account_id)
            if account is None:
                return
            self._account_state_store.apply_order_update(account, update)
        self._logger.info(
            "ORDER_UPDATE account_id=%s broker_order_id=%s code=%s status=%s dealt_qty=%s avg_price=%s side=%s",
            account_id,
            update.broker_order_id,
            update.code,
            update.status,
            update.dealt_qty,
            update.avg_price,
            update.side,
        )

    def on_fill(self, account_id: str, fill: FillEvent) -> None:
        """接收成交回报，并保留后续扩展 expected / reconcile 的统一入口。"""
        with self._lock:
            config = self._callback_config()
            if config is None:
                return
            trade_account_map = config.trade_account_map()
            account = trade_account_map.get(account_id)
            if account is None:
                return
            self._account_state_store.apply_fill(account, fill)
        self._logger.info(
            "FILL account_id=%s broker_order_id=%s code=%s qty=%s price=%s side=%s",
            account_id,
            fill.broker_order_id,
            fill.code,
            fill.fill_qty,
            fill.fill_price,
            fill.side,
        )

    def _current_reload_interval(self) -> float:
        with self._lock:
            if self._current_config is None:
                return 10.0
            return self._current_config.runtime.config_reload_interval_seconds

    def _history_warmup_retry_pending(self) -> bool:
        with self._lock:
            return self._history_warmup_pending and self._current_config is not None

    def _unavailable_warmup_codes(
        self,
        codes: tuple[str, ...],
        histories: dict[str, pd.DataFrame],
    ) -> tuple[str, ...]:
        unavailable = [
            code
            for code in codes
            if code not in histories or histories[code] is None or histories[code].empty
        ]
        return tuple(unavailable)

    def _apply_trade_accounts_config(self, config: LiveTradingConfig) -> None:
        """按配置增删或重连 trade account client。"""
        current_accounts = self._current_config.trade_account_map() if self._current_config is not None else {}
        target_accounts = config.trade_account_map()

        for account_id, client in list(self._trade_account_clients.items()):
            current_account = current_accounts.get(account_id)
            target_account = target_accounts.get(account_id)
            if (
                target_account is None
                or current_account is None
                or current_account.connection_signature() != target_account.connection_signature()
            ):
                client.close()
                del self._trade_account_clients[account_id]

        for account in config.trade_accounts:
            current_account = current_accounts.get(account.account_id)
            reconnect = (
                account.account_id not in self._trade_account_clients
                or current_account is None
                or current_account.connection_signature() != account.connection_signature()
            )
            if reconnect:
                client = self._trade_account_factory(account, self, self._logger)
                self._trade_account_clients[account.account_id] = client
                client.connect()

    def _sync_shadow_state(self, config: LiveTradingConfig) -> None:
        """裁剪过期代码/账户，并补齐 shadow / expected 的初值。"""
        active_codes = set(config.all_codes())
        active_account_ids = set(config.trade_account_map())
        self._latest_quotes = {code: quote for code, quote in self._latest_quotes.items() if code in active_codes}
        self._latest_bar_prices = {code: price for code, price in self._latest_bar_prices.items() if code in active_codes}
        self._account_state_store.prune(active_account_ids=active_account_ids, active_codes=active_codes)
        for account in config.trade_accounts:
            self._account_state_store.sync_active_codes(account.account_id, config.all_codes())
            self._account_state_store.reconcile_from_actual(account.account_id, config.all_codes())

    def _resolve_reference_price(self, code: str) -> float | None:
        if code in self._latest_quotes:
            return self._latest_quotes[code].last_price
        if code in self._latest_bar_prices:
            return self._latest_bar_prices[code]
        return None

    def _execute_portfolio_rebalance(self, decision: PortfolioRebalanceDecision) -> None:
        """收集参考价，按账户生成调仓计划并选择对应执行器。"""
        with self._lock:
            config = self._current_config
            if config is None:
                return
            prices: dict[str, float] = {}
            for code in config.all_codes():
                price = self._resolve_reference_price(code)
                if price is not None and price > 0:
                    prices[code] = price
            pool_codes = config.stock_pool.codes

            for account in config.trade_accounts:
                state = self._account_state_store.ensure(account.account_id)
                client = self._trade_account_clients.get(account.account_id)
                plan = self._planner.build_account_plan(
                    decision=decision,
                    account=account,
                    state=state,
                    pool_codes=pool_codes,
                    prices=prices,
                )
                if plan is None:
                    continue
                executor = create_order_executor(
                    account,
                    client=client,
                    logger=self._logger,
                    state_store=self._account_state_store,
                )
                try:
                    # 调仓执行期间保持 engine 锁，避免账户轮询 / 订单回报在 mark_submitted 之前抢先修改同一份状态。
                    executor.execute_plan(plan=plan, state=state)
                except Exception as exc:
                    # 单个账户的执行异常不应该把同一轮其他账户的调仓也一起中断。
                    self._logger.exception(
                        "ORDER_EXECUTION_FAILED account_id=%s executor=%s signal_time=%s error=%s",
                        account.account_id,
                        account.execution.executor,
                        decision.signal_time,
                        exc,
                    )

    def _execute_portfolio_rebalance_dry_run(self, decision: PortfolioRebalanceDecision) -> None:
        """兼容旧调用名，内部已改成按 execution.executor 选择执行器。"""
        self._execute_portfolio_rebalance(decision)

    def _callback_config(self) -> LiveTradingConfig | None:
        """配置应用过程中，回调优先使用 inflight 配置，避免 connect() 期间的首批事件被旧配置丢掉。"""
        return self._config_inflight or self._current_config
