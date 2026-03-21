from __future__ import annotations

import pandas as pd

from ..futu.runtime import _load_futu_api
from .common import HISTORY_COLUMNS, CachedRemoteDailyHistoryProvider


class FutuDailyHistoryProvider(CachedRemoteDailyHistoryProvider):
    def _fetch_remote_daily_history(self, code: str, bars: int) -> pd.DataFrame:
        if self._remote_daily_fetcher is not None:
            return self._remote_daily_fetcher(code, bars)

        futu = _load_futu_api()
        if not self._config.host or self._config.port is None:
            raise ValueError("futu history broker requires host and port")
        expected_latest_trade_date = self._expected_latest_trade_date()
        request_bars = min(bars + 1, 1000) if expected_latest_trade_date is not None else bars
        quote_ctx = futu["OpenQuoteContext"](host=self._config.host, port=self._config.port)
        try:
            ret, data = quote_ctx.get_cur_kline(code, request_bars, ktype=futu["KLType"].K_DAY)
        finally:
            quote_ctx.close()
        if ret != futu["RET_OK"]:
            self._logger.warning("get_cur_kline failed for %s: %s", code, data)
            return pd.DataFrame(columns=HISTORY_COLUMNS)

        history = data.copy()
        history["time_key"] = pd.to_datetime(history["time_key"])
        history = history.sort_values("time_key").drop_duplicates(subset=["time_key"], keep="last").reset_index(drop=True)
        history = history[HISTORY_COLUMNS]
        if expected_latest_trade_date is not None:
            trimmed = history.loc[history["time_key"].dt.date <= expected_latest_trade_date].reset_index(drop=True)
            if len(trimmed) != len(history):
                self._logger.info(
                    "trimmed in-progress futu daily bar code=%s expected_latest=%s returned_rows=%d kept_rows=%d",
                    code,
                    expected_latest_trade_date,
                    len(history),
                    len(trimmed),
                )
            history = trimmed
        return history.tail(bars).reset_index(drop=True)
