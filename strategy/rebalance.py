from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from .fees import compute_order_fees


DEFAULT_REBALANCE_BAND_PCT = 0.1


@dataclass(frozen=True)
class RebalancePolicy:
    # 调仓带是组合/执行域参数，不属于某个信号策略本身。
    band_pct: float = DEFAULT_REBALANCE_BAND_PCT

    @classmethod
    def from_mapping(cls, values: Mapping[str, object] | None = None) -> RebalancePolicy:
        raw = values or {}
        return cls(band_pct=float(raw.get("rebalance_band_pct", DEFAULT_REBALANCE_BAND_PCT)))

    def validate(self) -> None:
        if not 0 <= self.band_pct <= 1:
            raise ValueError("rebalance-band-pct must be within [0, 1]")


def compute_portfolio_value(
    *,
    cash: float,
    positions: Mapping[str, int],
    prices: Mapping[str, float],
) -> float:
    """按现金加持仓市值估算当前组合总资产。"""
    return float(cash) + sum(int(qty) * float(prices[code]) for code, qty in positions.items() if qty > 0 and code in prices)


def build_desired_shares(
    *,
    active_codes: Collection[str],
    current_positions: Mapping[str, int],
    target_weights: Mapping[str, float],
    prices: Mapping[str, float],
    portfolio_value: float,
    policy: RebalancePolicy,
    tradable_codes: Collection[str] | None = None,
) -> dict[str, int]:
    """把目标权重转换成目标股数，并应用调仓带。"""
    policy.validate()
    tradable = set(prices) if tradable_codes is None else set(tradable_codes)
    desired: dict[str, int] = {}
    for code in active_codes:
        current_qty = int(current_positions.get(code, 0))
        price = prices.get(code)
        if price is None or code not in tradable:
            desired[code] = current_qty
            continue
        target_weight = max(0.0, float(target_weights.get(code, 0.0)))
        target_value = float(portfolio_value) * target_weight
        desired_qty = int(target_value // price)
        delta_value = abs(desired_qty - current_qty) * price
        if portfolio_value > 0 and policy.band_pct > 0 and (delta_value / portfolio_value) < policy.band_pct:
            desired_qty = current_qty
        desired[code] = desired_qty
    return desired


def compute_affordable_qty_with_fee(
    *,
    available_cash: float,
    price: float,
    desired_qty: int,
    fee_account: str | None,
    market: str,
    security_type: str,
) -> tuple[int, float, dict[str, float]]:
    """在考虑手续费后，反推出当前现金最多能买多少股。"""
    qty = min(desired_qty, int(max(0.0, available_cash) // price))
    while qty > 0:
        fee_total, fee_breakdown = compute_order_fees(
            fee_account=fee_account,
            market=market,
            side="buy",
            price=price,
            shares=qty,
            security_type=security_type,
        )
        if qty * price + fee_total <= available_cash + 1e-9:
            return qty, fee_total, fee_breakdown
        qty -= 1
    return 0, 0.0, {}
