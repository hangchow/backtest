from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from trading_domain.rebalance import DEFAULT_REBALANCE_BAND_PCT
from .volume import compute_relative_volume, validate_volume_filter


DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_LONG_LOOKBACK_DAYS = 180
DEFAULT_LONG_LOOKBACK_WEIGHT = 0.25
DEFAULT_TOP_N = 1
DEFAULT_VOLUME_WINDOW = 20
DEFAULT_MIN_VOLUME_RATIO = 1.3
MAX_VOLUME_BOOST_RATIO = 1.5
DEFAULT_MARKET_FILTER_WINDOW = 120
DEFAULT_VOLATILITY_WINDOW = 20
DEFAULT_TARGET_ANNUAL_VOL = 0.30
DEFAULT_MAX_GROSS_EXPOSURE = 1.0


@dataclass(frozen=True)
class DualMomentumParams:
    # 这是 backtest/livetrading 共享的唯一参数定义，避免两边各自维护默认值和校验口径。
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    long_lookback_days: int = DEFAULT_LONG_LOOKBACK_DAYS
    long_lookback_weight: float = DEFAULT_LONG_LOOKBACK_WEIGHT
    top_n: int = DEFAULT_TOP_N
    volume_window: int = DEFAULT_VOLUME_WINDOW
    min_volume_ratio: float = DEFAULT_MIN_VOLUME_RATIO
    market_filter_window: int = DEFAULT_MARKET_FILTER_WINDOW
    volatility_window: int = DEFAULT_VOLATILITY_WINDOW
    target_annual_vol: float = DEFAULT_TARGET_ANNUAL_VOL
    max_gross_exposure: float = DEFAULT_MAX_GROSS_EXPOSURE

    @classmethod
    def from_mapping(cls, values: Mapping[str, object] | None = None) -> DualMomentumParams:
        # 配置文件读出来的数值可能是字符串，这里统一做一次类型收敛。
        raw = values or {}
        return cls(
            lookback_days=int(raw.get("lookback_days", DEFAULT_LOOKBACK_DAYS)),
            long_lookback_days=int(raw.get("long_lookback_days", DEFAULT_LONG_LOOKBACK_DAYS)),
            long_lookback_weight=float(raw.get("long_lookback_weight", DEFAULT_LONG_LOOKBACK_WEIGHT)),
            top_n=int(raw.get("top_n", DEFAULT_TOP_N)),
            volume_window=int(raw.get("volume_window", DEFAULT_VOLUME_WINDOW)),
            min_volume_ratio=float(raw.get("min_volume_ratio", DEFAULT_MIN_VOLUME_RATIO)),
            market_filter_window=int(raw.get("market_filter_window", DEFAULT_MARKET_FILTER_WINDOW)),
            volatility_window=int(raw.get("volatility_window", DEFAULT_VOLATILITY_WINDOW)),
            target_annual_vol=float(raw.get("target_annual_vol", DEFAULT_TARGET_ANNUAL_VOL)),
            max_gross_exposure=float(raw.get("max_gross_exposure", DEFAULT_MAX_GROSS_EXPOSURE)),
        )

    def validate(self) -> None:
        validate_dual_momentum_params(
            lookback_days=self.lookback_days,
            long_lookback_days=self.long_lookback_days,
            long_lookback_weight=self.long_lookback_weight,
            top_n=self.top_n,
            volume_window=self.volume_window,
            min_volume_ratio=self.min_volume_ratio,
            market_filter_window=self.market_filter_window,
            volatility_window=self.volatility_window,
            target_annual_vol=self.target_annual_vol,
            max_gross_exposure=self.max_gross_exposure,
        )

    def required_warmup_bars(self) -> int:
        # 供上层直接询问“至少要准备多少根日线”。
        return required_dual_momentum_warmup_bars(params=self)


@dataclass(frozen=True)
class DualMomentumSignal:
    """dual momentum 根据信号窗口产出的目标权重结果。"""
    completed_trade_date: Any
    target_codes: tuple[str, ...]
    target_weights: dict[str, float]
    gross_exposure: float
    market_is_risk_on: bool
    candidate_codes: tuple[str, ...]


def select_target_codes(momentum: pd.Series, top_n: int) -> list[str]:
    # 只保留正动量标的，然后按强弱排序取前 N。
    eligible = momentum.dropna()
    eligible = eligible[eligible > 0]
    if eligible.empty:
        return []
    return eligible.sort_values(ascending=False).head(top_n).index.tolist()


def compute_volume_boost(volume_ratio: pd.Series, min_volume_ratio: float) -> pd.Series:
    # 放量只作为加分项，不作为硬过滤；同时用上限约束避免极端成交量把排序拉得过于失真。
    capped_ratio = volume_ratio.clip(upper=MAX_VOLUME_BOOST_RATIO)
    volume_boost = pd.Series(1.0, index=volume_ratio.index, dtype=float)
    boosted = capped_ratio >= min_volume_ratio
    volume_boost.loc[boosted] = capped_ratio.loc[boosted] / min_volume_ratio
    return volume_boost.where(volume_ratio.notna())


