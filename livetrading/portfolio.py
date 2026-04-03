from __future__ import annotations

import logging
import threading
from typing import Callable

from .account_state import AccountStateStore
from .config import TradeAccountConfig
from .execution import RebalancePlanner, TradeAccountState, create_order_executor
from .notifications import send_email_notification
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
        email_sender: Callable[..., None] = send_email_notification,
    ) -> None:
        self._lock = lock
        self._logger = logger
        self._runtime_state = runtime_state
        self._state_store = state_store
        self._planner = planner
        self._order_executor_factory = order_executor_factory
        self._email_sender = email_sender

    def execute_portfolio_rebalance(self, decision: PortfolioRebalanceDecision) -> None:
        """把一次组合级调仓决策翻译成当前账户的执行计划。"""
        with self._lock:
            config = self._runtime_state.current_config
            if config is None:
                return

            account = config.trade_account
            if account.execution.executor == "notify":
                self._notify_recommendation(config=config, decision=decision)
                return

            # 这里拿到的是执行层参考价，而不是策略 warm-up 日线。
            # 如果目标股票从未被 push 过最新价格，planner 就无法把目标权重换算成目标股数。
            prices = self._runtime_state.active_prices_for_codes(config.all_codes())
            pool_codes = config.stock_pool.codes
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

    def _notify_recommendation(self, *, config, decision: PortfolioRebalanceDecision) -> None:
        account = config.trade_account
        email_config = account.notification.email
        target_codes = tuple(decision.metadata.get("target_codes") or tuple(sorted(decision.target_weights)))
        candidate_codes = tuple(decision.metadata.get("candidate_codes") or ())
        completed_trade_date = decision.metadata.get("completed_trade_date", "N/A")
        market_is_risk_on = decision.metadata.get("market_is_risk_on")
        target_summary = "、".join(target_codes) if target_codes else "CASH"
        candidate_summary = "、".join(candidate_codes) if candidate_codes else "无"
        risk_state = "risk_on" if market_is_risk_on else "risk_off"

        self._logger.info(
            "NOTIFY_SIGNAL signal_time=%s completed_trade_date=%s strategy=%s pool=%s target_codes=%s candidate_codes=%s market_is_risk_on=%s",
            decision.signal_time,
            completed_trade_date,
            config.stock_pool.strategy.name,
            ",".join(config.stock_pool.codes),
            ",".join(target_codes) if target_codes else "CASH",
            ",".join(candidate_codes),
            str(bool(market_is_risk_on)).lower(),
        )

        if not email_config.enabled:
            self._logger.info(
                "NOTIFY_EMAIL_SKIPPED account_id=%s reason=email_disabled",
                account.account_id,
            )
            return

        subject_core = f"{completed_trade_date} {config.stock_pool.strategy.name} 推荐：{target_summary}"
        subject = f"{email_config.subject_prefix} {subject_core}".strip()
        body = "\n".join(
            [
                "实盘选股提醒",
                f"",
                f"策略：{config.stock_pool.strategy.name}",
                f"信号时间：{decision.signal_time}",
                f"已完成交易日：{completed_trade_date}",
                f"当前股票池：{', '.join(config.stock_pool.codes)}",
                f"推荐目标：{target_summary}",
                f"备选候选：{candidate_summary}",
                f"风险状态：{risk_state}",
                f"原因：{decision.reason}",
            ]
        )
        try:
            self._email_sender(email_config, subject=subject, body=body)
        except Exception as exc:
            self._logger.exception(
                "NOTIFY_EMAIL_FAILED account_id=%s signal_time=%s error=%s",
                account.account_id,
                decision.signal_time,
                exc,
            )
            return
        self._logger.info(
            "NOTIFY_EMAIL_SENT account_id=%s signal_time=%s to=%s subject=%s",
            account.account_id,
            decision.signal_time,
            ",".join(email_config.to_addresses),
            subject,
        )
