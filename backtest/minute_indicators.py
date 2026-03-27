from __future__ import annotations

import pandas as pd


def compute_rsi(series: pd.Series, period: int) -> pd.Series:
    if period <= 0:
        raise ValueError("period must be positive")

    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    no_losses = avg_loss == 0
    no_gains = avg_gain == 0
    rsi = rsi.mask(no_losses, 100.0)
    rsi = rsi.mask(no_gains, 0.0)
    rsi = rsi.mask(no_losses & no_gains, 50.0)
    return rsi.fillna(50.0)
