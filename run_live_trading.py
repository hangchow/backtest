#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from live_trading import LiveTradingEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run dry-run live trading with split quote/trade configs, strategy signals, and config hot reload."
    )
    parser.add_argument("--quote-config", required=True, help="Path to the quote-subscription JSON config file.")
    parser.add_argument("--trade-config", required=True, help="Path to the trade-accounts JSON config file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    engine = LiveTradingEngine(args.quote_config, args.trade_config)
    try:
        engine.run()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
