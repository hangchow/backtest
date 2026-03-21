from __future__ import annotations

import os
from pathlib import Path
from typing import Any


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
