from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
from typing import Any, Iterable, Mapping

import pandas as pd

from ..config import RealtimeQuoteBrokerConfig
from ..models import QuoteUpdate
from .base import QuoteBrokerClient, QuoteBrokerEventSink


class MockRealtimeQuoteClient(QuoteBrokerClient):
    def __init__(self, config: RealtimeQuoteBrokerConfig, event_sink: QuoteBrokerEventSink, logger: logging.Logger) -> None:
        self._config = config
        self._event_sink = event_sink
        self._logger = logger
        self._codes: list[str] = []
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None

    def connect(self, codes: Iterable[str]) -> None:
        with self._lock:
            self.close()
            self._codes = self._normalize_codes(codes)
            self._server = self._build_server()
            server_host, server_port = self._server.server_address[:2]
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                name=f"mock-quote-server-{server_host}:{server_port}",
                daemon=True,
            )
            self._server_thread.start()
            self._event_sink.on_broker_message(
                logging.INFO,
                f"mock realtime quote broker listening at http://{server_host}:{server_port}/push "
                f"codes={','.join(self._codes)}",
            )

    def update_symbols(self, codes: Iterable[str]) -> None:
        with self._lock:
            self._codes = self._normalize_codes(codes)
            self._event_sink.on_broker_message(
                logging.INFO,
                f"mock realtime quote broker updated symbols: {','.join(self._codes)}",
            )

    def close(self) -> None:
        with self._lock:
            server = self._server
            thread = self._server_thread
            self._server = None
            self._server_thread = None
            self._codes = []
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

    def push_bar(self, payload: Mapping[str, Any]) -> bool:
        bar = self._normalize_bar_payload(payload)
        code = str(bar["code"])
        with self._lock:
            subscribed_codes = tuple(self._codes)
        if not subscribed_codes or code not in subscribed_codes:
            self._event_sink.on_broker_message(
                logging.WARNING,
                f"mock realtime quote broker ignored push for unsubscribed code={code}",
            )
            return False

        timestamp = pd.Timestamp(bar["time_key"])
        self._event_sink.on_quote(
            QuoteUpdate(
                code=code,
                timestamp=timestamp,
                last_price=float(bar["close"]),
                volume=float(bar["volume"]),
                turnover=_coerce_optional_float(payload.get("turnover")),
                open_price=float(bar["open"]),
                high_price=float(bar["high"]),
                low_price=float(bar["low"]),
                prev_close_price=_coerce_optional_float(payload.get("prev_close_price")),
                source="mock",
                raw=dict(payload),
            )
        )
        self._event_sink.on_bar(code, bar)
        self._event_sink.on_broker_message(
            logging.INFO,
            f"mock realtime quote broker pushed code={code} time={timestamp} close={bar['close']}",
        )
        return True

    def push_bars(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        items_raw = payload.get("bars", payload)
        if isinstance(items_raw, Mapping):
            items = [items_raw]
        elif isinstance(items_raw, list):
            items = items_raw
        else:
            raise ValueError("payload must be a JSON object or contain bars[]")
        if not items:
            raise ValueError("bars[] must not be empty")

        accepted = 0
        ignored = 0
        for item in items:
            if not isinstance(item, Mapping):
                raise ValueError("each bar payload must be a JSON object")
            if self.push_bar(item):
                accepted += 1
            else:
                ignored += 1
        return {
            "accepted": accepted,
            "ignored": ignored,
            "subscribed_codes": list(self._codes),
        }

    def _build_server(self) -> ThreadingHTTPServer:
        broker = self

        class MockQuotePushServer(ThreadingHTTPServer):
            allow_reuse_address = True

        class MockQuotePushHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != "/health":
                    self._send_json(404, {"error": "not found"})
                    return
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "codes": list(broker._codes),
                    },
                )

            def do_POST(self) -> None:
                if self.path != "/push":
                    self._send_json(404, {"error": "not found"})
                    return
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(400, {"error": "invalid content length"})
                    return
                body = self.rfile.read(content_length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                    if not isinstance(payload, Mapping):
                        raise ValueError("payload must be a JSON object")
                    result = broker.push_bars(payload)
                except Exception as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(200, result)

            def log_message(self, format: str, *args: object) -> None:
                return None

            def _send_json(self, status: int, payload: Mapping[str, Any]) -> None:
                encoded = json.dumps(dict(payload)).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        server = MockQuotePushServer((self._config.host, self._config.port), MockQuotePushHandler)
        server.daemon_threads = True
        return server

    def _normalize_codes(self, codes: Iterable[str]) -> list[str]:
        return sorted({str(code).strip().upper() for code in codes if str(code).strip()})

    def _normalize_bar_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        code = str(payload.get("code", "")).strip().upper()
        if not code:
            raise ValueError("bar.code must not be empty")
        raw_time_key = payload.get("time_key")
        if raw_time_key is None:
            raise ValueError("bar.time_key must not be empty")

        timestamp = pd.Timestamp(raw_time_key)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)

        close = float(payload.get("close"))
        open_price = float(payload.get("open", close))
        high_price = float(payload.get("high", max(open_price, close)))
        low_price = float(payload.get("low", min(open_price, close)))
        volume = float(payload.get("volume", 0.0))
        return {
            "code": code,
            "time_key": timestamp,
            "open": open_price,
            "close": close,
            "high": high_price,
            "low": low_price,
            "volume": volume,
        }


def _coerce_optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        normalized = value.strip().upper()
        if not normalized or normalized == "N/A":
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
