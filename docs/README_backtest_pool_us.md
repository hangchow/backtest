# 美股股票池回测结果与分析

## 统一回测口径与账户费用

- [回测统一口径（backtest/README.md）](../backtest/README.md#回测统一口径)
- [账户费用规则（backtest/README.md）](../backtest/README.md#费用规则futu_alt)

- 本文档只保留美股股票池的结果表、最少量结论和复现命令；统一口径与费用细则以上面两份基线文档为准。

## 优化参数股票池收益榜

按 `2025-03-07` 到 `2026-03-06` 记分窗口里的收益率排序（股票池为 `US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO US.GLD US.META`）：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count | total_fees | strategy_time_sec |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Dual momentum + EMA + RSI hybrid | day+minute | 229957.61 | 129.96 | -13.75 | 24 | 160.86 | 3.97 |
| EMA + RSI | minute | 165592.03 | 65.59 | -9.89 | 12990 | 78823.38 | 25.10 |
| EMA + RSI bull range | minute | 165592.03 | 65.59 | -9.89 | 12990 | 78823.38 | 25.38 |
| Dual momentum | daily | 158703.57 | 58.70 | -25.92 | 66 | 497.02 | 4.75 |
| Momentum monthly | daily | 136715.01 | 36.72 | -21.51 | 21 | 139.97 | 0.20 |
| EMA cross | minute | 91398.10 | -8.60 | -9.53 | 2685 | 5867.22 | 23.58 |
| RSI reversion | minute | 33019.26 | -66.98 | -67.23 | 51867 | 107451.22 | 51.39 |

## 结论与复现

- 本文档结果是 `2026-03-28` 对 10 只股票池 `US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO US.GLD US.META` 的最新复跑；具体数值以上表为准。
- 新增 `Dual momentum + EMA + RSI hybrid` 后，当前窗口榜首被直接改写：`final_value = 229957.61`、`return_pct = 129.96%`、`max_drawdown_pct = -13.75%`、`trade_count = 24`，收益和回撤都明显优于其余基线。
- `EMA + RSI` / `EMA + RSI bull range` 现在退到第二梯队，收益仍有 `65.59%`，但已不再是当前 10 只股票池里的最优解。
- `EMA + RSI bull range` 与 `EMA + RSI` 结果完全一致，因为股票池模式下它直接复用 [`backtest_ema_rsi_combo.py`](../backtest/backtest_ema_rsi_combo.py) 的执行引擎，当前基线参数也已收敛到同一组区间。
- 新增 `Momentum monthly` 后，日频轮动里形成了更清晰的分层：它以 `36.72%` 排在 `Dual momentum` 之后，但仍显著好于 `EMA cross` 和 `RSI reversion`。
- `EMA cross` 仍是低收益、相对低回撤基线；`RSI reversion` 仍是高换手、最差结果的策略。
- `US.GLD` 和 `US.META` 的本地日线与分钟线都已补齐；命令显式传入 `--eval-start/--eval-end`，窗口外数据只用于预热。

## 基线命令

后续更新这份文档时，优先复用批量脚本和参数文件 [baseline_strategy_config.json](./backtest_pool_us/baseline_strategy_config.json)。它固定当前表格使用的 7 个策略参数：`rsi_reversion`、`ema_cross`、`ema_rsi_combo`、`ema_rsi_bull_range`、`dual_momentum`、`momentum_monthly`、`dual_momentum_ema_rsi_hybrid`。

```bash
./.venv/bin/python -m backtest.backtest_pool_batch \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO US.GLD US.META \
  --market US \
  --initial-cash 100000 \
  --fee-account futu_alt \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --strategy rsi_reversion \
  --strategy ema_cross \
  --strategy ema_rsi_combo \
  --strategy ema_rsi_bull_range \
  --strategy dual_momentum \
  --strategy momentum_monthly \
  --strategy dual_momentum_ema_rsi_hybrid \
  --strategy-config docs/backtest_pool_us/baseline_strategy_config.json
```
