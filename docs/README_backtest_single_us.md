# 美股单标回测（`--codes`）

本文档汇总美股单标在默认参数下的回测结果（含 4 个分钟策略 + 1 个 dual momentum 日频策略）。

## 统一回测口径与账户费用

- [回测统一口径（backtest/README.md）](../backtest/README.md#回测统一口径)
- [账户费用规则（backtest/README.md）](../backtest/README.md#费用规则futu_alt)

## 结果范围

- 本文档仅保留美股单标结果表；统一回测口径与账户费用请以上方链接为准。
- 所有回测脚本现在都要求显式传入 `--market US`。

## 默认参数结果

| code | strategy | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | ---: | ---: | ---: | ---: |
| US.MSFT | RSI reversion | 100336.72 | 0.34 | -18.05 | 8610 |
| US.MSFT | EMA cross | 87909.61 | -12.09 | -19.95 | 1932 |
| US.MSFT | EMA + RSI | 108458.18 | 8.46 | -17.58 | 5738 |
| US.MSFT | EMA + RSI bull range | 81979.48 | -18.02 | -20.48 | 9552 |
| US.MSFT | dual momentum | 94201.57 | -5.80 | -22.31 | 42 |
| US.NVDA | RSI reversion | 153937.26 | 53.94 | -25.72 | 9022 |
| US.NVDA | EMA cross | 40858.05 | -59.14 | -66.64 | 1914 |
| US.NVDA | EMA + RSI | 83891.73 | -16.11 | -28.96 | 6736 |
| US.NVDA | EMA + RSI bull range | 49676.27 | -50.32 | -55.50 | 9494 |
| US.NVDA | dual momentum | 13452.86 | -86.55 | -92.57 | 44 |
| US.GOOG | RSI reversion | 68742.97 | -31.26 | -42.62 | 8524 |
| US.GOOG | EMA cross | 95918.15 | -4.08 | -24.34 | 1990 |
| US.GOOG | EMA + RSI | 86551.17 | -13.45 | -17.57 | 5980 |
| US.GOOG | EMA + RSI bull range | 69046.84 | -30.95 | -34.94 | 10198 |
| US.GOOG | dual momentum | 192148.40 | 92.15 | -14.99 | 22 |
| US.TSLA | RSI reversion | 80509.85 | -19.49 | -51.37 | 8843 |
| US.TSLA | EMA cross | 162034.04 | 62.03 | -16.23 | 1876 |
| US.TSLA | EMA + RSI | 130379.94 | 30.38 | -11.98 | 6326 |
| US.TSLA | EMA + RSI bull range | 92696.59 | -7.30 | -29.71 | 9382 |
| US.TSLA | dual momentum | 204762.80 | 104.76 | -30.61 | 37 |

## 复现命令示例

```bash
./.venv/bin/python -m backtest.backtest_rsi_reversion --codes US.MSFT --market US --initial-cash 100000 --fee-account futu_alt --show-trades 0
./.venv/bin/python -m backtest.backtest_ema_cross --codes US.MSFT --market US --initial-cash 100000 --fee-account futu_alt --show-trades 0
./.venv/bin/python -m backtest.backtest_ema_rsi_combo --codes US.MSFT --market US --initial-cash 100000 --fee-account futu_alt --show-trades 0
./.venv/bin/python -m backtest.backtest_ema_rsi_bull_range --codes US.MSFT --market US --initial-cash 100000 --fee-account futu_alt --show-trades 0
./.venv/bin/python -m backtest.backtest_dual_momentum --codes US.MSFT --market US --initial-cash 100000 --fee-account futu_alt --show-trades 0
```
