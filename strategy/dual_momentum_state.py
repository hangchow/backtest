from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from livetrading.config import DEFAULT_MARKET
from livetrading.market_hours import market_trade_date_for_timestamp, normalize_market_timestamp


@dataclass(frozen=True)
class CompletedDailyFrames:
    """换日时输出给策略层的已完成日线窗口。"""
    signal_time: pd.Timestamp
    current_trade_date: date
    prices: pd.DataFrame
    volumes: pd.DataFrame


def normalize_daily_history(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    """把不同 provider 的日线格式规整成状态机统一输入。"""
    # 历史日线 warm-up 可能来自不同 provider，这里统一成策略内部的最小字段集合。
    if frame.empty:
        return pd.DataFrame(columns=["trade_date", "close", "volume", "last_bar_time"])
    result = frame.copy()
    if "time_key" not in result.columns:
        raise ValueError(f"daily history for {code} must include time_key")
    result["time_key"] = pd.to_datetime(result["time_key"])
    result["time_key"] = result["time_key"].map(lambda value: normalize_market_timestamp(value, DEFAULT_MARKET).tz_localize(None))
    # trade_date 统一按市场本地时区计算，避免带时区的时间戳直接取 .date() 时跨天错位。
    result["trade_date"] = result["time_key"].map(lambda value: market_trade_date_for_timestamp(value, DEFAULT_MARKET))
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    result["volume"] = pd.to_numeric(result.get("volume", 0.0), errors="coerce").fillna(0.0)
    result["last_bar_time"] = result["time_key"]
    result = result[["trade_date", "close", "volume", "last_bar_time"]]
    result = result.dropna(subset=["trade_date", "close"])
    result = result.sort_values("trade_date").drop_duplicates(subset=["trade_date"], keep="last")
    return result.reset_index(drop=True)


class DualMomentumDailyState:
    def __init__(self, codes: tuple[str, ...], warmup_bars: int) -> None:
        self._codes = codes
        self._warmup_bars = warmup_bars
        self._daily_histories = {
            code: pd.DataFrame(columns=["trade_date", "close", "volume", "last_bar_time"]) for code in codes
        }
        self._current_trade_date: date | None = None
        self._last_emitted_trade_date: date | None = None

    def bootstrap(self, histories: dict[str, pd.DataFrame]) -> None:
        """用 warm-up 日线初始化每个股票的日频历史状态。"""
        for code in self._codes:
            history = normalize_daily_history(histories.get(code, pd.DataFrame()), code)
            self._daily_histories[code] = history.tail(self._warmup_bars).reset_index(drop=True)
        max_date = None
        for history in self._daily_histories.values():
            if history.empty:
                continue
            trade_date = history.iloc[-1]["trade_date"]
            if max_date is None or trade_date > max_date:
                max_date = trade_date
        # warm-up 最后一日就是状态机眼里的“当前交易日”基线。
        self._current_trade_date = max_date
        self._last_emitted_trade_date = None

    def on_bar(self, code: str, bar: pd.Series | dict[str, Any]) -> CompletedDailyFrames | None:
        """消费一根分钟 bar，必要时在换日时吐出已完成日线窗口。"""
        if code not in self._daily_histories:
            return None

        row = pd.Series(bar)
        # 状态机内部统一使用“市场本地 naive 时间”，和 mock quote broker 的归一化口径保持一致。
        timestamp = normalize_market_timestamp(row["time_key"], DEFAULT_MARKET).tz_localize(None)
        trade_date = market_trade_date_for_timestamp(timestamp, DEFAULT_MARKET)
        completed = None
        # 关键顺序：
        # 1. 先判断是否换日，并吐出“上一交易日已完成窗口”
        # 2. 再把当前 bar 合并到当天日线
        # trade_date 先按市场本地时区归属到正确交易日，再做换日判断。
        # 这样 2026-03-13 00:30:00+00:00 这类跨时区输入，不会被误判成 2026-03-13 的新交易日。
        if self._current_trade_date is not None and trade_date > self._current_trade_date:
            completed = self._emit_completed_frames(signal_time=timestamp, current_trade_date=trade_date)
        self._current_trade_date = trade_date
        self._update_daily_bar(code, timestamp, float(row["close"]), float(row.get("volume", 0.0)))
        return completed

    def _emit_completed_frames(
        self,
        *,
        signal_time: pd.Timestamp,
        current_trade_date: date,
    ) -> CompletedDailyFrames | None:
        """在进入新交易日时，输出上一交易日前的完整价格/成交量窗口。"""
        # 同一个 current_trade_date 只允许发一次，避免同一天多只股票的首根 bar 重复触发调仓。
        if self._last_emitted_trade_date == current_trade_date:
            return None
        prices, volumes = self._build_completed_frames(current_trade_date=current_trade_date)
        self._last_emitted_trade_date = current_trade_date
        return CompletedDailyFrames(
            signal_time=signal_time,
            current_trade_date=current_trade_date,
            prices=prices,
            volumes=volumes,
        )

    def _update_daily_bar(self, code: str, timestamp: pd.Timestamp, close: float, volume: float) -> None:
        """把分钟 bar 合并到对应交易日的日频聚合状态。"""
        history = self._daily_histories[code]
        trade_date = market_trade_date_for_timestamp(timestamp, DEFAULT_MARKET)
        if history.empty or trade_date > history.iloc[-1]["trade_date"]:
            next_row = pd.DataFrame(
                [
                    {
                        "trade_date": trade_date,
                        "close": close,
                        "volume": max(0.0, volume),
                        "last_bar_time": timestamp,
                    }
                ]
            )
            history = pd.concat([history, next_row], ignore_index=True)
        else:
            idx = history.index[history["trade_date"] == trade_date]
            if len(idx) == 0:
                next_row = pd.DataFrame(
                    [
                        {
                            "trade_date": trade_date,
                            "close": close,
                            "volume": max(0.0, volume),
                            "last_bar_time": timestamp,
                        }
                    ]
                )
                history = pd.concat([history, next_row], ignore_index=True)
            else:
                row_index = idx[-1]
                last_bar_time = history.at[row_index, "last_bar_time"]
                # 同一天里，close 始终覆盖成“最新一分钟的 close”；
                # volume 则持续累加。这样文档里 15:59 的那次 push 就能改写当天最终收盘结构。
                history.at[row_index, "close"] = close
                if pd.isna(last_bar_time) or pd.Timestamp(last_bar_time) < timestamp:
                    history.at[row_index, "volume"] = float(history.at[row_index, "volume"]) + max(0.0, volume)
                    history.at[row_index, "last_bar_time"] = timestamp
        self._daily_histories[code] = history.sort_values("trade_date").tail(self._warmup_bars).reset_index(drop=True)

    def _build_completed_frames(self, *, current_trade_date: date) -> tuple[pd.DataFrame, pd.DataFrame]:
        """组装当前可用于出信号的 completed prices/volumes 窗口。"""
        price_map: dict[str, pd.Series] = {}
        volume_map: dict[str, pd.Series] = {}
        for code, history in self._daily_histories.items():
            # 这里明确排除 current_trade_date，只把“已经收完盘的日线”交给策略层。
            completed = history[history["trade_date"] < current_trade_date]
            if completed.empty:
                continue
            price_map[code] = pd.Series(completed["close"].to_numpy(), index=completed["trade_date"].tolist())
            volume_map[code] = pd.Series(completed["volume"].to_numpy(), index=completed["trade_date"].tolist())
        if not price_map or not volume_map:
            return pd.DataFrame(), pd.DataFrame()
        prices = pd.DataFrame(price_map).sort_index()
        volumes = pd.DataFrame(volume_map).sort_index()
        return prices, volumes
