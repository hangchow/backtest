# 港股股票池回测结果与分析

## 维护边界

这份文档只记录港股股票池相关工作：

- 股票池范围固定为 `HK.00700`、`HK.09988`、`HK.00005`
- 结果、分析、后续迭代结论统一维护在这里
- 美股股票池结果单独维护在 [美股股票池回测结果与分析](README_backtest_us_stock_pool.md)
- 单标默认参数对比单独维护在 [单标的回测结果与分析](README_backtest_single_symbol.md)

如果后续策略脚本同时影响港股和美股，请分别更新两边结果，不要把两类市场的分析混写到同一节里。

## 当前口径

- 结果生成日期：`2026-03-12`
- 原始数据范围：`2024-03-07 09:30:00` 到 `2026-03-06 16:00:00`
- 指标预热窗口：`2024-03-07 09:30:00` 到 `2025-03-10 16:00:00`
- 正式记分窗口：`2025-03-11 09:30:00` 到 `2026-03-06 16:00:00`
- 股票池：`HK.00700`、`HK.09988`、`HK.00005`
- 初始资金：`100000`
- 默认允许隔夜；只有显式传入 `--flat-at-close` 才会日内平仓
- `--max-open-positions` 默认是 `-1`，等同全池可同时持仓
- `dual momentum` 使用同一批分钟数据聚合出的日线收盘价和日成交量

说明：

- 这份文档的港股股票池结果已经不是整段样本内统计，而是“前一年预热、后一年记收益”
- 仍然没有加入手续费、交易征费、印花税、滑点
- 这还不是完整的滚动 walk-forward，只是一段固定的样本外窗口
- 没有处理港股整手限制、停牌、除权除息等问题

## 默认参数股票池收益榜

按 `2025-03-11` 到 `2026-03-06` 记分窗口里的收益率排序：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| RSI reversion | minute | 420663.83 | 320.66 | -5.12 | 9386 |
| EMA + RSI bull range | minute | 303120.50 | 203.12 | -1.96 | 12880 |
| EMA + RSI | minute | 230451.60 | 130.45 | -2.79 | 7482 |
| dual momentum | daily | 141622.26 | 41.62 | -29.74 | 23 |
| EMA cross | minute | 88514.03 | -11.49 | -22.06 | 2343 |

## 结果解读

- 如果只看当前这段样本外窗口，`RSI reversion` 仍然是港股股票池第一名，`return_pct = 320.66%`、`max_drawdown_pct = -5.12%`。不过它相对旧的整段样本内 `970.93%` 已经明显回落，说明它虽然仍强，但对样本区间的依赖也很重。
- `EMA + RSI bull range` 和 `EMA + RSI` 继续维持第二、第三，而且最大回撤分别只有 `-1.96%` 和 `-2.79%`。这说明港股分钟池里，趋势过滤 + 回踩买入这条线在样本外仍然有效，而且风险控制比 `RSI reversion` 更平滑。
- `EMA + RSI bull range` 现在比普通 `EMA + RSI` 多赚了约 `72.67` 个百分点，回撤还更浅；代价是交易数升到 `12880`，所以如果后续加入真实费用，它和 `RSI reversion` 一样都会明显受冲击。
- `dual momentum` 在港股这组三只票上的样本外表现明显弱于美股，只剩 `41.62%`，而且最大回撤仍接近 `-30%`。这说明低频轮动逻辑在当前这个港股小股票池里并没有展现出和美股同等级别的优势。
- `EMA cross` 仍然是港股股票池里最弱的一档，样本外收益已经转负到 `-11.49%`，回撤 `-22.06%`，优先级可以继续放低。

## 实现备注

- 分钟级股票池策略现在支持 `--eval-start`，会用该时间点之前的 bar 做指标预热，但不把那一段纳入交易和收益统计。
- `dual momentum` 同样支持 `--eval-start`，但它按日频交易日解释这个起点；也就是先用更早的日线做 lookback 预热，再从指定日期开始记分。
- [`backtest_ema_rsi_bull_range.py`](backtest_ema_rsi_bull_range.py) 复用了 [`backtest_ema_rsi_combo.py`](backtest_ema_rsi_combo.py) 的股票池引擎，只是默认参数不同。

## 当前基线命令

后续更新这份文档时，优先复用下面这组命令：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --eval-start 2025-03-11 \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_cross.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --eval-start 2025-03-11 \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_combo.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --eval-start 2025-03-11 \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --eval-start 2025-03-11 \
  --show-trades 0

./.venv/bin/python scripts/backtest_dual_momentum.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --eval-start 2025-03-11 \
  --show-trades 0
```

## 更新约定

- 只要是港股股票池结果、分析、结论更新，优先修改这份文档。
- 如果是美股股票池结果更新，修改 [美股股票池回测结果与分析](README_backtest_us_stock_pool.md)。
- 如果是单标结果更新，修改 [单标的回测结果与分析](README_backtest_single_symbol.md)。
- 如果未来把股票池评估从单一窗口升级成滚动 walk-forward，也优先直接更新这份文档顶部口径，而不是只在根目录 `README.md` 里补一句。
