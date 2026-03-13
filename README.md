# Backtest

## 项目概览
这个项目基于港美股样本股票的1分钟K线数据，做单标与股票池的量化策略回测。

## 环境准备
在仓库根目录执行：

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```
### 回测数据
- 数据目录：`data/<股票代码>/`，如`data/HK.00700/`、`data/US.MSFT/`
- 数据文件格式：`<股票代码>_YYYY-MM-DD.csv`
- 数据文件字段：`time_key, open, close, high, low, volume`，每分钟一行
- 回测脚本本身只读取本地 `data/` 目录下的 CSV，不依赖外部服务。

## 已知缺陷和风险提示
- 没有加入手续费、平台费、印花税、滑点。
- 默认按分钟收盘价成交，真实成交未必能拿到这个价格。
- 没有处理港股整手限制，回测里允许按股数买卖。
- 没有处理停牌、除权除息、公司行为等更复杂情况。
- 样本仍然偏少，结论很容易被个股风格主导。
- 文档里的高收益结果不代表可实盘复制。
- 交易次数很多，加入真实费用后，收益会显著下降。
- 使用分钟级数据做高频触发时，执行延迟和滑点会非常敏感。
- 样本内最优参数，未来很可能失效。

## 建议的下一步
- 加入港股手续费、交易征费、印花税。
- 增加整手限制和现金不足约束。
- 把当前单段窗口扩展成更完整的滚动样本外测试。
- 把交易明细、权益曲线、回撤曲线导出。
- 持续扩大标的范围，降低策略被个股风格主导的风险。

## 目录入口
- [scripts 目录说明](scripts/README.md)
- [RSI 策略说明](scripts/README_backtest_rsi_reversion.md)
- [EMA 策略说明](scripts/README_backtest_ema_cross.md)
- [EMA + RSI 策略说明](scripts/README_backtest_ema_rsi_combo.md)
- [优化版 EMA + RSI 策略说明](scripts/README_backtest_ema_rsi_bull_range.md)
- [Dual Momentum 策略说明](scripts/README_backtest_dual_momentum.md)
- [港美股单股回测](scripts/README_backtest_single_symbol.md)
- [港股股票池回测](scripts/README_backtest_hk_stock_pool.md)
- [美股股票池回测](scripts/README_backtest_us_stock_pool.md)
- [tests 目录说明](tests/README.md)
- [Futu 抓取说明](tests/README_fetch_futu_1m.md)
- [Polygon 抓取说明](tests/README_fetch_polygon_1m.md)
- [ValueSider 抓取说明](tests/README_valuesider_holdings.md)
