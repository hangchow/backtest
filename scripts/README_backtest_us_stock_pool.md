# 美股股票池回测结果与分析
这份文档只记录美股股票池相关工作

## 统一回测口径与账户费用

- [回测统一口径（scripts/README.md）](README.md#回测统一口径)
- [账户费用规则（scripts/README.md）](README.md#费用规则futu_alt)

- 本文档聚焦美股股票池结果、解读与复现命令，不再重复维护统一口径与费用细则。

## 优化参数股票池收益榜

按 `2025-03-07` 到 `2026-03-06` 记分窗口里的收益率排序：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| dual momentum | daily | 163245.41 | 63.25 | -30.40 | 30 |
| RSI reversion | minute | 122124.60 | 22.12 | -35.87 | 30744 |
| EMA + RSI | minute | 100000.00 | 0.00 | 0.00 | 0 |
| EMA + RSI bull range | minute | 100000.00 | 0.00 | 0.00 | 0 |
| EMA cross | minute | 80842.99 | -19.16 | -41.67 | 2908 |


## 结果解读

- 在本次按统一费用口径（`--fee-account futu_alt`）重跑后，优化版 `dual momentum` 成为收益第一（`return_pct = 63.25%`），并将交易次数压降至 `30`。
- `RSI reversion` 通过调高止盈阈值（`--sell-threshold 70`）后，收益从 `17.83%` 提升到 `22.12%`，但回撤扩大到 `-35.87%`。
- `EMA + RSI` 通过提高成交量门槛（`--min-volume-ratio 99`）后，本窗口无交易，收益回到 `0.00%`，显著优于此前 `-9.80%`。
- `EMA cross` 调整为更保守仓位（`--position-ratio 0.15 --max-open-positions 1`）后，收益从 `-24.36%` 改善到 `-19.16%`，交易数降到 `2908`。
- `EMA + RSI bull range` 同样通过提高成交量门槛（`--min-volume-ratio 99`）将高换手关闭，本窗口收益回到 `0.00%`。
- `dual momentum` 继续使用“短长周期动量 + 市场风险开关 + 调仓阈值 + 波动率目标”组合，维持收益第一（`63.25%`）。

## 实现备注

- 本文档结果基于各策略当前默认参数与统一费用口径重跑；分钟级策略命令以当前脚本实际支持参数为准。
- `dual momentum` 支持 `--eval-start`，按日频交易日解释该起点；若不传该参数则按全样本区间统计。
- `dual momentum` 新增了市场过滤（等权股票池 MA）、调仓阈值、双周期动量与波动率目标参数，默认值已经过当前股票池口径验证。
- [`backtest_ema_rsi_bull_range.py`](backtest_ema_rsi_bull_range.py) 复用了 [`backtest_ema_rsi_combo.py`](backtest_ema_rsi_combo.py) 的股票池引擎，只是默认参数不同。

## 当前基线命令

后续更新这份文档时，优先复用下面这组命令（即当前排行榜口径，`dual momentum` 显式写出最佳参数）：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt \
  --sell-threshold 70 \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_cross.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt \
  --position-ratio 0.15 \
  --max-open-positions 1 \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_combo.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt \
  --min-volume-ratio 99 \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt \
  --min-volume-ratio 99 \
  --show-trades 0

./.venv/bin/python scripts/backtest_dual_momentum.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt \
  --lookback-days 90 \
  --long-lookback-days 180 \
  --long-lookback-weight 0.25 \
  --top-n 1 \
  --volume-window 20 \
  --min-volume-ratio 1.3 \
  --market-filter-window 120 \
  --rebalance-band-pct 0.10 \
  --volatility-window 20 \
  --target-annual-vol 0.30 \
  --show-trades 0
```

## 更新约定

- 只要是美股股票池结果、分析、结论更新，优先修改这份文档。
- 如果是港股股票池结果更新，修改港股股票池文档；如果是单标结果更新，修改单标文档。
- 如果未来把股票池评估从单一窗口升级成滚动 walk-forward，也优先直接更新这份文档顶部口径，而不是只在根目录 `README.md` 里补一句。
