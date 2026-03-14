# 美股单标回测（`--codes`）

本文档汇总美股单标在默认参数下的分钟级回测结果。

## 统一回测口径与账户费用

- [回测统一口径（scripts/README.md）](README.md#回测统一口径)
- [账户费用规则（scripts/README.md）](README.md#费用规则futu_alt)

## 结果范围

- 本文档仅保留美股单标结果表；统一回测口径与账户费用请以上方链接为准。

## 默认参数结果

| code | strategy | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | ---: | ---: | ---: | ---: |
| US.MSFT | RSI reversion | 116975.07 | 16.98 | -15.03 | 4300 |
| US.MSFT | EMA cross | 98772.69 | -1.23 | -6.87 | 942 |
| US.MSFT | EMA + RSI | 135930.17 | 35.93 | -4.80 | 2862 |
| US.MSFT | EMA + RSI bull range | 115964.97 | 15.96 | -11.66 | 4714 |
| US.NVDA | RSI reversion | 137748.57 | 37.75 | -18.61 | 4486 |
| US.NVDA | EMA cross | 94341.33 | -5.66 | -12.48 | 1028 |
| US.NVDA | EMA + RSI | 112572.82 | 12.57 | -15.87 | 3438 |
| US.NVDA | EMA + RSI bull range | 121675.65 | 21.68 | -15.87 | 4964 |
| US.GOOG | RSI reversion | 118282.86 | 18.28 | -14.22 | 4322 |
| US.GOOG | EMA cross | 112003.70 | 12.00 | -7.81 | 988 |
| US.GOOG | EMA + RSI | 114388.78 | 14.39 | -6.13 | 2972 |
| US.GOOG | EMA + RSI bull range | 115707.60 | 15.71 | -11.58 | 5074 |
| US.TSLA | RSI reversion | 91670.84 | -8.33 | -33.11 | 4373 |
| US.TSLA | EMA cross | 122998.53 | 23.00 | -9.67 | 952 |
| US.TSLA | EMA + RSI | 128901.81 | 28.90 | -9.16 | 3176 |
| US.TSLA | EMA + RSI bull range | 127930.61 | 27.93 | -20.02 | 4740 |

## 复现命令示例

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py --codes US.MSFT
./.venv/bin/python scripts/backtest_ema_cross.py --codes US.MSFT
./.venv/bin/python scripts/backtest_ema_rsi_combo.py --codes US.MSFT
./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py --codes US.MSFT
```
