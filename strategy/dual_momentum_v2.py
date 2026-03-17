from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .volume import compute_relative_volume


@dataclass(frozen=True)
class DualMomentumV2Params:
    lookback_days: int = 40
    long_lookback_days: int = 120
    momentum_skip_days: int = 5
    long_lookback_weight: float = 0.35
    top_n: int = 2
    volume_window: int = 20
    min_volume_ratio: float = 1.0
    market_filter_window: int = 80
    market_trend_window: int = 20
    asset_filter_window: int = 60
    volatility_window: int = 20
    target_annual_vol: float = 0.35
    max_gross_exposure: float = 1.2


@dataclass(frozen=True)
class DualMomentumV2Signal:
    completed_trade_date: Any
    target_codes: tuple[str, ...]
    target_weights: dict[str, float]
    gross_exposure: float


def _inv_vol_weights(asset_returns: pd.DataFrame, codes: list[str], window: int, idx: int) -> dict[str, float]:
    if not codes:
        return {}
    vol = asset_returns[codes].rolling(window=window, min_periods=window).std().iloc[idx]
    inv = 1.0 / vol.clip(lower=1e-6)
    w = inv / inv.sum()
    return {c: float(w[c]) for c in codes if pd.notna(w[c])}


def build_dual_momentum_v2_signal(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    params: DualMomentumV2Params,
) -> DualMomentumV2Signal | None:
    if prices.empty or volumes.empty:
        return None
    if not prices.index.equals(volumes.index) or not prices.columns.equals(volumes.columns):
        raise ValueError("prices and volumes must share index/columns")

    idx = len(prices.index) - 1
    need = max(
        params.long_lookback_days + params.momentum_skip_days + 1,
        params.market_filter_window,
        params.asset_filter_window,
        params.volatility_window + 1,
        params.volume_window + 1,
    )
    if len(prices.index) < need:
        return None

    anchor = idx - params.momentum_skip_days
    short_m = prices.iloc[anchor] / prices.iloc[anchor - params.lookback_days] - 1
    long_m = prices.iloc[anchor] / prices.iloc[anchor - params.long_lookback_days] - 1
    blended = short_m * (1 - params.long_lookback_weight) + long_m * params.long_lookback_weight

    rel_volume = volumes.apply(lambda s: compute_relative_volume(s, params.volume_window)).iloc[idx]
    vol_boost = (rel_volume / max(params.min_volume_ratio, 1e-6)).clip(lower=0.8, upper=1.4)

    asset_ma = prices.rolling(params.asset_filter_window, min_periods=params.asset_filter_window).mean().iloc[idx]
    asset_ok = (prices.iloc[idx] >= asset_ma) & (blended > 0)

    score = (blended * vol_boost).where(asset_ok)
    ranked = score.dropna().sort_values(ascending=False)
    selected = list(ranked.head(min(params.top_n, len(ranked))).index)

    asset_returns = prices.pct_change(fill_method=None)
    pool_returns = asset_returns.mean(axis=1, skipna=True)
    pool_index = (1.0 + pool_returns.fillna(0.0)).cumprod()
    pool_ma = pool_index.rolling(params.market_filter_window, min_periods=params.market_filter_window).mean().iloc[idx]
    pool_trend = pool_index.iloc[idx] / pool_index.iloc[idx - params.market_trend_window] - 1
    risk_on = pd.notna(pool_ma) and pool_index.iloc[idx] >= pool_ma and pool_trend > 0

    target_codes = tuple(selected) if risk_on else ()
    if not target_codes:
        return DualMomentumV2Signal(prices.index[idx], (), {}, 0.0)

    basket_returns = asset_returns[list(target_codes)].mean(axis=1, skipna=True)
    rvol = basket_returns.rolling(params.volatility_window, min_periods=params.volatility_window).std().iloc[idx]
    vol_mult = 1.0
    if pd.notna(rvol) and rvol > 0:
        vol_mult = min(1.0, params.target_annual_vol / (float(rvol) * (252**0.5)))
    gross = vol_mult * params.max_gross_exposure

    rel_w = _inv_vol_weights(asset_returns, list(target_codes), params.volatility_window, idx)
    if not rel_w:
        equal = gross / len(target_codes)
        weights = {c: equal for c in target_codes}
    else:
        weights = {c: gross * rel_w[c] for c in target_codes}
    return DualMomentumV2Signal(prices.index[idx], target_codes, weights, gross)
