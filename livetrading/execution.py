from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging

from strategy.fees import compute_order_fees
from strategy.rebalance import (
    RebalancePolicy,
    build_desired_shares,
    compute_affordable_qty_with_fee,
    compute_portfolio_value,
)
from .account_state import AccountRuntimeState, AccountStateStore
from .config import TradeAccountConfig
from .models import OrderIntent, OrderSubmission, PortfolioRebalanceDecision
from .trade_accounts.base import TradeAccountClient


@dataclass(frozen=True)
class AccountRebalancePlan:
    """描述某个账户在某次信号下需要执行的完整调仓计划。"""

    account: TradeAccountConfig
    decision: PortfolioRebalanceDecision
    sell_intents: tuple[OrderIntent, ...]
    buy_intents: tuple[OrderIntent, ...]


class RebalancePlanner:
    """把策略信号转换成账户级订单计划。"""

    def __init__(self, logger: logging.Logger, state_store: AccountStateStore) -> None:
        self._logger = logger
        self._state_store = state_store

    def build_account_plan(
        self,
        *,
        decision: PortfolioRebalanceDecision,
        account: TradeAccountConfig,
        state: AccountRuntimeState,
        pool_codes: tuple[str, ...],
        prices: dict[str, float],
    ) -> AccountRebalancePlan | None:
        """按账户的执行模式选择规划视图，并生成买卖 intent。"""
        # active_codes 不能只看股票池本身，还要把账户里已有的持仓代码也带上。
        # 否则目标权重里虽然不再持有，但旧仓位不会被规划成卖单。
        active_codes = tuple(
            sorted(set(pool_codes) | set(state.shadow_positions) | set(state.expected_positions))
        )
        current_positions = self._state_store.planning_positions(
            executor_name=account.execution.executor,
            state=state,
            active_codes=active_codes,
        )
        portfolio_value = compute_portfolio_value(
            cash=self._state_store.planning_cash(
                executor_name=account.execution.executor,
                state=state,
            ),
            positions=current_positions,
            prices=prices,
        )
        if portfolio_value <= 0:
            self._logger.warning("REBALANCE_SKIPPED account_id=%s reason=no_portfolio_value", account.account_id)
            return None

        rebalance_policy = RebalancePolicy(band_pct=float(decision.metadata.get("rebalance_band_pct", 0.0)))
        desired_shares = build_desired_shares(
            active_codes=active_codes,
            current_positions=current_positions,
            target_weights=decision.target_weights,
            prices=prices,
            portfolio_value=portfolio_value,
            policy=rebalance_policy,
            tradable_codes=prices.keys(),
        )

        sell_intents: list[OrderIntent] = []
        buy_intents: list[OrderIntent] = []
        for code in active_codes:
            current_qty = int(current_positions.get(code, 0))
            desired_qty = int(desired_shares.get(code, current_qty))
            price = prices.get(code)
            if price is None:
                continue
            if current_qty > desired_qty:
                sell_intents.append(
                    OrderIntent(
                        account_id=account.account_id,
                        code=code,
                        side="SELL",
                        qty=current_qty - desired_qty,
                        reference_price=price,
                        limit_price=price,
                        reason=decision.reason,
                        signal_time=decision.signal_time,
                    )
                )
            elif desired_qty > current_qty:
                buy_intents.append(
                    OrderIntent(
                        account_id=account.account_id,
                        code=code,
                        side="BUY",
                        qty=desired_qty - current_qty,
                        reference_price=price,
                        limit_price=price,
                        reason=decision.reason,
                        signal_time=decision.signal_time,
                    )
                )

        return AccountRebalancePlan(
            account=account,
            decision=decision,
            sell_intents=tuple(sell_intents),
            buy_intents=tuple(buy_intents),
        )


class OrderExecutor(ABC):
    """执行器接口：规划器只负责算单，执行器只负责怎么落地。"""

    def __init__(self, logger: logging.Logger, state_store: AccountStateStore) -> None:
        self._logger = logger
        self._state_store = state_store

    @abstractmethod
    def execute_plan(self, *, plan: AccountRebalancePlan, state: AccountRuntimeState) -> None:
        raise NotImplementedError


