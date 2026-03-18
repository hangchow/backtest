from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Protocol

import pandas as pd

from ..models import QuoteUpdate


class QuoteBrokerEventSink(Protocol):
    def on_quote(self, update: QuoteUpdate) -> None:
        raise NotImplementedError

    def on_bar(self, code: str, bar: pd.Series | dict[str, Any]) -> None:
        raise NotImplementedError

    def on_broker_message(self, level: int, message: str) -> None:
        raise NotImplementedError


class QuoteBrokerClient(ABC):
    @abstractmethod
    def connect(self, codes: Iterable[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_symbols(self, codes: Iterable[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
