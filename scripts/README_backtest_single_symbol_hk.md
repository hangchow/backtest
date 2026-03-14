# 港股单标回测（`--codes`）

本文档汇总港股单标在默认参数下的分钟级回测结果。

## 回测口径

- 数据目录：`data/`
- 初始资金：`100000`
- 每次仅回测 1 只标的（`--codes <HK.CODE>`）
- 默认允许隔夜持仓（未启用 `--flat-at-close`）
- 交易价格：分钟收盘价
- 费用：当前结果未加入 `--fee-account`，属于样本内结果快照

## 标的范围

- `HK.00700`
- `HK.09988`
- `HK.00005`

## 默认参数结果

| code | strategy | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | ---: | ---: | ---: | ---: |
| HK.00700 | RSI reversion | 491405.10 | 391.41 | -10.14 | 3208 |
| HK.00700 | EMA cross | 92739.70 | -7.26 | -10.59 | 786 |
| HK.00700 | EMA + RSI | 250760.00 | 150.76 | -3.13 | 2472 |
| HK.00700 | EMA + RSI bull range | 385851.30 | 285.85 | -3.28 | 4502 |
| HK.09988 | RSI reversion | 485308.30 | 385.31 | -8.11 | 3476 |
| HK.09988 | EMA cross | 92886.45 | -7.11 | -14.64 | 722 |
| HK.09988 | EMA + RSI | 215142.90 | 115.14 | -4.15 | 2286 |
| HK.09988 | EMA + RSI bull range | 251209.50 | 151.21 | -5.07 | 4038 |
| HK.00005 | RSI reversion | 286442.98 | 186.44 | -8.13 | 2792 |
| HK.00005 | EMA cross | 96853.50 | -3.15 | -6.98 | 852 |
| HK.00005 | EMA + RSI | 225399.45 | 125.40 | -6.34 | 2760 |
| HK.00005 | EMA + RSI bull range | 286016.50 | 186.02 | -5.35 | 4400 |

## 复现命令示例

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py --codes HK.00700
./.venv/bin/python scripts/backtest_ema_cross.py --codes HK.00700
./.venv/bin/python scripts/backtest_ema_rsi_combo.py --codes HK.00700
./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py --codes HK.00700
```
