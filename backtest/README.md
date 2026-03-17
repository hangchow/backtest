# Backtest 项目说明

本文档用于统一维护回测相关的项目概览、文档入口、回测参数口径与账户费用。

## 项目概览

这个项目基于港美股样本股票的 `1分钟 K 线` 与 `日 K 线` 数据，做单标与股票池的量化策略回测，并提供一个基于 `Futu OpenD` 的实时信号 dry-run 框架。

## 回测数据

- 分钟级目录：`kline_minute/<股票代码>/`，如 `kline_minute/HK.00700/`、`kline_minute/US.MSFT/`
- 日线目录：`kline_day/<股票代码>/`，如 `kline_day/HK.00700/`、`kline_day/US.MSFT/`
- 分钟级文件格式：按交易日拆分，文件名为 `<股票代码>_YYYY-MM-DD.csv`
- 日线文件格式：按自然周拆分，文件名为 `<股票代码>_YYYY-MM-DD.csv`，其中日期是该周周一
- 两类 CSV 字段统一为：`time_key, open, close, high, low, volume`
- `dual_momentum` 从本地 `kline_day/` 读取日线数据
- `dual_momentum_ema_rsi_hybrid` 同时读取 `kline_day/` + `kline_minute/`（日线选股 + 分钟择时）
- 其他分钟策略从本地 `kline_minute/` 读取分钟数据
- 回测脚本本身只读取本地 CSV，不依赖外部服务

## 文档入口

- [港股股票池回测结果与分析](../docs/README_backtest_pool_hk.md)
- [美股股票池回测结果与分析](../docs/README_backtest_pool_us.md)
- [港股单标回测说明](../docs/README_backtest_single_symbol_hk.md)
- [美股单标回测说明](../docs/README_backtest_single_symbol_us.md)
- [RSI reversion 策略说明](../docs/README_backtest_rsi_reversion.md)
- [EMA cross 策略说明](../docs/README_backtest_ema_cross.md)
- [EMA + RSI 策略说明](../docs/README_backtest_ema_rsi_combo.md)
- [EMA + RSI bull range 策略说明](../docs/README_backtest_ema_rsi_bull_range.md)
- [分钟策略横向对比工具说明](../docs/README_backtest_compare_backtests.md)
- [dual momentum 策略说明](../docs/README_backtest_dual_momentum.md)
- [dual momentum + EMA + RSI hybrid 策略说明](../docs/README_backtest_dual_momentum_ema_rsi_hybrid.md)
- [实时交易信号框架说明](../README.md)
- [tests 目录说明](../tests/README.md)
- [Futu 抓取说明](../docs/README_fetch_futu_1m.md)
- [Polygon 日线抓取说明](../docs/README_fetch_polygon_day.md)
- [Polygon 抓取说明](../docs/README_fetch_polygon_1m.md)

## 回测统一口径

- 回测数据目录：`kline_minute/` `kline_day/`
- 预热数据时间范围：`2025-03-06` 之前的数据
- 回测数据时间范围：`2025-03-07` 到 `2026-03-06`
- 初始资金：`港股：800000港币` `美股：100000美元`
- 市场参数：所有 backtest 脚本都必须显式传入 `--market HK|US`；不会再从代码或目录名自动推断
- 持仓上限：`--max-open-positions -1`
- 默认允许隔夜持仓：未启用 `--flat-at-close`
- 费用：启用 `--fee-account futu_alt`
- 证券类型：`stock`

## 费用规则（`futu_alt`）

### 港股

- 佣金：`0.03% * 成交金额`，每笔最低 `3 HKD`
- 平台使用费：每笔 `15 HKD`
- 交易系统使用费：`0`
- 交收费：`0.0042% * 成交金额`
- 印花税：`0.1% * 成交金额`，每笔最低 `1 HKD`，ETF/涡轮/牛熊证豁免
- 交易费：`0.00565% * 成交金额`，每笔最低 `0.01 HKD`
- 证监会征费：`0.0027% * 成交金额`，每笔最低 `0.01 HKD`
- 财汇局征费：`0.00015% * 成交金额`

### 美股

- 佣金：`0.0049 USD/股`，每笔最低 `0.99 USD`，最高 `0.5% * 成交金额`
- 平台使用费：`0.005 USD/股`，每笔最低 `1 USD`，最高 `0.5% * 成交金额`
- 交收费：`0.003 USD/股`
- 证监会规费：`0`
- 交易活动费：`0.000195 USD/股`，仅卖出收取，最低 `0.01 USD`，最高 `9.79 USD`
- 综合审计跟踪监管费：`0`

## 已知缺陷和风险提示

- 没有加入手续费、平台费、印花税、滑点
- 默认按分钟收盘价成交，真实成交未必能拿到这个价格
- 没有处理港股整手限制，回测里允许按股数买卖
- 没有处理停牌、除权除息、公司行为等更复杂情况
- 样本仍然偏少，结论很容易被个股风格主导
- 文档里的高收益结果不代表可实盘复制
- 交易次数很多，加入真实费用后，收益会显著下降
- 使用分钟级数据做高频触发时，执行延迟和滑点会非常敏感
- 样本内最优参数，未来很可能失效

## 建议的下一步

- 加入港股手续费、交易征费、印花税
- 增加整手限制和现金不足约束
- 把当前单段窗口扩展成更完整的滚动样本外测试
- 把交易明细、权益曲线、回撤曲线导出
- 持续扩大标的范围，降低策略被个股风格主导的风险