def validate_dual_momentum_params(
    *,
    lookback_days: int,
    long_lookback_days: int,
    long_lookback_weight: float,
    top_n: int,
    volume_window: int,
    min_volume_ratio: float,
    market_filter_window: int,
    volatility_window: int,
    target_annual_vol: float,
    max_gross_exposure: float,
) -> None:
    # 统一参数校验口径，回测和实时策略都复用这里。
    if lookback_days <= 0:
        raise ValueError("lookback-days must be positive")
    if long_lookback_days <= 0:
        raise ValueError("long-lookback-days must be positive")
    if not 0 <= long_lookback_weight <= 1:
        raise ValueError("long-lookback-weight must be within [0, 1]")
    if top_n <= 0:
        raise ValueError("top-n must be positive")
    validate_volume_filter(volume_window, min_volume_ratio)
    if market_filter_window <= 0:
        raise ValueError("market-filter-window must be positive")
    if volatility_window <= 1:
        raise ValueError("volatility-window must be > 1")
    if target_annual_vol <= 0:
        raise ValueError("target-annual-vol must be positive")
    if max_gross_exposure < 1:
        raise ValueError("max-gross-exposure must be >= 1")


def _resolve_dual_momentum_params(
    *,
    params: DualMomentumParams | None,
    lookback_days: int,
    long_lookback_days: int,
    long_lookback_weight: float,
    top_n: int,
    volume_window: int,
    min_volume_ratio: float,
    market_filter_window: int,
    volatility_window: int,
    target_annual_vol: float,
    max_gross_exposure: float,
) -> DualMomentumParams:
    # 上层既可以直接传 params 对象，也可以继续走旧的 keyword 参数形式。
    # 这里把两种入口收敛成一个已校验的参数对象。
    resolved = params or DualMomentumParams(
        lookback_days=lookback_days,
        long_lookback_days=long_lookback_days,
        long_lookback_weight=long_lookback_weight,
        top_n=top_n,
        volume_window=volume_window,
        min_volume_ratio=min_volume_ratio,
        market_filter_window=market_filter_window,
        volatility_window=volatility_window,
        target_annual_vol=target_annual_vol,
        max_gross_exposure=max_gross_exposure,
    )
    resolved.validate()
    return resolved


def required_dual_momentum_signal_bars(
    *,
    params: DualMomentumParams | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    long_lookback_days: int = DEFAULT_LONG_LOOKBACK_DAYS,
    long_lookback_weight: float = DEFAULT_LONG_LOOKBACK_WEIGHT,
    top_n: int = DEFAULT_TOP_N,
    volume_window: int = DEFAULT_VOLUME_WINDOW,
    min_volume_ratio: float = DEFAULT_MIN_VOLUME_RATIO,
    market_filter_window: int = DEFAULT_MARKET_FILTER_WINDOW,
    volatility_window: int = DEFAULT_VOLATILITY_WINDOW,
    target_annual_vol: float = DEFAULT_TARGET_ANNUAL_VOL,
    max_gross_exposure: float = DEFAULT_MAX_GROSS_EXPOSURE,
) -> int:
    resolved = _resolve_dual_momentum_params(
        params=params,
        lookback_days=lookback_days,
        long_lookback_days=long_lookback_days,
        long_lookback_weight=long_lookback_weight,
        top_n=top_n,
        volume_window=volume_window,
        min_volume_ratio=min_volume_ratio,
        market_filter_window=market_filter_window,
        volatility_window=volatility_window,
        target_annual_vol=target_annual_vol,
        max_gross_exposure=max_gross_exposure,
    )
    # 真正能出信号的门槛必须覆盖所有滚动窗口，而不仅仅是短周期动量。
    return max(
        resolved.lookback_days + 1,
        resolved.long_lookback_days + 1 if resolved.long_lookback_weight > 0 else resolved.lookback_days + 1,
        resolved.market_filter_window,
        resolved.volatility_window + 1,
        resolved.volume_window + 1,
    )


def required_dual_momentum_warmup_bars(
    *,
    params: DualMomentumParams | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    long_lookback_days: int = DEFAULT_LONG_LOOKBACK_DAYS,
    long_lookback_weight: float = DEFAULT_LONG_LOOKBACK_WEIGHT,
    top_n: int = DEFAULT_TOP_N,
    volume_window: int = DEFAULT_VOLUME_WINDOW,
    min_volume_ratio: float = DEFAULT_MIN_VOLUME_RATIO,
    market_filter_window: int = DEFAULT_MARKET_FILTER_WINDOW,
    volatility_window: int = DEFAULT_VOLATILITY_WINDOW,
    target_annual_vol: float = DEFAULT_TARGET_ANNUAL_VOL,
    max_gross_exposure: float = DEFAULT_MAX_GROSS_EXPOSURE,
) -> int:
    """计算 dual momentum warm-up 至少要准备的日线根数。"""
    # warm-up 至少要覆盖所有滚动窗口，再额外留一点余量，避免边界日刚好缺数据。
    signal_bars = required_dual_momentum_signal_bars(
        params=params,
        lookback_days=lookback_days,
        long_lookback_days=long_lookback_days,
        long_lookback_weight=long_lookback_weight,
        top_n=top_n,
        volume_window=volume_window,
        min_volume_ratio=min_volume_ratio,
        market_filter_window=market_filter_window,
        volatility_window=volatility_window,
        target_annual_vol=target_annual_vol,
        max_gross_exposure=max_gross_exposure,
    )
    return max(signal_bars, 30) + 5


