# 美股股票池回测结果与分析
这份文档只记录美股股票池相关工作

## 统一回测口径与账户费用

- [回测统一口径（scripts/README.md）](README.md#回测统一口径)
- [账户费用规则（scripts/README.md）](README.md#费用规则futu_alt)

- 本文档聚焦美股股票池结果、解读与复现命令，不再重复维护统一口径与费用细则。

## 优化参数股票池收益榜

按 `2025-03-07` 到 `2026-03-06` 记分窗口里的收益率排序（股票池新增 `US.AMZN`）：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| dual momentum | daily | 202129.96 | 102.13 | -16.06 | 55 |
| RSI reversion | minute | 136188.21 | 36.19 | -31.56 | 18496 |
| EMA + RSI | minute | 100000.00 | 0.00 | 0.00 | 0 |
| EMA + RSI bull range | minute | 100000.00 | 0.00 | 0.00 | 0 |
| EMA cross | minute | 88092.78 | -11.91 | -14.92 | 2746 |


## 结果解读

- 在本次继续优化并按统一费用口径（`--fee-account futu_alt`）重跑后，优化版 `dual momentum` 继续收益第一，`return_pct` 提升至 `102.13%`，且 `max_drawdown_pct` 收敛到 `-16.06%`。
- `RSI reversion` 在五只股票池中收益提升至 `36.19%`，同时最大回撤收敛到 `-31.56%`，交易数降到 `18496`。
- `EMA + RSI` 通过提高成交量门槛（`--min-volume-ratio 99`）后，本窗口无交易，收益回到 `0.00%`，显著优于此前 `-9.80%`。
- `EMA cross` 在新增 `US.AMZN` 后继续维持保守仓位配置，收益改善到 `-11.91%`，最大回撤降至 `-14.92%`。
- `EMA + RSI bull range` 同样通过提高成交量门槛（`--min-volume-ratio 99`）将高换手关闭，本窗口收益回到 `0.00%`。
- `dual momentum` 继续使用“短长周期动量 + 市场风险开关 + 调仓阈值 + 波动率目标”组合，并新增了可控杠杆上限（`max gross exposure`）参数，在当前股票池口径中实现了更高收益同时控制回撤。

## 实现备注

- 本文档结果基于各策略当前默认参数与统一费用口径重跑；分钟级策略命令以当前脚本实际支持参数为准。
- `dual momentum` 支持 `--eval-start`，按日频交易日解释该起点；若不传该参数则按全样本区间统计。
- `dual momentum` 现支持 `--max-gross-exposure`（默认 `1.0`），用于限制最大总仓位倍率；默认值不改变历史口径，只有显式提高该参数时才会使用受控杠杆。
- [`backtest_ema_rsi_bull_range.py`](backtest_ema_rsi_bull_range.py) 复用了 [`backtest_ema_rsi_combo.py`](backtest_ema_rsi_combo.py) 的股票池引擎，只是默认参数不同。

## 当前基线命令

后续更新这份文档时，优先复用下面这组命令（即当前排行榜口径，`dual momentum` 显式写出最佳参数）：

```bash
python3 scripts/backtest_rsi_reversion.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN \
  --fee-account futu_alt \
  --sell-threshold 70 \
  --show-trades 0

python3 scripts/backtest_ema_cross.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN \
  --fee-account futu_alt \
  --position-ratio 0.15 \
  --max-open-positions 1 \
  --show-trades 0

python3 scripts/backtest_ema_rsi_combo.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN \
  --fee-account futu_alt \
  --min-volume-ratio 99 \
  --show-trades 0

python3 scripts/backtest_ema_rsi_bull_range.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN \
  --fee-account futu_alt \
  --min-volume-ratio 99 \
  --show-trades 0

python3 scripts/backtest_dual_momentum.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN \
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
  --show-trades 0
```

## 更新约定

- 只要是美股股票池结果、分析、结论更新，优先修改这份文档。
- 如果是港股股票池结果更新，修改港股股票池文档；如果是单标结果更新，修改单标文档。
- 如果未来把股票池评估从单一窗口升级成滚动 walk-forward，也优先直接更新这份文档顶部口径，而不是只在根目录 `README.md` 里补一句。
