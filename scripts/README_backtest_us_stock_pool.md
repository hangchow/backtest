# 美股股票池回测结果与分析
这份文档只记录美股股票池相关工作

## 默认参数股票池收益榜

按 `2025-03-11` 到 `2026-03-06` 记分窗口里的收益率排序：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| dual momentum | daily | 188354.82 | 88.35 | -10.04 | 42 |
| EMA + RSI | minute | 123345.07 | 23.35 | -5.16 | 12382 |
| EMA + RSI bull range | minute | 122234.29 | 22.23 | -8.58 | 19368 |
| EMA cross | minute | 119643.63 | 19.64 | -14.83 | 3878 |
| RSI reversion | minute | 118489.57 | 18.49 | -14.78 | 17317 |

## 结果解读

- 如果只看当前这段样本外窗口，`dual momentum` 仍然明显是第一名。它从旧的整段样本内 `102.23%` 回落到 `88.35%`，但优势没有消失，说明它不是完全靠那段样本内区间堆出来的。
- 如果只看分钟级股票池，`EMA + RSI` 现在排到第一，`return_pct = 23.35%`、`max_drawdown_pct = -5.16%`。它比 `EMA + RSI bull range` 更稳，说明更保守的趋势过滤在样本外更有韧性。
- `EMA + RSI bull range` 和 `RSI reversion` 的收益都比旧的整段样本内结果回落明显，说明这两套参数对原先那段样本依赖更强，样本外衰减更明显。
- `EMA cross` 虽然不是收益冠军，但交易数只有 `3878`，明显低于其它分钟级股票池策略，更适合作为低频、低换手的控制组。
- `dual momentum` 的交易数只有 `42`，远低于分钟级策略；如果后续引入真实费用和滑点，它的相对优势理论上还有机会进一步放大。

## 实现备注

- 分钟级股票池策略现在支持 `--eval-start`，会用该时间点之前的 bar 做指标预热，但不把那一段纳入交易和收益统计。
- `dual momentum` 同样支持 `--eval-start`，但它按日频交易日解释这个起点；也就是先用更早的日线做 lookback 预热，再从指定日期开始记分。
- [`backtest_ema_rsi_bull_range.py`](backtest_ema_rsi_bull_range.py) 复用了 [`backtest_ema_rsi_combo.py`](backtest_ema_rsi_combo.py) 的股票池引擎，只是默认参数不同。

## 当前基线命令

后续更新这份文档时，优先复用下面这组命令：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --eval-start "2025-03-11 09:30:00" \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_cross.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --eval-start "2025-03-11 09:30:00" \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_combo.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --eval-start "2025-03-11 09:30:00" \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --eval-start "2025-03-11 09:30:00" \
  --show-trades 0

./.venv/bin/python scripts/backtest_dual_momentum.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --eval-start "2025-03-11 09:30:00" \
  --show-trades 0
```

## 更新约定

- 只要是美股股票池结果、分析、结论更新，优先修改这份文档。
- 如果是港股股票池结果更新，修改港股股票池文档；如果是单标结果更新，修改单标文档。
- 如果未来把股票池评估从单一窗口升级成滚动 walk-forward，也优先直接更新这份文档顶部口径，而不是只在根目录 `README.md` 里补一句。