def build_dual_momentum_signal(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    *,
    params: DualMomentumParams | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    long_lookback_days: int = DEFAULT_LONG_LOOKBACK_DAYS,
    long_lookback_weight: float = DEFAULT_LONG_LOOKBACK_WEIGHT,
    top_n: int = DEFAULT_TOP_N,
    volume_window: int = DEFAULT_VOLUME_WINDOW,
    min_volume_ratio: float = DEFAULT_MIN_VOLUME_RATIO,
    market_filter_window: int = DEFAULT_MARKET_FILTER_WINDOW,
    volatility_window: int = DEFAULT_VOLATILITY_WINDOW,
    target_annual_vol: float = DEFAULT_TARGET_ANNUAL_VOL,
    max_gross_exposure: float = DEFAULT_MAX_GROSS_EXPOSURE,
) -> DualMomentumSignal | None:
    """基于已完成日线窗口计算 dual momentum 目标权重。"""
    # 所有上层调用最终都汇总到这里，先拿到一份已经完成默认值填充和校验的参数对象。
    resolved = _resolve_dual_momentum_params(
        params=params,
        lookback_days=lookback_days,
        long_lookback_days=long_lookback_days,
        long_lookback_weight=long_lookback_weight,
        top_n=top_n,
        volume_window=volume_window,
        min_volume_ratio=min_volume_ratio,
        market_filter_window=market_filter_window,
        volatility_window=volatility_window,
        target_annual_vol=target_annual_vol,
        max_gross_exposure=max_gross_exposure,
    )
    if prices.empty or volumes.empty:
        return None
    if not prices.index.equals(volumes.index) or not prices.columns.equals(volumes.columns):
        raise ValueError("prices and volumes must share the same index and columns")
    if len(prices.index) < required_dual_momentum_signal_bars(params=resolved):
        return None

    top_n = min(resolved.top_n, len(prices.columns))
    # 相对成交量按列分别计算，每个标的只和自己的近期成交量基线比较。
    relative_volume = volumes.apply(lambda column: compute_relative_volume(column, resolved.volume_window))
    idx = len(prices.index) - 1

    # dual momentum 的第一层是相对强弱：短周期为主，长周期作为辅助权重。
    short_momentum = prices.iloc[idx] / prices.iloc[idx - resolved.lookback_days] - 1
    long_momentum = pd.Series(0.0, index=prices.columns, dtype=float)
    if idx >= resolved.long_lookback_days:
        long_momentum = prices.iloc[idx] / prices.iloc[idx - resolved.long_lookback_days] - 1
    blended_momentum = short_momentum * (1 - resolved.long_lookback_weight) + long_momentum * resolved.long_lookback_weight
    # 放量只增强正动量，不让负动量因为放量“变好”。
    volume_weight = compute_volume_boost(relative_volume.iloc[idx], resolved.min_volume_ratio)
    weighted_momentum = blended_momentum.where(blended_momentum > 0) * volume_weight
    candidate_codes = tuple(select_target_codes(weighted_momentum, top_n))

    # dual momentum 的第二层是绝对动量/市场过滤：
    # 股票池整体跌破自身均线时，直接切到现金，不持有风险资产。
    pool_close = prices.mean(axis=1)
    pool_ma = pool_close.rolling(
        window=resolved.market_filter_window,
        min_periods=resolved.market_filter_window,
    ).mean()
    market_is_risk_on = bool(pd.notna(pool_ma.iloc[idx]) and pool_close.iloc[idx] >= pool_ma.iloc[idx])
    target_codes = candidate_codes if market_is_risk_on else ()

    # 第三层是波动率控制：当股票池近期波动过大时，下调总 gross exposure。
    target_vol_multiplier = 1.0
    daily_pool_returns = pool_close.pct_change()
    realized_daily_vol = daily_pool_returns.rolling(
        window=resolved.volatility_window,
        min_periods=resolved.volatility_window,
    ).std()
    if pd.notna(realized_daily_vol.iloc[idx]) and realized_daily_vol.iloc[idx] > 0:
        annualized_vol = float(realized_daily_vol.iloc[idx]) * (252**0.5)
        target_vol_multiplier = min(1.0, resolved.target_annual_vol / annualized_vol)

    # 当前版本仍是等权持仓，只是用 gross_exposure 控制总风险预算。
    gross_exposure = target_vol_multiplier * resolved.max_gross_exposure if target_codes else 0.0
    weight_per_code = gross_exposure / len(target_codes) if target_codes else 0.0
    target_weights = {code: weight_per_code for code in target_codes}

    return DualMomentumSignal(
        completed_trade_date=prices.index[idx],
        target_codes=target_codes,
        target_weights=target_weights,
        gross_exposure=gross_exposure,
        market_is_risk_on=market_is_risk_on,
        candidate_codes=candidate_codes,
    )