class MockExecutor(OrderExecutor):
    """本地 mock 执行器：不提单，只维护影子状态并打印日志。"""

    def execute_plan(self, *, plan: AccountRebalancePlan, state: AccountRuntimeState) -> None:
        account = plan.account
        decision = plan.decision
        self._logger.info(
            "DRY_RUN_REBALANCE account_id=%s signal_time=%s reason=%s target_weights=%s",
            account.account_id,
            decision.signal_time,
            decision.reason,
            decision.target_weights,
        )

        for intent in plan.sell_intents:
            violation = _order_limit_violation(account, intent)
            if violation is not None:
                self._logger.warning(
                    "ORDER_SKIPPED account_id=%s action=%s code=%s qty=%s reason=%s",
                    account.account_id,
                    intent.side,
                    intent.code,
                    intent.qty,
                    violation,
                )
                continue
            self._execute_sell(intent=intent, plan=plan, state=state)

        for intent in plan.buy_intents:
            violation = _order_limit_violation(account, intent)
            if violation is not None:
                self._logger.warning(
                    "ORDER_SKIPPED account_id=%s action=%s code=%s qty=%s reason=%s",
                    account.account_id,
                    intent.side,
                    intent.code,
                    intent.qty,
                    violation,
                )
                continue
            self._execute_buy(intent=intent, plan=plan, state=state)

    def _execute_sell(
        self,
        *,
        intent: OrderIntent,
        plan: AccountRebalancePlan,
        state: AccountRuntimeState,
    ) -> None:
        """mock 卖单直接改影子现金和影子持仓。"""
        account = plan.account
        current_qty = int(state.shadow_positions.get(intent.code, 0))
        fee_total, fee_breakdown = compute_order_fees(
            fee_account=account.broker.fee_account,
            market=account.broker.market,
            side="sell",
            price=intent.limit_price,
            shares=intent.qty,
            security_type=account.broker.security_type,
        )
        state.shadow_cash = float(state.shadow_cash or 0.0) + intent.qty * intent.limit_price - fee_total
        state.shadow_positions[intent.code] = max(current_qty - intent.qty, 0)
        self._logger.info(
            "DRY_RUN_ORDER account_id=%s action=SELL code=%s qty=%s price=%.4f signal_time=%s "
            "shadow_cash_after=%.2f actual_qty=%s shadow_qty=%s fee=%s fee_breakdown=%s reason=%s command=%s",
            account.account_id,
            intent.code,
            intent.qty,
            intent.limit_price,
            plan.decision.signal_time,
            state.shadow_cash,
            state.actual_positions.get(intent.code).qty if intent.code in state.actual_positions else 0,
            state.shadow_positions[intent.code],
            fee_total,
            fee_breakdown,
            plan.decision.reason,
            _build_place_order_command(account, intent),
        )

    def _execute_buy(
        self,
        *,
        intent: OrderIntent,
        plan: AccountRebalancePlan,
        state: AccountRuntimeState,
    ) -> None:
        """mock 买单按可用现金和手续费反推出实际可买数量。"""
        account = plan.account
        current_qty = int(state.shadow_positions.get(intent.code, 0))
        buy_qty, fee_total, fee_breakdown = compute_affordable_qty_with_fee(
            available_cash=float(state.shadow_cash or 0.0),
            price=intent.limit_price,
            desired_qty=intent.qty,
            fee_account=account.broker.fee_account,
            market=account.broker.market,
            security_type=account.broker.security_type,
        )
        if buy_qty <= 0:
            self._logger.warning(
                "BUY_SKIPPED account_id=%s code=%s desired_qty=%s price=%.4f reason=insufficient_cash_for_rebalance",
                account.account_id,
                intent.code,
                intent.qty,
                intent.limit_price,
            )
            return
        state.shadow_cash = float(state.shadow_cash or 0.0) - buy_qty * intent.limit_price - fee_total
        state.shadow_positions[intent.code] = current_qty + buy_qty
        self._logger.info(
            "DRY_RUN_ORDER account_id=%s action=BUY code=%s qty=%s price=%.4f signal_time=%s "
            "shadow_cash_after=%.2f actual_qty=%s shadow_qty=%s fee=%s fee_breakdown=%s reason=%s command=%s",
            account.account_id,
            intent.code,
            buy_qty,
            intent.limit_price,
            plan.decision.signal_time,
            state.shadow_cash,
            state.actual_positions.get(intent.code).qty if intent.code in state.actual_positions else 0,
            state.shadow_positions[intent.code],
            fee_total,
            fee_breakdown,
            plan.decision.reason,
            _build_place_order_command(
                account,
                OrderIntent(
                    account_id=intent.account_id,
                    code=intent.code,
                    side=intent.side,
                    qty=buy_qty,
                    reference_price=intent.reference_price,
                    limit_price=intent.limit_price,
                    reason=intent.reason,
                    signal_time=intent.signal_time,
                    metadata=intent.metadata,
                ),
            ),
        )


