# scripts 回测口径（含账户收费）

本文档给出 `scripts/` 下分钟级策略在**股票池模式**中的统一回测口径，并记录加入账户收费后的最新结果。

相关文档：

- [港股单标回测说明](README_backtest_single_symbol_hk.md)
- [美股单标回测说明](README_backtest_single_symbol_us.md)

## 回测口径

- 数据目录：`data/`
- 初始资金：`100000`
- 持仓上限：`--max-open-positions 2`
- 默认允许隔夜持仓（未启用 `--flat-at-close`）
- 交易价格：分钟收盘价
- 费用：启用 `--fee-account futu_alt`（你提供的该账户港美股收费）
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

## 港股股票池回测（含收费）

股票池：`HK.00700`、`HK.09988`、`HK.00005`

| strategy | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | ---: | ---: | ---: | ---: |
| RSI reversion | 188.59 | -99.81% | -99.81% | 2874 |
| EMA cross | 11537.15 | -88.46% | -88.91% | 1849 |
| EMA + RSI | 203.43 | -99.80% | -99.80% | 2738 |
| EMA + RSI bull range | 192.89 | -99.81% | -99.81% | 2614 |

## 美股股票池回测（含收费）

股票池：`US.MSFT`、`US.NVDA`、`US.GOOG`、`US.TSLA`

| strategy | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | ---: | ---: | ---: | ---: |
| RSI reversion | 92994.63 | -7.01% | -23.46% | 12967 |
| EMA cross | 117439.02 | 17.44% | -19.51% | 2446 |
| EMA + RSI | 94390.68 | -5.61% | -13.72% | 11256 |
| EMA + RSI bull range | 81676.17 | -18.32% | -19.14% | 17940 |

## 复现命令

```bash
python scripts/backtest_rsi_reversion.py --codes HK.00700 HK.09988 HK.00005 --fee-account futu_alt --show-trades 0
python scripts/backtest_ema_cross.py --codes HK.00700 HK.09988 HK.00005 --fee-account futu_alt --show-trades 0
python scripts/backtest_ema_rsi_combo.py --codes HK.00700 HK.09988 HK.00005 --fee-account futu_alt --show-trades 0
python scripts/backtest_ema_rsi_bull_range.py --codes HK.00700 HK.09988 HK.00005 --fee-account futu_alt --show-trades 0

python scripts/backtest_rsi_reversion.py --codes US.MSFT US.NVDA US.GOOG US.TSLA --fee-account futu_alt --show-trades 0
python scripts/backtest_ema_cross.py --codes US.MSFT US.NVDA US.GOOG US.TSLA --fee-account futu_alt --show-trades 0
python scripts/backtest_ema_rsi_combo.py --codes US.MSFT US.NVDA US.GOOG US.TSLA --fee-account futu_alt --show-trades 0
python scripts/backtest_ema_rsi_bull_range.py --codes US.MSFT US.NVDA US.GOOG US.TSLA --fee-account futu_alt --show-trades 0
```
