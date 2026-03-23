from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any

import pandas as pd

from strategy.dual_momentum import (
    DualMomentumParams,
    build_dual_momentum_signal,
)
from strategy.dual_momentum_state import DualMomentumDailyState
from domain.rebalance import RebalancePolicy
from .config import StockPoolConfig
from .models import PortfolioRebalanceDecision
from .pool_strategy_registry import (
    register_pool_strategy,
    resolve_pool_strategy_factory,
    supported_pool_strategy_names,
    unregister_pool_strategy,
)


class PoolLiveStrategy(ABC):
    def __init__(self, config: StockPoolConfig) -> None:
        self.config = config
        self.codes = config.codes

    @abstractmethod
    def required_daily_warmup_bars(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def bootstrap(self, histories: dict[str, pd.DataFrame]) -> None:
        raise NotImplementedError

    @abstractmethod
    def on_bar(self, code: str, bar: pd.Series | dict[str, Any]) -> PortfolioRebalanceDecision | None:
        raise NotImplementedError


class DualMomentumPoolStrategy(PoolLiveStrategy):
    def __init__(self, config: StockPoolConfig) -> None:
        super().__init__(config)
        # live 侧不再自己维护一套参数定义，直接复用 strategy 层的统一参数对象。
        self.signal_params = DualMomentumParams.from_mapping(config.strategy.params)
        self.signal_params.validate()
        self.rebalance_policy = RebalancePolicy.from_mapping(config.strategy.params)
        self.rebalance_policy.validate()
        self._state = DualMomentumDailyState(self.codes, self.signal_params.required_warmup_bars())

    def required_daily_warmup_bars(self) -> int:
        """返回 dual momentum 至少需要的 warm-up 日线根数。"""
        return self.signal_params.required_warmup_bars()

    def bootstrap(self, histories: dict[str, pd.DataFrame]) -> None:
        """把 warm-up 日线喂给日频状态机，初始化策略上下文。"""
        # 日频状态机已经下沉到 strategy 层，这里只负责把历史 warm-up 交给它。
        self._state.bootstrap(histories)

    def on_bar(self, code: str, bar: pd.Series | dict[str, Any]) -> PortfolioRebalanceDecision | None:
        """把分钟 bar 交给日频状态机，必要时产出调仓决策。"""
        completed = self._state.on_bar(code, bar)
        if completed is None:
            return None
        return self._build_rebalance_decision(
            signal_time=completed.signal_time,
            current_trade_date=completed.current_trade_date,
            prices=completed.prices,
            volumes=completed.volumes,
        )

    def _build_rebalance_decision(
        self,
        *,
        signal_time: pd.Timestamp,
        current_trade_date: date,
        prices: pd.DataFrame,
        volumes: pd.DataFrame,
    ) -> PortfolioRebalanceDecision | None:
        """用已完成日线窗口计算信号，并封装成组合调仓决策。"""
        signal = build_dual_momentum_signal(
            prices,
            volumes,
            params=self.signal_params,
        )
        if signal is None:
            return None

        # 这里不直接下单，只把统一的目标权重和诊断信息交给引擎后续处理。
        return PortfolioRebalanceDecision(
            signal_time=signal_time,
            target_weights=signal.target_weights,
            reason=(
                f"dual_momentum rebalance using completed daily data through {signal.completed_trade_date} "
                f"(targets={','.join(signal.target_codes) if signal.target_codes else 'CASH'})"
            ),
            metadata={
                "completed_trade_date": signal.completed_trade_date,
                "target_codes": list(signal.target_codes),
                "candidate_codes": list(signal.candidate_codes),
                "gross_exposure": signal.gross_exposure,
                "market_is_risk_on": signal.market_is_risk_on,
                "rebalance_band_pct": self.rebalance_policy.band_pct,
                "top_n": self.signal_params.top_n,
                "current_trade_date": current_trade_date,
            },
        )


_BUILTINS_REGISTERED = False


def ensure_builtin_pool_strategy_registrations() -> None:
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return
    register_pool_strategy("dual_momentum", DualMomentumPoolStrategy)
    _BUILTINS_REGISTERED = True


def build_pool_strategy(config: StockPoolConfig) -> PoolLiveStrategy:
    """按注册表构建 live 股票池策略。"""
    return resolve_pool_strategy_factory(config.strategy.name)(config)


__all__ = [
    "DualMomentumPoolStrategy",
    "PoolLiveStrategy",
    "build_pool_strategy",
    "ensure_builtin_pool_strategy_registrations",
    "register_pool_strategy",
    "supported_pool_strategy_names",
    "unregister_pool_strategy",
]