class _BaseFutuSubmitExecutor(OrderExecutor):
    """Futu 提单执行器公共逻辑：校验、提交、记 pending、打印日志。"""

    executor_name: str = ""
    required_trade_env: str = ""

    def __init__(
        self,
        logger: logging.Logger,
        state_store: AccountStateStore,
        client: TradeAccountClient | None,
    ) -> None:
        super().__init__(logger, state_store)
        self._client = client

    def execute_plan(self, *, plan: AccountRebalancePlan, state: AccountRuntimeState) -> None:
        account = plan.account
        self._validate_account_config(account)
        skip_reason = self._runtime_skip_reason(state)
        if skip_reason is not None:
            self._logger.warning(
                "REBALANCE_SKIPPED account_id=%s executor=%s reason=%s",
                account.account_id,
                self.executor_name,
                skip_reason,
            )
            return
        if self._client is None:
            self._logger.error("ORDER_SUBMIT_FAILED account_id=%s reason=trade_account_client_unavailable", account.account_id)
            return

        self._logger.info(
            "ORDER_PLAN account_id=%s executor=%s signal_time=%s reason=%s sells=%s buys=%s target_weights=%s pending_orders=%s",
            account.account_id,
            self.executor_name,
            plan.decision.signal_time,
            plan.decision.reason,
            len(plan.sell_intents),
            len(plan.buy_intents),
            plan.decision.target_weights,
            self._state_store.pending_order_count(account.account_id),
        )

        # 顺序保持为“先卖后买”。
        # 这样 live 提单路径即使还没拿到账户下一轮快照，也能更接近真实的现金释放顺序。
        for intent in plan.sell_intents:
            final_intent = self._prepare_intent_for_submission(account=account, state=state, intent=intent)
            if final_intent is None:
                continue
            violation = _order_limit_violation(account, final_intent)
            if violation is not None:
                self._logger.warning(
                    "ORDER_SKIPPED account_id=%s action=%s code=%s qty=%s reason=%s",
                    account.account_id,
                    final_intent.side,
                    final_intent.code,
                    final_intent.qty,
                    violation,
                )
                continue
            self._submit_intent(account=account, intent=final_intent)

        for intent in plan.buy_intents:
            final_intent = self._prepare_intent_for_submission(account=account, state=state, intent=intent)
            if final_intent is None:
                continue
            violation = _order_limit_violation(account, final_intent)
            if violation is not None:
                self._logger.warning(
                    "ORDER_SKIPPED account_id=%s action=%s code=%s qty=%s reason=%s",
                    account.account_id,
                    final_intent.side,
                    final_intent.code,
                    final_intent.qty,
                    violation,
                )
                continue
            self._submit_intent(account=account, intent=final_intent)

    def _validate_account_config(self, account: TradeAccountConfig) -> None:
        if account.broker.trade_env != self.required_trade_env:
            raise ValueError(
                f"account {account.account_id} {self.executor_name} executor requires trade_env={self.required_trade_env}"
            )

    @staticmethod
    def _runtime_skip_reason(state: AccountRuntimeState) -> str | None:
        if state.actual_account is None:
            return "account_snapshot_not_synchronized"
        if state.last_position_sync_at is None:
            return "positions_not_synchronized"
        return None

    def _prepare_intent_for_submission(
        self,
        *,
        account: TradeAccountConfig,
        state: AccountRuntimeState,
        intent: OrderIntent,
    ) -> OrderIntent | None:
        """把规划层 intent 收口成最终提交给 broker 的订单。"""
        if intent.side != "BUY":
            return intent

        available_cash = self._state_store.planning_cash(
            executor_name=account.execution.executor,
            state=state,
        )
        buy_qty, _, _ = compute_affordable_qty_with_fee(
            available_cash=available_cash,
            price=intent.limit_price,
            desired_qty=intent.qty,
            fee_account=account.broker.fee_account,
            market=account.broker.market,
            security_type=account.broker.security_type,
        )
        if buy_qty <= 0:
            self._logger.warning(
                "BUY_SKIPPED account_id=%s executor=%s code=%s desired_qty=%s price=%.4f reason=insufficient_cash_for_rebalance",
                account.account_id,
                self.executor_name,
                intent.code,
                intent.qty,
                intent.limit_price,
            )
            return None
        if buy_qty == intent.qty:
            return intent

        self._logger.info(
            "ORDER_RESIZED account_id=%s executor=%s action=BUY code=%s desired_qty=%s adjusted_qty=%s price=%.4f reason=affordable_qty_with_fee",
            account.account_id,
            self.executor_name,
            intent.code,
            intent.qty,
            buy_qty,
            intent.limit_price,
        )
        return OrderIntent(
            account_id=intent.account_id,
            code=intent.code,
            side=intent.side,
            qty=buy_qty,
            reference_price=intent.reference_price,
            limit_price=intent.limit_price,
            reason=intent.reason,
            signal_time=intent.signal_time,
            metadata=intent.metadata,
        )

    def _submit_intent(self, *, account: TradeAccountConfig, intent: OrderIntent) -> None:
        self._logger.info(
            "ORDER_SUBMITTING account_id=%s executor=%s action=%s code=%s qty=%s price=%.4f signal_time=%s",
            account.account_id,
            self.executor_name,
            intent.side,
            intent.code,
            intent.qty,
            intent.limit_price,
            intent.signal_time,
        )
        submission = self._client.submit_order(intent)
        if submission.accepted:
            self._state_store.mark_submitted(account, intent, submission)
        _log_submission(self._logger, account, self.executor_name, intent, submission)


