# 美股股票池回测结果与分析
这份文档只记录美股股票池相关工作

## 统一回测口径与账户费用

- [回测统一口径（backtest/README.md）](README.md#回测统一口径)
- [账户费用规则（backtest/README.md）](README.md#费用规则futu_alt)

- 本文档聚焦美股股票池结果、解读与复现命令，不再重复维护统一口径与费用细则。

## 优化参数股票池收益榜

按 `2025-03-07` 到 `2026-03-06` 记分窗口里的收益率排序（股票池扩展为 `US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO`）：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| dual momentum | daily | 204553.43 | 104.55 | -16.05 | 50 |
| EMA + RSI | minute | 100003.72 | 0.00 | -0.00 | 2 |
| EMA + RSI bull range | minute | 100000.00 | 0.00 | 0.00 | 0 |
| EMA cross | minute | 95429.91 | -4.57 | -5.72 | 1499 |
| RSI reversion | minute | 54255.05 | -45.74 | -46.84 | 25818 |


## 结果解读

- 在扩容到 8 只美股并按统一评分窗口（`2025-03-07` 到 `2026-03-06`）重跑后，优化版 `dual momentum` 仍然显著领先，`return_pct` 提升到 `104.55%`，同时 `max_drawdown_pct` 维持在 `-16.05%`。
- `EMA cross` 在更大的股票池里仍然保持相对温和的风险暴露，虽然收益仍为负，但回撤控制明显，`return_pct` 为 `-4.57%`，`max_drawdown_pct` 仅 `-5.72%`。
- `EMA + RSI` 在 `--min-volume-ratio 99` 的高门槛下只触发了 `2` 笔交易，期末基本打平，`final_value` 为 `100003.72`。
- `EMA + RSI bull range` 在同样的高成交量门槛下继续零交易，窗口收益维持在 `0.00%`。
- `RSI reversion` 在统一持仓上限口径（默认 `--max-open-positions -1`）和 8 只股票池下显著恶化，`return_pct` 降到 `-45.74%`，`max_drawdown_pct` 扩大到 `-46.84%`，说明这套分钟级均值回归在扩容后的样本外窗口里不稳定。

## 实现备注

- 本文档结果基于各策略当前默认参数与统一费用口径重跑；分钟级策略命令以当前脚本实际支持参数为准。
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
  --min-volume-ratio 99 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

python3 backtest/backtest_ema_rsi_bull_range.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --fee-account futu_alt \
  --min-volume-ratio 99 \
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
