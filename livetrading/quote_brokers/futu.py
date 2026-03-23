from __future__ import annotations

import logging
import threading
from typing import Iterable

import pandas as pd

from ..config import RealtimeQuoteBrokerConfig
from ..futu.adapters import iter_kline_bars, iter_quote_updates
from ..futu.runtime import _load_futu_api
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
                    extended_time=self._config.subscribe_extended_time,
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
        for update in iter_quote_updates(frame):
            self._event_sink.on_quote(update)

    def _handle_kline_frame(self, frame: pd.DataFrame) -> None:
        for code, bar in iter_kline_bars(frame):
            self._event_sink.on_bar(code, bar)
