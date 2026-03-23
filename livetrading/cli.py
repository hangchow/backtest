from __future__ import annotations

import argparse
import logging

from .engine import LiveTradingEngine


def parse_args() -> argparse.Namespace:
    """解析 CLI 参数，定位实时行情、历史 warm-up、股票池和交易账户配置文件。"""
    parser = argparse.ArgumentParser(
        description="Run live trading with split quote/history/pool/trade configs, strategy signals, configurable executors, and config hot reload."
    )
    parser.add_argument("--quote-config", required=True, help="Path to the quote-subscription JSON config file.")
    parser.add_argument("--history-config", help="Optional path to the history-broker JSON config file.")
    parser.add_argument("--pool-config", help="Optional path to the stock-pool JSON config file.")
    parser.add_argument("--trade-config", required=True, help="Path to the trade-account JSON config file.")
    return parser.parse_args()


def main() -> int:
    """初始化日志并启动实盘主流程。"""
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    engine = LiveTradingEngine(
        args.quote_config,
        args.trade_config,
        history_config_path=args.history_config,
        pool_config_path=args.pool_config,
    )
    try:
        engine.run()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
    return 0
