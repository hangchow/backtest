from __future__ import annotations

import pandas as pd


def validate_volume_filter(volume_window: int, min_volume_ratio: float) -> None:
    if volume_window <= 0:
        raise ValueError("volume-window must be positive")
    if min_volume_ratio <= 0:
        raise ValueError("min-volume-ratio must be positive")


def compute_relative_volume(volume: pd.Series, volume_window: int) -> pd.Series:
    validate_volume_filter(volume_window, 1e-9)
    baseline = volume.shift(1).rolling(window=volume_window, min_periods=1).mean()
    relative_volume = (volume / baseline).replace([float("inf"), float("-inf")], pd.NA)
    relative_volume = relative_volume.where(volume.notna(), pd.NA)
    relative_volume = relative_volume.mask(volume.notna() & baseline.isna(), 1.0)
    return pd.to_numeric(relative_volume, errors="coerce")


def compute_volume_scale(
    volume_ratio: float,
    min_volume_ratio: float,
    min_scale: float = 0.5,
    max_scale: float = 1.25,
) -> float:
    validate_volume_filter(1, min_volume_ratio)
    if min_scale <= 0 or max_scale <= 0 or min_scale > max_scale:
        raise ValueError("volume scale bounds must be positive and ordered")
    if pd.isna(volume_ratio) or volume_ratio <= 0:
        return float(min_scale)
    normalized_ratio = float(volume_ratio) / min_volume_ratio
    return max(min_scale, min(max_scale, normalized_ratio))
