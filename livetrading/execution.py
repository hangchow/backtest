from __future__ import annotations

from dataclasses import dataclass, field
import logging

from strategy.fees import compute_order_fees
from strategy.rebalance import (
    RebalancePolicy,
    build_desired_shares,
    compute_affordable_qty_with_fee,
    compute_portfolio_value,
)
from .config import TradeAccountConfig
from .models import AccountSnapshot, PortfolioRebalanceDecision, PositionSnapshot


@dataclass
class TradeAccountState:
    actual_account: AccountSnapshot | None = None
    actual_positions: dict[str, PositionSnapshot] = field(default_factory=dict)
    shadow_cash: float | None = None
    shadow_positions: dict[str, int] = field(default_factory=dict)


class DryRunRebalanceExecutor:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def execute_portfolio_rebalance(
        self,
        *,
        decision: PortfolioRebalanceDecision,
        accounts: tuple[TradeAccountConfig, ...],
        account_states: dict[str, TradeAccountState],
        pool_codes: tuple[str, ...],
        prices: dict[str, float],
    ) -> None:
        for account in accounts:
            state = account_states.setdefault(account.account_id, TradeAccountState())
            self.execute_account_rebalance(
                decision=decision,
                account=account,
                state=state,
                pool_codes=pool_codes,
                prices=prices,
            )

    def execute_account_rebalance(
        self,
        *,
        decision: PortfolioRebalanceDecision,
        account: TradeAccountConfig,
        state: TradeAccountState,
        pool_codes: tuple[str, ...],
        prices: dict[str, float],
    ) -> None:
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
