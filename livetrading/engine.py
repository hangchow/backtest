from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import logging
from pathlib import Path
import threading
from typing import Any, Callable

import pandas as pd

from strategy.fees import compute_order_fees
from strategy.rebalance import (
    RebalancePolicy,
    build_desired_shares,
    compute_affordable_qty_with_fee,
    compute_portfolio_value,
)
from .broker import (
    DailyHistoryProvider,
    QuoteBrokerClient,
    TradeAccountClient,
    create_daily_history_provider,
    create_quote_broker_client,
    create_trade_account_client,
)
from .config import (
    HistoryBrokerConfig,
    LiveTradingConfig,
    RealtimeQuoteBrokerConfig,
    QuoteConfig,
    TradeAccountConfig,
    TradeAccountsConfig,
    build_livetrading_config,
    load_quote_config_from_text,
    load_trade_accounts_config_from_text,
)
from .models import AccountSnapshot, PortfolioRebalanceDecision, PositionSnapshot, QuoteUpdate
from .pool_strategies import build_pool_strategy


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


@dataclass
class TradeAccountState:
    actual_account: AccountSnapshot | None = None
    actual_positions: dict[str, PositionSnapshot] = field(default_factory=dict)
    shadow_cash: float | None = None
    shadow_positions: dict[str, int] = field(default_factory=dict)


