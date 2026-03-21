from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Mapping

import pandas as pd


class DailyHistoryProvider(ABC):
    @abstractmethod
    def fetch_daily_histories(
        self,
        codes: Iterable[str],
        daily_warmup_bars: Mapping[str, int],
    ) -> dict[str, pd.DataFrame]:
        """为股票池拉取 warm-up 所需的日线窗口。"""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
