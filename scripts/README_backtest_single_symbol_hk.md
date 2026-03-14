# 港股单标回测（`--codes`）

本文档汇总港股单标在默认参数下的回测结果（含 4 个分钟策略 + 1 个 dual momentum 日频策略）。

## 统一回测口径与账户费用

- [回测统一口径（scripts/README.md）](README.md#回测统一口径)
- [账户费用规则（scripts/README.md）](README.md#费用规则futu_alt)

## 结果范围

- 本文档仅保留港股单标结果表；统一回测口径与账户费用请以上方链接为准。
- dual momentum 脚本当前无 `--fee-account` 参数，其结果按脚本现有逻辑计算（与分钟策略口径不同）。

## 默认参数结果

| code | strategy | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | ---: | ---: | ---: | ---: |
| HK.00700 | RSI reversion | 366.15 | -99.63 | -99.63 | 1810 |
| HK.00700 | EMA cross | 17109.99 | -82.89 | -83.70 | 1522 |
| HK.00700 | EMA + RSI | 363.32 | -99.64 | -99.64 | 1710 |
| HK.00700 | EMA + RSI bull range | 353.76 | -99.65 | -99.65 | 1752 |
| HK.00700 | dual momentum | 143059.00 | 43.06 | -22.60 | 30 |
| HK.09988 | RSI reversion | 84.36 | -99.92 | -99.92 | 1748 |
| HK.09988 | EMA cross | 15829.87 | -84.17 | -84.54 | 1532 |
| HK.09988 | EMA + RSI | 87.06 | -99.91 | -99.91 | 1790 |
| HK.09988 | EMA + RSI bull range | 65.97 | -99.93 | -99.93 | 1768 |
| HK.09988 | dual momentum | 125914.70 | 25.91 | -35.74 | 20 |
| HK.00005 | RSI reversion | 56.52 | -99.94 | -99.94 | 1898 |
| HK.00005 | EMA cross | 14053.91 | -85.95 | -86.31 | 1737 |
| HK.00005 | EMA + RSI | 62.71 | -99.94 | -99.94 | 1920 |
| HK.00005 | EMA + RSI bull range | 53.52 | -99.95 | -99.95 | 1894 |
| HK.00005 | dual momentum | 191522.40 | 91.52 | -18.75 | 13 |

## 复现命令示例

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py --codes HK.00700 --fee-account futu_alt --show-trades 0
./.venv/bin/python scripts/backtest_ema_cross.py --codes HK.00700 --fee-account futu_alt --show-trades 0
./.venv/bin/python scripts/backtest_ema_rsi_combo.py --codes HK.00700 --fee-account futu_alt --show-trades 0
./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py --codes HK.00700 --fee-account futu_alt --show-trades 0
./.venv/bin/python scripts/backtest_dual_momentum.py --codes HK.00700 --show-trades 0
```
