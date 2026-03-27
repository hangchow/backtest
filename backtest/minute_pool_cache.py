from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.backtest_common import resolve_eval_window
from backtest.minute_indicators import compute_rsi
from strategy.volume import compute_relative_volume


def _prepare_history(history: pd.DataFrame) -> pd.DataFrame:
    prepared = history
    if "trade_date" not in prepared.columns or "is_day_end" not in prepared.columns:
        prepared = history.copy()
        if "trade_date" not in prepared.columns:
            prepared["trade_date"] = prepared["time_key"].dt.date
        if "is_day_end" not in prepared.columns:
            prepared["is_day_end"] = prepared["trade_date"] != prepared["trade_date"].shift(-1)
    return prepared


@dataclass(frozen=True)
class MinuteCodeArrays:
    time_key: pd.DatetimeIndex
    trade_date: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    is_day_end: np.ndarray


@dataclass(frozen=True)
class MinuteTimelineWindow:
    row_indices: np.ndarray
    warmup_start_time: pd.Timestamp
    start_time: pd.Timestamp
    end_time: pd.Timestamp


class MinutePoolFeatureCache:
    def __init__(self, histories: dict[str, pd.DataFrame]) -> None:
        if not histories:
            raise ValueError("histories must not be empty")

        self.codes = sorted(histories)
        prepared_histories = {code: _prepare_history(histories[code]) for code in self.codes}
        all_timestamps = pd.concat(
            [prepared_histories[code]["time_key"] for code in self.codes],
            ignore_index=True,
        )
        self.timeline = pd.DatetimeIndex(all_timestamps.unique()).sort_values()
        self.code_arrays: list[MinuteCodeArrays] = []
        self.row_lookup = np.full((len(self.timeline), len(self.codes)), -1, dtype=np.int32)

        for code_index, code in enumerate(self.codes):
            history = prepared_histories[code]
            time_key = pd.DatetimeIndex(history["time_key"])
            row_positions = self.timeline.get_indexer(time_key)
            self.row_lookup[row_positions, code_index] = np.arange(len(history), dtype=np.int32)
            self.code_arrays.append(
                MinuteCodeArrays(
                    time_key=time_key,
                    trade_date=history["trade_date"].to_numpy(copy=False),
                    close=history["close"].astype(float).to_numpy(copy=False),
                    volume=history["volume"].astype(float).to_numpy(copy=False),
                    is_day_end=history["is_day_end"].astype(bool).to_numpy(copy=False),
                )
            )

        self._ema_cache: dict[int, list[np.ndarray]] = {}
        self._rsi_cache: dict[int, list[np.ndarray]] = {}
        self._volume_ratio_cache: dict[int, list[np.ndarray]] = {}
        self._hybrid_day_end_cache: dict[tuple[int, int, int], dict[str, pd.DataFrame]] = {}

    def resolve_window(
        self,
        eval_start: pd.Timestamp | None = None,
        eval_end: pd.Timestamp | None = None,
    ) -> MinuteTimelineWindow:
        mask, warmup_start_time, start_time, end_time = resolve_eval_window(self.timeline, eval_start, eval_end)
        row_indices = np.flatnonzero(mask)
        return MinuteTimelineWindow(
            row_indices=row_indices,
            warmup_start_time=warmup_start_time,
            start_time=start_time,
            end_time=end_time,
        )

    def ema(self, span: int) -> list[np.ndarray]:
        cached = self._ema_cache.get(span)
        if cached is not None:
            return cached
        computed = [pd.Series(arrays.close).ewm(span=span, adjust=False).mean().to_numpy() for arrays in self.code_arrays]
        self._ema_cache[span] = computed
        return computed

    def rsi(self, period: int) -> list[np.ndarray]:
        cached = self._rsi_cache.get(period)
        if cached is not None:
            return cached
        computed = [compute_rsi(pd.Series(arrays.close), period).to_numpy() for arrays in self.code_arrays]
        self._rsi_cache[period] = computed
        return computed

    def volume_ratio(self, window: int) -> list[np.ndarray]:
        cached = self._volume_ratio_cache.get(window)
        if cached is not None:
            return cached
        computed = [compute_relative_volume(pd.Series(arrays.volume), window).to_numpy() for arrays in self.code_arrays]
        self._volume_ratio_cache[window] = computed
        return computed

    def build_day_end_indicator_frames(
        self,
        *,
        fast_span: int,
        slow_span: int,
        rsi_period: int,
    ) -> dict[str, pd.DataFrame]:
        key = (fast_span, slow_span, rsi_period)
        cached = self._hybrid_day_end_cache.get(key)
        if cached is not None:
            return cached

        ema_fast = self.ema(fast_span)
        ema_slow = self.ema(slow_span)
        rsi_values = self.rsi(rsi_period)
        result: dict[str, pd.DataFrame] = {}
        for code_index, code in enumerate(self.codes):
            arrays = self.code_arrays[code_index]
            mask = arrays.is_day_end
            trade_date = pd.to_datetime(arrays.trade_date[mask])
            result[code] = pd.DataFrame(
                {
                    "close": arrays.close[mask],
                    "ema_fast": ema_fast[code_index][mask],
                    "ema_slow": ema_slow[code_index][mask],
                    "rsi": rsi_values[code_index][mask],
                },
                index=trade_date,
            )

        self._hybrid_day_end_cache[key] = result
        return result
