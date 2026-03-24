from __future__ import annotations

import logging
import threading
from typing import Callable

from .account_state import AccountStateStore
from .config import TradeAccountConfig
from .execution import RebalancePlanner, TradeAccountState, create_order_executor
from .models import PortfolioRebalanceDecision
from .runtime_state import LiveTradingRuntimeState


class PortfolioCoordinator:
    """把组合决策翻译成当前账户计划并交给执行器。"""

    def __init__(
        self,
        *,
        lock: threading.RLock,
        logger: logging.Logger,
        runtime_state: LiveTradingRuntimeState,
        state_store: AccountStateStore,
        planner: RebalancePlanner,
        order_executor_factory: Callable[..., object] = create_order_executor,
    ) -> None:
        self._lock = lock
        self._logger = logger
        self._runtime_state = runtime_state
        self._state_store = state_store
        self._planner = planner
        self._order_executor_factory = order_executor_factory

    def execute_portfolio_rebalance(self, decision: PortfolioRebalanceDecision) -> None:
        """把一次组合级调仓决策翻译成当前账户的执行计划。"""
        with self._lock:
            config = self._runtime_state.current_config
            if config is None:
                return

            # 这里拿到的是执行层参考价，而不是策略 warm-up 日线。
            # 如果目标股票从未被 push 过最新价格，planner 就无法把目标权重换算成目标股数。
            prices = self._runtime_state.active_prices_for_codes(config.all_codes())
            pool_codes = config.stock_pool.codes
            account = config.trade_account
            state = self._state_store.ensure(account.account_id)
            client = self._runtime_state.trade_account_clients.get(account.account_id)
            plan = self._planner.build_account_plan(
                decision=decision,
                account=account,
                state=state,
                pool_codes=pool_codes,
                prices=prices,
            )
            if plan is None:
                return

            executor = self._order_executor_factory(
                account,
                client=client,
                logger=self._logger,
                state_store=self._state_store,
            )
            try:
                # 调仓执行期间保持统一锁，避免订单回报在 mark_submitted 前抢先修改同一份状态。
                executor.execute_plan(plan=plan, state=state)
            except Exception as exc:
                self._logger.exception(
                    "ORDER_EXECUTION_FAILED account_id=%s executor=%s signal_time=%s error=%s",
                    account.account_id,
                    account.execution.executor,
                    decision.signal_time,
                    exc,
                )
