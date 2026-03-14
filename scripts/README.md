# scripts 目录文档

本文档用于维护 `scripts/` 下股票池回测的**统一口径**（回测参数与账户费用），作为相关结果文档更新时的基线约束。

相关文档：

- [港股股票池回测结果与分析](README_backtest_hk_stock_pool.md)
- [美股股票池回测结果与分析](README_backtest_us_stock_pool.md)
- [港股单标回测说明](README_backtest_single_symbol_hk.md)
- [美股单标回测说明](README_backtest_single_symbol_us.md)
- [RSI reversion 策略说明](README_backtest_rsi_reversion.md)
- [EMA cross 策略说明](README_backtest_ema_cross.md)
- [EMA + RSI 策略说明](README_backtest_ema_rsi_combo.md)
- [EMA + RSI bull range 策略说明](README_backtest_ema_rsi_bull_range.md)
- [dual momentum 策略说明](README_backtest_dual_momentum.md)

## 回测统一口径

- 数据目录：`data/`
- 初始资金：`港股：800000港币` `美股：100000美元`
- 持仓上限：`--max-open-positions -1`
- 默认允许隔夜持仓（未启用 `--flat-at-close`）
- 费用：启用 `--fee-account futu_alt`（港美股统一按该账户收费）
- 证券类型：`stock`（默认）

## 费用规则（`futu_alt`）

### 港股

- 佣金：`0.03% * 成交金额`，每笔最低 `3 HKD`
- 平台使用费：每笔 `15 HKD`
- 交易系统使用费：`0`
- 交收费：`0.0042% * 成交金额`
- 印花税：`0.1% * 成交金额`，每笔最低 `1 HKD`（ETF/涡轮/牛熊证豁免）
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

