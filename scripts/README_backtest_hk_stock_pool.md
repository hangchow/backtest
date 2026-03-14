# 港股股票池回测结果与分析

- 这份文档的港股股票池结果已经不是整段样本内统计，而是“前一年预热、后一年记收益”
- 费用与参数口径请以「统一回测口径与账户费用」小节所链接基线文档为准
- 这还不是完整的滚动 walk-forward，只是一段固定的样本外窗口
- 没有处理港股整手限制、停牌、除权除息等问题

## 统一回测口径与账户费用

- [回测统一口径（scripts/README.md）](README.md#回测统一口径)
- [账户费用规则（scripts/README.md）](README.md#费用规则futu_alt)

- 本文档聚焦港股股票池结果、解读与复现命令，不再重复维护统一口径与费用细则。

## 默认参数股票池收益榜

按 `2025-03-07` 到 `2026-03-06` 记分窗口里的收益率排序：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| RSI reversion | minute | 414743.66 | 314.74 | -5.12 | 9478 |
| EMA + RSI bull range | minute | 303271.75 | 203.27 | -1.96 | 12956 |
| EMA + RSI | minute | 231257.15 | 131.26 | -2.80 | 7542 |
| dual momentum | daily | 135075.80 | 35.08 | -29.75 | 23 |
| EMA cross | minute | 88191.95 | -11.81 | -22.94 | 2355 |

## 结果解读

- 如果只看当前这段样本外窗口，`RSI reversion` 仍然是港股股票池第一名，`return_pct = 314.74%`、`max_drawdown_pct = -5.12%`。不过它相对旧的整段样本内 `970.93%` 已经明显回落，说明它虽然仍强，但对样本区间的依赖也很重。
- `EMA + RSI bull range` 和 `EMA + RSI` 继续维持第二、第三，而且最大回撤分别只有 `-1.96%` 和 `-2.79%`。这说明港股分钟池里，趋势过滤 + 回踩买入这条线在样本外仍然有效，而且风险控制比 `RSI reversion` 更平滑。
- `EMA + RSI bull range` 现在比普通 `EMA + RSI` 多赚了约 `72.01` 个百分点，回撤还更浅；代价是交易数升到 `12956`，所以如果后续加入真实费用，它和 `RSI reversion` 一样都会明显受冲击。
- `dual momentum` 在港股这组三只票上的样本外表现明显弱于美股，只剩 `35.08%`，而且最大回撤仍接近 `-30%`。这说明低频轮动逻辑在当前这个港股小股票池里并没有展现出和美股同等级别的优势。
- `EMA cross` 仍然是港股股票池里最弱的一档，样本外收益已经转负到 `-11.81%`，回撤 `-22.94%`，优先级可以继续放低。

## 实现备注

- 分钟级股票池策略现在支持 `--eval-start`，会用该时间点之前的 bar 做指标预热，但不把那一段纳入交易和收益统计。
- `dual momentum` 同样支持 `--eval-start`，但它按日频交易日解释这个起点；也就是先用更早的日线做 lookback 预热，再从指定日期开始记分。
- [`backtest_ema_rsi_bull_range.py`](backtest_ema_rsi_bull_range.py) 复用了 [`backtest_ema_rsi_combo.py`](backtest_ema_rsi_combo.py) 的股票池引擎，只是默认参数不同。

## 当前基线命令

后续更新这份文档时，优先复用下面这组命令：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --eval-start "2025-03-07 09:30:00" \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_cross.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --eval-start "2025-03-07 09:30:00" \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_combo.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --eval-start "2025-03-07 09:30:00" \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --eval-start "2025-03-07 09:30:00" \
  --show-trades 0

./.venv/bin/python scripts/backtest_dual_momentum.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --eval-start "2025-03-07 09:30:00" \
  --show-trades 0
```

## 更新约定

- 只要是港股股票池结果、分析、结论更新，优先修改这份文档。
- 如果是美股股票池结果更新，修改 [美股股票池回测结果与分析](README_backtest_us_stock_pool.md)。
- 如果是单标结果更新，修改 [单标的回测结果与分析](README_backtest_single_symbol.md)。
- 如果未来把股票池评估从单一窗口升级成滚动 walk-forward，也优先直接更新这份文档顶部口径，而不是只在根目录 `README.md` 里补一句。