class LiveTradingEngine:
    def __init__(
        self,
        quote_config_path: Path | str,
        trade_config_path: Path | str,
        *,
        quote_broker_factory: Callable[[RealtimeQuoteBrokerConfig, object, logging.Logger], QuoteBrokerClient] = create_quote_broker_client,
        history_provider_factory: Callable[[HistoryBrokerConfig, logging.Logger], DailyHistoryProvider] = create_daily_history_provider,
        trade_account_factory: Callable[[TradeAccountConfig, object, logging.Logger], TradeAccountClient] = create_trade_account_client,
        logger: logging.Logger | None = None,
    ) -> None:
        self._quote_config_path = Path(quote_config_path)
        self._trade_config_path = Path(trade_config_path)
        self._quote_broker_factory = quote_broker_factory
        self._history_provider_factory = history_provider_factory
        self._trade_account_factory = trade_account_factory
        self._logger = logger or logging.getLogger("livetrading")
        self._current_config: LiveTradingConfig | None = None
        self._quote_broker: QuoteBrokerClient | None = None
        self._history_provider: DailyHistoryProvider | None = None
        self._trade_account_clients: dict[str, TradeAccountClient] = {}
        self._pool_strategy = None
        self._latest_quotes: dict[str, QuoteUpdate] = {}
        self._latest_bar_prices: dict[str, float] = {}
        self._account_states: dict[str, TradeAccountState] = {}
        self._history_warmup_pending = False
        self._warmup_unavailable_codes: tuple[str, ...] = ()
        self._pending_account_log_ids: set[str] = set()
        self._pending_position_log_ids: set[str] = set()
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

    def apply_config(self, config: LiveTradingConfig, *, force_warmup_refresh: bool = False) -> None:
        """按新配置重建依赖、执行 warm-up，并同步影子状态。"""
        with self._lock:
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
            if config_changed:
                tracked_account_ids = set(config.trade_account_map())
                self._pending_account_log_ids = tracked_account_ids.copy()
                self._pending_position_log_ids = tracked_account_ids.copy()
            accounts_summary = ",".join(
                f"{account.account_id}@{account.broker.host}:{account.broker.port}/{account.broker.trade_env}"
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

    def run(self) -> None:
        """启动配置加载与热更新主循环。"""
        quote_watcher = ConfigFileWatcher(self._quote_config_path, load_quote_config_from_text)
        trade_watcher = ConfigFileWatcher(self._trade_config_path, load_trade_accounts_config_from_text)
        quote_config = quote_watcher.load()
        trade_config = trade_watcher.load()
        self.apply_config(build_livetrading_config(quote_config, trade_config))

        while not self._stop_event.is_set():
            timeout = self._current_reload_interval()
            if self._stop_event.wait(timeout):
                break
            try:
                refreshed_quote = quote_watcher.maybe_reload()
                refreshed_trade = trade_watcher.maybe_reload()
            except Exception as exc:
                self._logger.exception(
                    "CONFIG_RELOAD_FAILED quote_path=%s trade_path=%s error=%s",
                    self._quote_config_path,
                    self._trade_config_path,
                    exc,
                )
                continue
            if refreshed_quote is not None:
                quote_config = refreshed_quote
                self._logger.info("CONFIG_CHANGED path=%s", self._quote_config_path)
            if refreshed_trade is not None:
                trade_config = refreshed_trade
                self._logger.info("CONFIG_CHANGED path=%s", self._trade_config_path)
            retry_warmup = self._history_warmup_retry_pending()
            if refreshed_quote is not None or refreshed_trade is not None or retry_warmup:
                if retry_warmup and refreshed_quote is None and refreshed_trade is None:
                    self._logger.error(
                        "HISTORY_WARMUP_RETRY_PENDING history=%s codes=%s",
                        self._current_config.history_broker.endpoint_summary() if self._current_config is not None else "N/A",
                        ",".join(self._warmup_unavailable_codes),
                    )
                self.apply_config(
                    build_livetrading_config(quote_config, trade_config),
                    force_warmup_refresh=retry_warmup,
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
            self._execute_portfolio_rebalance_dry_run(decision)

    def on_account(self, account_id: str, snapshot: AccountSnapshot) -> None:
        """同步账户资金快照，并在首次可用时初始化 shadow_cash。"""
        with self._lock:
            if self._current_config is None or account_id not in self._current_config.trade_account_map():
                return
            state = self._account_states.setdefault(account_id, TradeAccountState())
            state.actual_account = snapshot
            if state.shadow_cash is None and snapshot.available_funds is not None:
                state.shadow_cash = snapshot.available_funds
            runtime = self._current_config.runtime
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
            if self._current_config is None or account_id not in self._current_config.trade_account_map():
                return
            state = self._account_states.setdefault(account_id, TradeAccountState())
            state.actual_positions = positions
            active_codes = self._current_config.all_codes()
            for code in active_codes:
                state.shadow_positions.setdefault(code, positions.get(code).qty if code in positions else 0)
            runtime = self._current_config.runtime
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
        """裁剪过期代码/账户，并补齐影子仓位与影子现金初值。"""
        active_codes = set(config.all_codes())
        active_account_ids = set(config.trade_account_map())
        self._latest_quotes = {code: quote for code, quote in self._latest_quotes.items() if code in active_codes}
        self._latest_bar_prices = {code: price for code, price in self._latest_bar_prices.items() if code in active_codes}
        self._account_states = {
            account_id: state
            for account_id, state in self._account_states.items()
            if account_id in active_account_ids
        }
        for account in config.trade_accounts:
            state = self._account_states.setdefault(account.account_id, TradeAccountState())
            state.shadow_positions = {
                code: qty for code, qty in state.shadow_positions.items() if code in active_codes
            }
            for code in active_codes:
                if code not in state.shadow_positions:
                    state.shadow_positions[code] = state.actual_positions.get(code).qty if code in state.actual_positions else 0
            if state.shadow_cash is None and state.actual_account is not None and state.actual_account.available_funds is not None:
                state.shadow_cash = state.actual_account.available_funds

    def _resolve_reference_price(self, code: str) -> float | None:
        if code in self._latest_quotes:
            return self._latest_quotes[code].last_price
        if code in self._latest_bar_prices:
            return self._latest_bar_prices[code]
        return None

    def _execute_portfolio_rebalance_dry_run(self, decision: PortfolioRebalanceDecision) -> None:
        """对每个交易账户执行一轮组合级 dry-run 调仓。"""
        with self._lock:
            config = self._current_config
            if config is None:
                return
            prices: dict[str, float] = {}
            for code in config.all_codes():
                price = self._resolve_reference_price(code)
                if price is not None and price > 0:
                    prices[code] = price

            for account in config.trade_accounts:
                state = self._account_states.setdefault(account.account_id, TradeAccountState())
                self._execute_account_rebalance_dry_run(
                    decision=decision,
                    account=account,
                    state=state,
                    pool_codes=config.stock_pool.codes,
                    prices=prices,
                )

    def _execute_account_rebalance_dry_run(
        self,
        *,
        decision: PortfolioRebalanceDecision,
        account: TradeAccountConfig,
        state: TradeAccountState,
        pool_codes: tuple[str, ...],
        prices: dict[str, float],
    ) -> None:
        """按目标权重先卖后买，更新单账户 shadow 状态并输出日志。"""
        active_codes = sorted(set(pool_codes) | set(state.shadow_positions))
        portfolio_value = compute_portfolio_value(
            cash=float(state.shadow_cash or 0.0),
            positions=state.shadow_positions,
            prices=prices,
        )
        if portfolio_value <= 0:
            self._logger.warning("REBALANCE_SKIPPED account_id=%s reason=no_portfolio_value", account.account_id)
            return

        rebalance_policy = RebalancePolicy(band_pct=float(decision.metadata.get("rebalance_band_pct", 0.0)))
        desired_shares = build_desired_shares(
            active_codes=active_codes,
            current_positions=state.shadow_positions,
            target_weights=decision.target_weights,
            prices=prices,
            portfolio_value=portfolio_value,
            policy=rebalance_policy,
            tradable_codes=prices.keys(),
        )

        self._logger.info(
            "DRY_RUN_REBALANCE account_id=%s signal_time=%s reason=%s target_weights=%s",
            account.account_id,
            decision.signal_time,
            decision.reason,
            decision.target_weights,
        )

        for code in active_codes:
            current_qty = int(state.shadow_positions.get(code, 0))
            desired_qty = int(desired_shares.get(code, current_qty))
            price = prices.get(code)
            if price is None or current_qty <= desired_qty:
                continue
            sell_qty = current_qty - desired_qty
            fee_total, fee_breakdown = compute_order_fees(
                fee_account=account.broker.fee_account,
                market=account.broker.market,
                side="sell",
                price=price,
                shares=sell_qty,
                security_type=account.broker.security_type,
            )
            state.shadow_cash = float(state.shadow_cash or 0.0) + sell_qty * price - fee_total
            state.shadow_positions[code] = desired_qty
            command = (
                f"place_order(price={price:.4f}, qty={sell_qty}, code='{code}', "
                f"trd_side='SELL', order_type='NORMAL', trd_env='{account.broker.trade_env}', "
                f"acc_index={account.broker.account_index})"
            )
            self._logger.info(
                "DRY_RUN_ORDER account_id=%s action=SELL code=%s qty=%s price=%.4f signal_time=%s "
                "shadow_cash_after=%.2f actual_qty=%s shadow_qty=%s fee=%s fee_breakdown=%s reason=%s command=%s",
                account.account_id,
                code,
                sell_qty,
                price,
                decision.signal_time,
                state.shadow_cash,
                state.actual_positions.get(code).qty if code in state.actual_positions else 0,
                state.shadow_positions[code],
                fee_total,
                fee_breakdown,
                decision.reason,
                command,
            )

        for code in active_codes:
            current_qty = int(state.shadow_positions.get(code, 0))
            desired_qty = int(desired_shares.get(code, current_qty))
            price = prices.get(code)
            if price is None or desired_qty <= current_qty:
                continue
            buy_qty, fee_total, fee_breakdown = compute_affordable_qty_with_fee(
                available_cash=float(state.shadow_cash or 0.0),
                price=price,
                desired_qty=desired_qty - current_qty,
                fee_account=account.broker.fee_account,
                market=account.broker.market,
                security_type=account.broker.security_type,
            )
            if buy_qty <= 0:
                self._logger.warning(
                    "BUY_SKIPPED account_id=%s code=%s desired_qty=%s price=%.4f reason=insufficient_cash_for_rebalance",
                    account.account_id,
                    code,
                    desired_qty - current_qty,
                    price,
                )
                continue
            state.shadow_cash = float(state.shadow_cash or 0.0) - buy_qty * price - fee_total
            state.shadow_positions[code] = current_qty + buy_qty
            command = (
                f"place_order(price={price:.4f}, qty={buy_qty}, code='{code}', "
                f"trd_side='BUY', order_type='NORMAL', trd_env='{account.broker.trade_env}', "
                f"acc_index={account.broker.account_index})"
            )
            self._logger.info(
                "DRY_RUN_ORDER account_id=%s action=BUY code=%s qty=%s price=%.4f signal_time=%s "
                "shadow_cash_after=%.2f actual_qty=%s shadow_qty=%s fee=%s fee_breakdown=%s reason=%s command=%s",
                account.account_id,
                code,
                buy_qty,
                price,
                decision.signal_time,
                state.shadow_cash,
                state.actual_positions.get(code).qty if code in state.actual_positions else 0,
                state.shadow_positions[code],
                fee_total,
                fee_breakdown,
                decision.reason,
                command,
            )
