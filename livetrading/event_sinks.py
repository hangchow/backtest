from __future__ import annotations

import logging
import threading
from typing import Any

import pandas as pd

from .account_state import AccountStateStore
from .models import AccountSnapshot, FillEvent, OrderUpdate, PositionSnapshot, QuoteUpdate
from .portfolio import PortfolioCoordinator
from .runtime_state import LiveTradingRuntimeState


class QuoteBrokerEventSinkAdapter:
    """承接行情 broker 推送，并驱动策略与调仓协调器。"""

    def __init__(
        self,
        *,
        lock: threading.RLock,
        logger: logging.Logger,
        runtime_state: LiveTradingRuntimeState,
        portfolio_coordinator: PortfolioCoordinator,
    ) -> None:
        self._lock = lock
        self._logger = logger
        self._runtime_state = runtime_state
        self._portfolio_coordinator = portfolio_coordinator

    def on_quote(self, update: QuoteUpdate) -> None:
        with self._lock:
            self._runtime_state.latest_quotes[update.code] = update
            config = self._runtime_state.callback_config()
            runtime = config.runtime if config is not None else None
        if runtime is not None and runtime.log_price_updates:
            self._logger.info(
                "QUOTE code=%s time=%s last=%.4f volume=%s turnover=%s",
                update.code,
                update.timestamp,
                update.last_price,
                update.volume,
                update.turnover,
            )

    def on_bar(self, code: str, bar: pd.Series | dict[str, Any]) -> None:
        bar_row = pd.Series(bar)
        with self._lock:
            # 这里记录的是执行层参考价，供 planner 把目标权重换算成股数。
            # 它和策略内部用来出信号的 completed daily window 是两套概念。
            self._runtime_state.latest_bar_prices[code] = float(bar_row["close"])
            pool_strategy = self._runtime_state.pool_strategy
        if pool_strategy is None:
            return

        # 任意一只股票的新分钟 bar 都可能推动整个股票池策略出一次组合决策。
        decision = pool_strategy.on_bar(code, bar_row)
        if decision is not None:
            self._portfolio_coordinator.execute_portfolio_rebalance(decision)

    def on_broker_message(self, level: int, message: str) -> None:
        self._logger.log(level, message)


class TradeAccountEventSinkAdapter:
    """承接账户侧事件，并把状态推进收口到 AccountStateStore。"""

    def __init__(
        self,
        *,
        lock: threading.RLock,
        logger: logging.Logger,
        runtime_state: LiveTradingRuntimeState,
        account_state_store: AccountStateStore,
    ) -> None:
        self._lock = lock
        self._logger = logger
        self._runtime_state = runtime_state
        self._account_state_store = account_state_store

    def on_account(self, account_id: str, snapshot: AccountSnapshot) -> None:
        with self._lock:
            config = self._runtime_state.callback_config()
            if config is None or account_id != config.trade_account.account_id:
                return
            self._account_state_store.upsert_actual_account(account_id, snapshot)
            self._account_state_store.sync_active_codes(account_id, config.all_codes())
            self._account_state_store.reconcile_from_actual(account_id, config.all_codes())
            runtime = config.runtime
            should_log = runtime.log_account_updates and account_id in self._runtime_state.pending_account_log_ids
            if should_log:
                self._runtime_state.pending_account_log_ids.discard(account_id)
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
        with self._lock:
            config = self._runtime_state.callback_config()
            if config is None or account_id != config.trade_account.account_id:
                return
            active_codes = config.all_codes()
            state = self._account_state_store.upsert_actual_positions(account_id, positions)
            self._account_state_store.sync_active_codes(account_id, active_codes)
            self._account_state_store.reconcile_from_actual(account_id, active_codes)
            runtime = config.runtime
            should_log = runtime.log_position_updates and account_id in self._runtime_state.pending_position_log_ids
            if should_log:
                self._runtime_state.pending_position_log_ids.discard(account_id)

        if should_log:
            summary = [
                f"{code}:actual_qty={positions.get(code).qty if code in positions else 0},shadow_qty={state.shadow_positions.get(code, 0)}"
                for code in sorted(active_codes)
            ]
            self._logger.info("POSITIONS account_id=%s %s", account_id, " | ".join(summary))

    def on_order_update(self, account_id: str, update: OrderUpdate) -> None:
        with self._lock:
            config = self._runtime_state.callback_config()
            if config is None:
                return
            if account_id != config.trade_account.account_id:
                return
            account = config.trade_account
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
        with self._lock:
            config = self._runtime_state.callback_config()
            if config is None:
                return
            if account_id != config.trade_account.account_id:
                return
            account = config.trade_account
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

    def on_broker_message(self, level: int, message: str) -> None:
        self._logger.log(level, message)
