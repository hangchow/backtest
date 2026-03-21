from __future__ import annotations

from dataclasses import dataclass, field
import logging

import pandas as pd

from strategy.fees import compute_order_fees

from .config import TradeAccountConfig
from .models import AccountSnapshot, FillEvent, OrderIntent, OrderSubmission, OrderUpdate, PositionSnapshot


@dataclass
class PendingOrder:
    """记录一笔已提交但还没最终结束的订单。"""

    broker_order_id: str
    code: str
    side: str
    submitted_qty: int
    limit_price: float
    dealt_qty: int = 0
    reported_dealt_qty: int = 0
    filled_qty: int = 0
    status: str | None = None
    signal_time: pd.Timestamp | None = None
    reason: str | None = None
    estimated_fee_total: float = 0.0
    filled_notional: float = 0.0
    last_avg_price: float | None = None
    settled_expected: bool = False
    settled_cash_delta: float | None = None
    settled_position_delta: int | None = None

    @property
    def open_qty(self) -> int:
        """返回这笔订单当前还未完成的剩余数量。"""
        return max(int(self.submitted_qty) - int(self.dealt_qty), 0)


@dataclass
class AccountRuntimeState:
    """统一存放一个账户在运行时的真实状态、期望状态和 mock 影子状态。"""

    actual_account: AccountSnapshot | None = None
    actual_positions: dict[str, PositionSnapshot] = field(default_factory=dict)
    shadow_cash: float | None = None
    shadow_positions: dict[str, int] = field(default_factory=dict)
    expected_cash: float | None = None
    expected_positions: dict[str, int] = field(default_factory=dict)
    pending_orders: dict[str, PendingOrder] = field(default_factory=dict)
    last_account_sync_at: pd.Timestamp | None = None
    last_position_sync_at: pd.Timestamp | None = None
    last_reconciled_at: pd.Timestamp | None = None
    last_drift_signature: tuple[object, ...] | None = None


