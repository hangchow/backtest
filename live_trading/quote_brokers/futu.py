from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
from typing import Any, Iterable

import pandas as pd

from ..config import RealtimeQuoteBrokerConfig
from ..models import QuoteUpdate
from .base import QuoteBrokerClient, QuoteBrokerEventSink


class FutuRealtimeQuoteClient(QuoteBrokerClient):
    def __init__(self, config: RealtimeQuoteBrokerConfig, event_sink: QuoteBrokerEventSink, logger: logging.Logger) -> None:
        self._config = config
        self._event_sink = event_sink
        self._logger = logger
        self._quote_ctx = None
        self._futu = None
        self._codes: list[str] = []
        self._lock = threading.RLock()

    def connect(self, codes: Iterable[str]) -> None:
        with self._lock:
            self.close()
            self._futu = _load_futu_api()
            self._quote_ctx = self._futu["OpenQuoteContext"](host=self._config.host, port=self._config.port)
            self._quote_ctx.set_handler(self._build_quote_handler())
            self._quote_ctx.set_handler(self._build_kline_handler())
            self._quote_ctx.start()
        self.update_symbols(codes)

    def update_symbols(self, codes: Iterable[str]) -> None:
        with self._lock:
            if self._quote_ctx is None or self._futu is None:
                raise RuntimeError("Futu realtime quote broker is not connected")

            target_codes = sorted({str(code).strip().upper() for code in codes if str(code).strip()})
            if self._codes:
                ret, data = self._quote_ctx.unsubscribe(self._codes, [self._futu["SubType"].QUOTE, self._futu["SubType"].K_1M])
                if ret != self._futu["RET_OK"]:
                    self._event_sink.on_broker_message(logging.WARNING, f"quote unsubscribe failed: {data}")

            if target_codes:
                ret, data = self._quote_ctx.subscribe(
                    target_codes,
                    [self._futu["SubType"].QUOTE, self._futu["SubType"].K_1M],
                    is_first_push=False,
                    subscribe_push=True,
                    extended_time=self._config.extended_time,
                )
                if ret != self._futu["RET_OK"]:
                    raise RuntimeError(f"quote subscribe failed: {data}")

            self._codes = target_codes

    def close(self) -> None:
        with self._lock:
            quote_ctx = self._quote_ctx
            self._quote_ctx = None
            self._codes = []
            if quote_ctx is not None:
                try:
                    quote_ctx.close()
                except Exception as exc:
                    self._event_sink.on_broker_message(logging.WARNING, f"quote context close failed: {exc}")

    def _build_quote_handler(self):
        futu = self._futu
        broker = self

        class QuoteHandler(futu["StockQuoteHandlerBase"]):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code != futu["RET_OK"]:
                    broker._event_sink.on_broker_message(logging.ERROR, f"quote push error: {content}")
                    return ret_code, content
                broker._handle_quote_frame(content)
                return ret_code, content

        return QuoteHandler()

    def _build_kline_handler(self):
        futu = self._futu
        broker = self

        class KlineHandler(futu["CurKlineHandlerBase"]):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code != futu["RET_OK"]:
                    broker._event_sink.on_broker_message(logging.ERROR, f"kline push error: {content}")
                    return ret_code, content
                broker._handle_kline_frame(content)
                return ret_code, content

        return KlineHandler()

    def _handle_quote_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        for row in frame.itertuples(index=False):
            timestamp = pd.Timestamp(f"{row.data_date} {row.data_time}")
            self._event_sink.on_quote(
                QuoteUpdate(
                    code=str(row.code),
                    timestamp=timestamp,
                    last_price=float(row.last_price),
                    volume=float(row.volume) if not pd.isna(row.volume) else None,
                    turnover=float(row.turnover) if not pd.isna(row.turnover) else None,
                    open_price=float(row.open_price) if not pd.isna(row.open_price) else None,
                    high_price=float(row.high_price) if not pd.isna(row.high_price) else None,
                    low_price=float(row.low_price) if not pd.isna(row.low_price) else None,
                    prev_close_price=float(row.prev_close_price) if not pd.isna(row.prev_close_price) else None,
                    source="quote",
                )
            )

    def _handle_kline_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        normalized = frame.copy()
        normalized["time_key"] = pd.to_datetime(normalized["time_key"])
        for row in normalized.sort_values("time_key").itertuples(index=False):
            self._event_sink.on_bar(
                str(row.code),
                {
                    "code": str(row.code),
                    "time_key": pd.Timestamp(row.time_key),
                    "open": float(row.open),
                    "close": float(row.close),
                    "high": float(row.high),
                    "low": float(row.low),
                    "volume": float(row.volume) if not pd.isna(row.volume) else 0.0,
                },
            )


def _load_futu_api() -> dict[str, Any]:
    runtime_home = Path.cwd() / ".futu_runtime"
    runtime_home.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(runtime_home)
    from futu import (
        Currency,
        CurKlineHandlerBase,
        KLType,
        OpenQuoteContext,
        OpenSecTradeContext,
        RET_OK,
        StockQuoteHandlerBase,
        SubType,
        TradeDealHandlerBase,
        TradeOrderHandlerBase,
        TrdEnv,
        TrdMarket,
    )

    return {
        "Currency": Currency,
        "CurKlineHandlerBase": CurKlineHandlerBase,
        "KLType": KLType,
        "OpenQuoteContext": OpenQuoteContext,
        "OpenSecTradeContext": OpenSecTradeContext,
        "RET_OK": RET_OK,
        "StockQuoteHandlerBase": StockQuoteHandlerBase,
        "SubType": SubType,
        "TradeDealHandlerBase": TradeDealHandlerBase,
        "TradeOrderHandlerBase": TradeOrderHandlerBase,
        "TrdEnv": TrdEnv,
        "TrdMarket": TrdMarket,
    }
