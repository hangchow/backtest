# 美股股票池回测结果与分析
这份文档只记录美股股票池相关工作

## 统一回测口径与账户费用

- [回测统一口径（backtest/README.md）](README.md#回测统一口径)
- [账户费用规则（backtest/README.md）](README.md#费用规则futu_alt)

- 本文档聚焦美股股票池结果、解读与复现命令，不再重复维护统一口径与费用细则。
- `dual momentum` 已于 `2026-03-16` 按本文“当前基线命令”重新复跑一次，结果仍为 `final_value = 204553.43`、`return_pct = 104.55%`、`max_drawdown_pct = -16.05%`、`trade_count = 50`。

## 优化参数股票池收益榜

按 `2025-03-07` 到 `2026-03-06` 记分窗口里的收益率排序（股票池扩展为 `US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO`）：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| dual momentum | daily | 204553.43 | 104.55 | -16.05 | 50 |
| EMA + RSI | minute | 117761.64 | 17.76 | -12.37 | 6408 |
| EMA + RSI bull range | minute | 117761.64 | 17.76 | -12.37 | 6408 |
| EMA cross | minute | 95429.91 | -4.57 | -5.72 | 1499 |
| RSI reversion | minute | 54255.05 | -45.74 | -46.84 | 25818 |


## 结果解读

- 在扩容到 8 只美股并按统一评分窗口（`2025-03-07` 到 `2026-03-06`）重跑后，优化版 `dual momentum` 仍然显著领先，`return_pct` 维持在 `104.55%`，`2026-03-16` 的复跑结果也没有变化，同时 `max_drawdown_pct` 继续保持在 `-16.05%`。
- `EMA + RSI` 的股票池基线已经从“几乎不交易”的 `--min-volume-ratio 99` 调整成真正可成交的保守参数组合：`buy<35 / sell>60 / min-volume-ratio 1.2 / max-open-positions 1`。在这个口径下，`return_pct` 提升到 `17.76%`，`max_drawdown_pct` 为 `-12.37%`，说明它在股票池层面更适合做低并发、低频率的顺势回撤，而不是把量能门槛抬到几乎禁用。
- `EMA + RSI bull range` 的股票池默认参数在当前 8 只美股样本里会明显过度交易；把它也收敛到同一组保守参数后，结果与 `EMA + RSI` 完全一致，说明这两个脚本在股票池模式下的最稳健解已经收敛到同一套执行区间。
- `EMA cross` 在更大的股票池里仍然保持相对温和的风险暴露，虽然收益仍为负，但回撤控制明显，`return_pct` 为 `-4.57%`，`max_drawdown_pct` 仅 `-5.72%`。
- `RSI reversion` 在统一持仓上限口径（默认 `--max-open-positions -1`）和 8 只股票池下显著恶化，`return_pct` 降到 `-45.74%`，`max_drawdown_pct` 扩大到 `-46.84%`，说明这套分钟级均值回归在扩容后的样本外窗口里不稳定。

## 实现备注

- 本文档结果基于各策略当前默认参数与统一费用口径重跑；分钟级策略命令以当前脚本实际支持参数为准。
- `dual momentum` 已于 `2026-03-16` 用下方基线命令单独复跑确认，输出为：`Trades = 50 (BUY 25, SELL 25)`、`Ending cash = 204553.43`、`Final value = 204553.43`、`Total return = 104.55%`、`Max drawdown = -16.05%`。
- `EMA + RSI` 已于 `2026-03-16` 用新的股票池基线参数复跑确认，输出为：`Trades = 6408 (BUY 3204, SELL 3204)`、`Final value = 117761.64`、`Total return = 17.76%`、`Max drawdown = -12.37%`。
- `EMA + RSI bull range` 当前股票池基线也改成同一组保守参数；由于 [`backtest_ema_rsi_bull_range.py`](README_backtest_ema_rsi_bull_range.md) 内部直接复用 [`backtest_ema_rsi_combo.py`](README_backtest_ema_rsi_combo.md) 的股票池执行引擎，在 `fast/slow/rsi/buy/sell/volume/max-open-positions` 参数完全一致时，汇总结果也与 `EMA + RSI` 相同。
- 由于数据目录已延伸到 `2026-03-13`，本次所有股票池回归都显式传入 `--eval-start 2025-03-07 --eval-end 2026-03-06`，保证评分窗口严格对齐 [`backtest/README.md`](README.md#回测统一口径)。
- 分钟级股票池脚本与 `dual momentum` 现在都支持 `--eval-start` / `--eval-end`；窗口外数据只用于预热，不再混入评分结果。
- `dual momentum` 现支持 `--max-gross-exposure`（默认 `1.0`），用于限制最大总仓位倍率；默认值不改变历史口径，只有显式提高该参数时才会使用受控杠杆。
- [`backtest_ema_rsi_bull_range.py`](backtest_ema_rsi_bull_range.py) 复用了 [`backtest_ema_rsi_combo.py`](backtest_ema_rsi_combo.py) 的股票池引擎，只是默认参数不同。

## 当前基线命令

后续更新这份文档时，优先复用下面这组命令（即当前排行榜口径，`dual momentum` 显式写出最佳参数）：

```bash
python3 backtest/backtest_rsi_reversion.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --fee-account futu_alt \
  --sell-threshold 70 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

python3 backtest/backtest_ema_cross.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --fee-account futu_alt \
  --position-ratio 0.15 \
  --max-open-positions 1 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

python3 backtest/backtest_ema_rsi_combo.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --fee-account futu_alt \
  --buy-threshold 35 \
  --sell-threshold 60 \
  --min-volume-ratio 1.2 \
  --max-open-positions 1 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

python3 backtest/backtest_ema_rsi_bull_range.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --fee-account futu_alt \
  --fast-span 20 \
  --slow-span 240 \
  --rsi-period 6 \
  --buy-threshold 35 \
  --sell-threshold 60 \
  --min-volume-ratio 1.2 \
  --max-open-positions 1 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

python3 backtest/backtest_dual_momentum.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --fee-account futu_alt \
  --lookback-days 40 \
  --long-lookback-days 120 \
  --long-lookback-weight 0.25 \
  --top-n 1 \
  --volume-window 20 \
  --min-volume-ratio 1.0 \
  --market-filter-window 60 \
  --rebalance-band-pct 0.05 \
  --volatility-window 20 \
  --target-annual-vol 0.60 \
  --max-gross-exposure 1.20 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0
```

## 更新约定

- 只要是美股股票池结果、分析、结论更新，优先修改这份文档。
- 如果是港股股票池结果更新，修改港股股票池文档；如果是单标结果更新，修改单标文档。
- 如果未来把股票池评估从单一窗口升级成滚动 walk-forward，也优先直接更新这份文档顶部口径，而不是只在根目录 `README.md` 里补一句。