class FutuSimulateExecutor(_BaseFutuSubmitExecutor):
    """把订单真正发到 Futu 模拟交易环境。"""

    executor_name = "futu_simulate"
    required_trade_env = "SIMULATE"


class FutuRealExecutor(_BaseFutuSubmitExecutor):
    """把订单真正发到 Futu 真实交易环境。"""

    executor_name = "futu_real"
    required_trade_env = "REAL"

    def _validate_account_config(self, account: TradeAccountConfig) -> None:
        super()._validate_account_config(account)
        if not account.execution.enable_real_trading:
            raise ValueError(f"account {account.account_id} futu_real executor requires enable_real_trading=true")


def create_order_executor(
    account: TradeAccountConfig,
    *,
    client: TradeAccountClient | None,
    logger: logging.Logger,
    state_store: AccountStateStore,
) -> OrderExecutor:
    """按账户 execution.executor 返回对应执行器实例。"""
    if account.execution.executor == "mock":
        return MockExecutor(logger, state_store)
    if account.execution.executor == "futu_simulate":
        return FutuSimulateExecutor(logger, state_store, client)
    if account.execution.executor == "futu_real":
        return FutuRealExecutor(logger, state_store, client)
    raise ValueError(f"unsupported executor: {account.execution.executor}")


def _order_limit_violation(account: TradeAccountConfig, intent: OrderIntent) -> str | None:
    """统一检查执行层的订单数量和名义金额上限。"""
    max_order_qty = account.execution.max_order_qty
    if max_order_qty is not None and intent.qty > max_order_qty:
        return "max_order_qty_exceeded"
    max_order_notional = account.execution.max_order_notional
    if max_order_notional is not None and intent.limit_price * intent.qty > max_order_notional:
        return "max_order_notional_exceeded"
    return None


def _build_place_order_command(account: TradeAccountConfig, intent: OrderIntent) -> str:
    return (
        f"place_order(price={intent.limit_price:.4f}, qty={intent.qty}, code='{intent.code}', "
        f"trd_side='{intent.side}', order_type='NORMAL', trd_env='{account.broker.trade_env}', "
        f"acc_index={account.broker.account_index})"
    )


def _log_submission(
    logger: logging.Logger,
    account: TradeAccountConfig,
    executor_name: str,
    intent: OrderIntent,
    submission: OrderSubmission,
) -> None:
    """统一输出提交成功和拒单日志。"""
    if submission.accepted:
        logger.info(
            "ORDER_SUBMITTED account_id=%s executor=%s action=%s code=%s qty=%s price=%.4f broker_order_id=%s message=%s",
            account.account_id,
            executor_name,
            intent.side,
            intent.code,
            submission.submitted_qty or intent.qty,
            submission.submitted_price or intent.limit_price,
            submission.broker_order_id,
            submission.message,
        )
        return
    logger.warning(
        "ORDER_REJECTED account_id=%s executor=%s action=%s code=%s qty=%s price=%.4f broker_order_id=%s message=%s",
        account.account_id,
        executor_name,
        intent.side,
        intent.code,
        intent.qty,
        intent.limit_price,
        submission.broker_order_id,
        submission.message,
    )


# 兼容旧代码和旧文档里 still 使用的类名。
TradeAccountState = AccountRuntimeState
DryRunRebalanceExecutor = MockExecutor