class AccountStateStore:
    """集中管理账户的真实状态、影子状态和预期状态。

    实盘链路里最容易出错的不是“如何算一笔单”，而是“订单途中账户到底应该看哪份状态”。
    这个 store 就是专门解决这个问题的单一入口。
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._states: dict[str, AccountRuntimeState] = {}

    @property
    def states(self) -> dict[str, AccountRuntimeState]:
        """暴露内部状态字典，方便 engine 和测试复用同一份对象。"""
        return self._states

    def ensure(self, account_id: str) -> AccountRuntimeState:
        """拿到账户运行态；如果不存在就先创建空状态。"""
        return self._states.setdefault(account_id, AccountRuntimeState())

    def prune(self, *, active_account_ids: set[str], active_codes: set[str]) -> None:
        """清理已经不活跃的账户和代码，避免旧配置残留状态继续参与运行。"""
        stale_account_ids = [account_id for account_id in self._states if account_id not in active_account_ids]
        for account_id in stale_account_ids:
            del self._states[account_id]

        for state in self._states.values():
            tracked_codes = active_codes | {pending.code for pending in state.pending_orders.values()}
            state.shadow_positions = {
                code: qty
                for code, qty in state.shadow_positions.items()
                if code in tracked_codes
            }
            state.expected_positions = {
                code: qty
                for code, qty in state.expected_positions.items()
                if code in tracked_codes
            }

    def sync_active_codes(self, account_id: str, active_codes: tuple[str, ...]) -> AccountRuntimeState:
        """让当前账户对所有活跃代码都具备可规划的初始状态。

        这个方法会补齐 shadow/expected 缺失的代码，并清掉已经不再跟踪的旧代码，
        保证 planner 在任何时刻读取到的持仓视图都是“代码齐全、不会缺 key”的。
        """
        state = self.ensure(account_id)
        tracked_code_set = set(active_codes) | {pending.code for pending in state.pending_orders.values()}
        state.shadow_positions = {
            code: qty for code, qty in state.shadow_positions.items() if code in tracked_code_set
        }
        state.expected_positions = {
            code: qty for code, qty in state.expected_positions.items() if code in tracked_code_set
        }
        for code in tracked_code_set:
            actual_qty = state.actual_positions.get(code).qty if code in state.actual_positions else 0
            state.shadow_positions.setdefault(code, actual_qty)
            state.expected_positions.setdefault(code, actual_qty)
        if state.shadow_cash is None and state.actual_account is not None and state.actual_account.available_funds is not None:
            state.shadow_cash = state.actual_account.available_funds
        if state.expected_cash is None and state.actual_account is not None and state.actual_account.available_funds is not None:
            state.expected_cash = state.actual_account.available_funds
        return state

    def upsert_actual_account(self, account_id: str, snapshot: AccountSnapshot) -> AccountRuntimeState:
        """写入真实账户资金快照，并在首次同步时建立现金基线。

        shadow_cash/expected_cash 只会在尚未初始化时从真实账户继承，
        避免后续执行器已经推进过的本地状态被新的快照无条件覆盖。
        """
        state = self.ensure(account_id)
        state.actual_account = snapshot
        state.last_account_sync_at = snapshot.timestamp
        if state.shadow_cash is None and snapshot.available_funds is not None:
            state.shadow_cash = snapshot.available_funds
        if state.expected_cash is None and snapshot.available_funds is not None:
            state.expected_cash = snapshot.available_funds
        return state

    def upsert_actual_positions(
        self,
        account_id: str,
        positions: dict[str, PositionSnapshot],
    ) -> AccountRuntimeState:
        """写入真实持仓快照，并在首个持仓同步时修正占位基线。

        启动早期经常会先收到 account snapshot，再收到 positions snapshot。
        这时 sync_active_codes 可能已经把股票池代码预填成 0，这个方法会在首个真实持仓到达时
        把这些占位值改成真实基线，避免后续规划错误地从空仓起步。
        """
        state = self.ensure(account_id)
        first_position_sync = state.last_position_sync_at is None
        state.actual_positions = positions
        state.last_position_sync_at = pd.Timestamp.now(tz="UTC")
        if first_position_sync:
            # 启动早期可能先到账户资金，再到账户持仓。
            # 前一步 sync_active_codes() 会把股票池代码预填成 0，避免缺 key；
            # 这里在首个真实持仓快照到达时，必须把这些“占位 0”改成真实基线，
            # 否则 mock executor 会错误地从空仓开始规划。
            tracked_codes = set(state.shadow_positions) | set(state.expected_positions) | set(positions)
            for code in tracked_codes:
                actual_qty = positions.get(code).qty if code in positions else 0
                state.shadow_positions[code] = actual_qty
                if not state.pending_orders:
                    state.expected_positions[code] = actual_qty
        return state

    def mark_submitted(
        self,
        account: TradeAccountConfig,
        intent: OrderIntent,
        submission: OrderSubmission,
    ) -> AccountRuntimeState:
        """在 broker 受理订单后登记 pending，并乐观推进 expected 状态。

        这里的 expected 视图代表“假设这笔单最终会按提交数量成交”时账户应该变成什么样，
        这样下一轮 planner 就能在 broker 快照尚未返回前，先基于更接近真实的状态继续工作。
        """
        state = self.ensure(account.account_id)
        if not submission.accepted or not submission.broker_order_id:
            return state
        submitted_qty = int(submission.submitted_qty or intent.qty)
        submitted_price = float(submission.submitted_price or intent.limit_price)
        estimated_fee_total = self._estimate_order_fee(
            account,
            side=intent.side,
            price=submitted_price,
            qty=submitted_qty,
        )

        pending = PendingOrder(
            broker_order_id=submission.broker_order_id,
            code=intent.code,
            side=intent.side,
            submitted_qty=submitted_qty,
            limit_price=submitted_price,
            status="SUBMITTED",
            signal_time=intent.signal_time,
            reason=intent.reason,
            estimated_fee_total=estimated_fee_total,
        )
        state.pending_orders[pending.broker_order_id] = pending
        self._ensure_expected_base(state, code=intent.code)
        # live 提单路径先乐观预估整笔单最终会成交；如果后面被拒绝或撤单，再回滚未成交部分。
        self._apply_expected_delta(
            state=state,
            code=intent.code,
            side=intent.side,
            qty=pending.submitted_qty,
            price=pending.limit_price,
            fee_total=pending.estimated_fee_total,
            reverse=False,
        )
        return state

    def apply_order_update(self, account: TradeAccountConfig, update: OrderUpdate) -> AccountRuntimeState:
        """消费订单状态更新，并在订单结束时把乐观 expected 修正为最终结果。

        订单状态推送通常会告诉我们：这笔单是否已经结束、累计成交了多少、均价是多少。
        一旦进入最终状态，就可以把提交时的整笔成交预估回拨到真实成交数量。
        """
        state = self.ensure(account.account_id)
        pending = state.pending_orders.get(update.broker_order_id)
        if pending is None:
            return state

        pending.reported_dealt_qty = max(int(pending.reported_dealt_qty), int(update.dealt_qty))
        pending.dealt_qty = max(int(pending.reported_dealt_qty), int(pending.filled_qty))
        pending.status = update.status
        if update.avg_price is not None:
            pending.last_avg_price = float(update.avg_price)

        if self._is_final_status(update.status):
            # 提交时我们先按“整笔成交”乐观推进 expected_*。
            # 订单真正结束后，再把 expected_* 调整到“真实成交数量 + 真实均价 + 真实手续费估算”。
            self._settle_final_expected(account=account, state=state, pending=pending)
            pending.settled_expected = True
        return state

    def apply_fill(self, account: TradeAccountConfig, fill: FillEvent) -> AccountRuntimeState:
        """消费成交回报，累计真实成交数量和成交额。

        有些 broker 会先推订单最终状态，再补最后一笔成交明细；
        因此这里不仅要记账，还要支持在“订单已 final”的情况下再次修正 expected 现金。
        """
        state = self.ensure(account.account_id)
        pending = state.pending_orders.get(fill.broker_order_id)
        if pending is None:
            return state
        pending.filled_qty = min(int(pending.submitted_qty), int(pending.filled_qty) + int(fill.fill_qty))
        pending.dealt_qty = max(int(pending.reported_dealt_qty), int(pending.filled_qty))
        if fill.fill_price is not None:
            pending.filled_notional += float(fill.fill_price) * int(fill.fill_qty)
        # 有些 broker 会先推 final 订单状态，再把最后一笔 deal 补过来。
        # 这里允许在订单已 final 的情况下再次结算 expected_*，把早到的保守估算修正成真实成交额。
        if self._is_final_status(pending.status):
            self._settle_final_expected(account=account, state=state, pending=pending)
            pending.settled_expected = True
        return state

    def reconcile_from_actual(self, account_id: str, active_codes: tuple[str, ...]) -> AccountRuntimeState:
        """根据真实账户快照做对账，并决定 expected 是否可以回归真实状态。

        没有 pending 订单时，expected 可以完全向真实账户看齐；
        有 pending 订单时，则优先保留 expected 视图，只在真实账户已经追上它时再清理已结束挂单。
        """
        state = self.ensure(account_id)
        tracked_codes = self._tracked_codes(state, active_codes)
        if state.pending_orders:
            if self._actual_matches_expected(state, tracked_codes):
                # 真实账户已经追上 expected 视图时，可以把已经结束的订单从 pending 集合里清掉。
                settled_order_ids = [
                    broker_order_id
                    for broker_order_id, pending in state.pending_orders.items()
                    if self._is_final_status(pending.status)
                ]
                for broker_order_id in settled_order_ids:
                    del state.pending_orders[broker_order_id]
                if state.pending_orders:
                    return state
            if state.pending_orders:
                self._log_drift_if_needed(account_id, state, tracked_codes)
                return state

        if state.actual_account is not None and state.actual_account.available_funds is not None:
            state.expected_cash = state.actual_account.available_funds
        state.expected_positions = {
            code: state.actual_positions.get(code).qty if code in state.actual_positions else 0
            for code in active_codes
        }
        state.last_reconciled_at = pd.Timestamp.now(tz="UTC")
        state.last_drift_signature = None
        return state

    def planning_cash(self, *, executor_name: str, state: AccountRuntimeState) -> float:
        """为 planner 选择本轮应该使用的现金视图。

        mock 模式使用 shadow_cash，live submit 模式优先使用 expected_cash。
        这样可以让两类执行器都基于“对自己最可信的一份状态”做规划。
        """
        if executor_name == "mock":
            return float(state.shadow_cash or 0.0)
        if state.expected_cash is not None:
            return float(state.expected_cash)
        if state.actual_account is not None and state.actual_account.available_funds is not None:
            return float(state.actual_account.available_funds)
        return 0.0

    def planning_positions(
        self,
        *,
        executor_name: str,
        state: AccountRuntimeState,
        active_codes: tuple[str, ...],
    ) -> dict[str, int]:
        """为 planner 选择本轮应该使用的持仓视图。

        mock 模式直接看 shadow_positions；
        live submit 模式优先看 expected_positions，避免上一轮挂单尚未反映到真实账户时重复买卖。
        """
        if executor_name == "mock":
            return {code: int(state.shadow_positions.get(code, 0)) for code in active_codes}
        positions: dict[str, int] = {}
        for code in active_codes:
            if code in state.expected_positions:
                positions[code] = int(state.expected_positions.get(code, 0))
            else:
                positions[code] = int(state.actual_positions.get(code).qty if code in state.actual_positions else 0)
        return positions

    def pending_order_count(self, account_id: str) -> int:
        """返回账户当前还在执行中的订单数量。"""
        return len(self.ensure(account_id).pending_orders)

    def _ensure_expected_base(self, state: AccountRuntimeState, *, code: str) -> None:
        if state.expected_cash is None and state.actual_account is not None and state.actual_account.available_funds is not None:
            state.expected_cash = state.actual_account.available_funds
        state.expected_positions.setdefault(code, state.actual_positions.get(code).qty if code in state.actual_positions else 0)

    def _apply_expected_delta(
        self,
        *,
        state: AccountRuntimeState,
        code: str,
        side: str,
        qty: int,
        price: float,
        fee_total: float,
        reverse: bool,
    ) -> None:
        direction = -1 if reverse else 1
        state.expected_cash = float(state.expected_cash or 0.0) + direction * self._cash_delta(
            side=side,
            qty=qty,
            price=price,
            fee_total=fee_total,
        )
        state.expected_positions[code] = int(state.expected_positions.get(code, 0)) + direction * self._position_delta(
            side=side,
            qty=qty,
        )

    def _settle_final_expected(
        self,
        *,
        account: TradeAccountConfig,
        state: AccountRuntimeState,
        pending: PendingOrder,
    ) -> None:
        """把提交时的乐观 expected 预估结算成最终订单结果。

        核心思路是先算“提交时假设整笔成交”的现金/持仓变化，再算“真实最终成交”的变化，
        两者做差后回写到 expected_*，从而把预估状态平滑地修正成真实结果。
        """
        self._ensure_expected_base(state, code=pending.code)
        final_qty = min(max(int(pending.dealt_qty), 0), int(pending.submitted_qty))
        final_price = self._resolve_final_price(pending, final_qty)
        final_fee_total = self._estimate_order_fee(
            account,
            side=pending.side,
            price=final_price,
            qty=final_qty,
        )

        optimistic_cash_delta = self._cash_delta(
            side=pending.side,
            qty=pending.submitted_qty,
            price=pending.limit_price,
            fee_total=pending.estimated_fee_total,
        )
        final_cash_delta = self._cash_delta(
            side=pending.side,
            qty=final_qty,
            price=final_price,
            fee_total=final_fee_total,
        )
        final_position_delta = self._position_delta(side=pending.side, qty=final_qty)
        if pending.settled_expected and pending.settled_cash_delta is not None and pending.settled_position_delta is not None:
            cash_adjustment = final_cash_delta - pending.settled_cash_delta
            position_adjustment = final_position_delta - pending.settled_position_delta
        else:
            cash_adjustment = final_cash_delta - optimistic_cash_delta
            optimistic_position_delta = self._position_delta(side=pending.side, qty=pending.submitted_qty)
            position_adjustment = final_position_delta - optimistic_position_delta

        state.expected_cash = float(state.expected_cash or 0.0) + cash_adjustment
        state.expected_positions[pending.code] = int(state.expected_positions.get(pending.code, 0)) + position_adjustment
        pending.settled_cash_delta = final_cash_delta
        pending.settled_position_delta = final_position_delta

    @staticmethod
    def _resolve_final_price(pending: PendingOrder, final_qty: int) -> float:
        """优先用订单回报里的均价，其次用累计成交额，最后退回提交限价。"""
        if final_qty <= 0:
            return float(pending.limit_price)
        if pending.last_avg_price is not None and pending.last_avg_price > 0:
            return float(pending.last_avg_price)
        if pending.filled_notional > 0:
            return float(pending.filled_notional) / float(final_qty)
        return float(pending.limit_price)

    @staticmethod
    def _position_delta(*, side: str, qty: int) -> int:
        normalized_side = side.strip().upper()
        if normalized_side == "BUY":
            return int(qty)
        if normalized_side == "SELL":
            return -int(qty)
        raise ValueError(f"unsupported order side: {side}")

    @staticmethod
    def _cash_delta(*, side: str, qty: int, price: float, fee_total: float) -> float:
        notional = float(price) * int(qty)
        normalized_side = side.strip().upper()
        if normalized_side == "BUY":
            return -(notional + float(fee_total))
        if normalized_side == "SELL":
            return notional - float(fee_total)
        raise ValueError(f"unsupported order side: {side}")

    @staticmethod
    def _estimate_order_fee(account: TradeAccountConfig, *, side: str, price: float, qty: int) -> float:
        fee_total, _ = compute_order_fees(
            fee_account=account.broker.fee_account,
            market=account.broker.market,
            side="buy" if side.strip().upper() == "BUY" else "sell",
            price=price,
            shares=qty,
            security_type=account.broker.security_type,
        )
        return fee_total

    def _log_drift_if_needed(
        self,
        account_id: str,
        state: AccountRuntimeState,
        active_codes: tuple[str, ...],
    ) -> None:
        """在真实账户与 expected 视图发生偏离时打印一次漂移日志。

        这里会对漂移签名做去重，避免 broker 长时间未追平时反复刷同一条日志，
        影响线上排查时对真正新问题的观察。
        """
        actual_cash = state.actual_account.available_funds if state.actual_account is not None else None
        actual_positions = tuple(
            (code, state.actual_positions.get(code).qty if code in state.actual_positions else 0)
            for code in active_codes
        )
        expected_positions = tuple((code, int(state.expected_positions.get(code, 0))) for code in active_codes)
        signature = (
            actual_cash,
            state.expected_cash,
            actual_positions,
            expected_positions,
            tuple(sorted(state.pending_orders)),
        )
        if signature == state.last_drift_signature:
            return
        state.last_drift_signature = signature
        self._logger.warning(
            "ACCOUNT_STATE_DRIFT account_id=%s actual_available_funds=%s expected_cash=%s pending_orders=%s actual_positions=%s expected_positions=%s",
            account_id,
            actual_cash,
            state.expected_cash,
            sorted(state.pending_orders),
            dict(actual_positions),
            dict(expected_positions),
        )

    @staticmethod
    def _tracked_codes(state: AccountRuntimeState, active_codes: tuple[str, ...]) -> tuple[str, ...]:
        """把股票池代码和 pending 订单代码合并，避免切池时把未完成订单直接遗忘。"""
        return tuple(sorted(set(active_codes) | {pending.code for pending in state.pending_orders.values()}))

    @staticmethod
    def _actual_matches_expected(state: AccountRuntimeState, active_codes: tuple[str, ...]) -> bool:
        actual_cash = state.actual_account.available_funds if state.actual_account is not None else None
        expected_cash = state.expected_cash
        if actual_cash is not None and expected_cash is not None and abs(actual_cash - expected_cash) > 0.05:
            return False
        for code in active_codes:
            actual_qty = state.actual_positions.get(code).qty if code in state.actual_positions else 0
            expected_qty = int(state.expected_positions.get(code, 0))
            if actual_qty != expected_qty:
                return False
        return True

    @staticmethod
    def _is_final_status(status: str | None) -> bool:
        normalized = (status or "").strip().lower().replace(" ", "_")
        if normalized in {
            "filled_all",
            "filled",
            "cancelled_all",
            "cancelled_part",
            "canceled_all",
            "canceled_part",
            "failed",
            "submit_failed",
            "submitted_failed",
            "deleted",
            "disabled",
            "rejected",
        }:
            return True
        if "reject" in normalized:
            return True
        if normalized.endswith("_failed"):
            return True
        if normalized.startswith("cancelled_") and not normalized.startswith("cancelling_"):
            return True
        if normalized.startswith("canceled_") and not normalized.startswith("canceling_"):
            return True
        return False
