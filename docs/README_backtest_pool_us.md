# 美股股票池回测结果与分析
这份文档只记录美股股票池相关工作

## 统一回测口径与账户费用

- [回测统一口径（backtest/README.md）](../backtest/README.md#回测统一口径)
- [账户费用规则（backtest/README.md）](../backtest/README.md#费用规则futu_alt)

- 本文档聚焦美股股票池结果、解读与复现命令，不再重复维护统一口径与费用细则。
- `dual momentum` 已于 `2026-03-17` 按本文“当前基线命令”完成双窗口复跑：在 `2025-03-07 ~ 2026-03-06` 窗口结果为 `final_value = 221343.02`、`return_pct = 121.34%`、`max_drawdown_pct = -14.44%`、`trade_count = 50`；在新增窗口 `2025-01-01 ~ 2026-01-01`（实际交易日落点 `2025-01-02 ~ 2025-12-31`）结果为 `final_value = 185287.43`、`return_pct = 85.29%`、`max_drawdown_pct = -20.22%`、`trade_count = 53`。

## 优化参数股票池收益榜（窗口一）

按 `2025-03-07` 到 `2026-03-06` 记分窗口里的收益率排序（股票池扩展为 `US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO`）：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| dual momentum | daily | 221343.02 | 121.34 | -14.44 | 50 |
| EMA + RSI | minute | 117761.64 | 17.76 | -12.37 | 6408 |
| EMA + RSI bull range | minute | 117761.64 | 17.76 | -12.37 | 6408 |
| EMA cross | minute | 95429.91 | -4.57 | -5.72 | 1499 |
| RSI reversion | minute | 54255.05 | -45.74 | -46.84 | 25818 |

## 优化参数股票池收益榜（窗口二）

按新增记分窗口 `2025-01-01` 到 `2026-01-01`（交易日实际落在 `2025-01-02` 到 `2025-12-31`）收益率排序（股票池同样为 `US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO`）：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| dual momentum | daily | 185287.43 | 85.29 | -20.22 | 53 |
| EMA + RSI | minute | 180185.63 | 80.19 | -14.98 | 12766 |
| EMA + RSI bull range | minute | 180185.63 | 80.19 | -14.98 | 12766 |
| EMA cross | minute | 87808.95 | -12.19 | -13.86 | 2890 |
| RSI reversion | minute | 47647.88 | -52.35 | -52.70 | 44921 |

## 结果解读

- 在扩容到 8 只美股并按统一评分窗口（`2025-03-07` 到 `2026-03-06`）重跑后，优化版 `dual momentum` 仍然显著领先；`2026-03-17` 的复跑结果进一步提升到 `return_pct = 121.34%`，同时 `max_drawdown_pct` 收敛到 `-14.44%`。
- 新增 `2025-01-01 ~ 2026-01-01` 记分窗口后，`dual momentum` 依旧位列第一，但领先幅度显著收窄（`85.29%` vs `80.19%`），且回撤从窗口一的 `-14.44%` 扩大到 `-20.22%`，说明更长窗口对趋势策略的波动容忍提出了更高要求。
- `EMA + RSI` 的股票池基线已经从“几乎不交易”的 `--min-volume-ratio 99` 调整成真正可成交的保守参数组合：`buy<35 / sell>60 / min-volume-ratio 1.2 / max-open-positions 1`。在这个口径下，`return_pct` 提升到 `17.76%`，`max_drawdown_pct` 为 `-12.37%`，说明它在股票池层面更适合做低并发、低频率的顺势回撤，而不是把量能门槛抬到几乎禁用。
- `EMA + RSI` / `EMA + RSI bull range` 在窗口二同步抬升到 `80.19%`，与 `dual momentum` 只差约 `5.10` 个百分点，且回撤仍低于 `dual momentum`，说明分钟级趋势+回撤在 2025 全年这个窗口里更接近“高收益、可接受回撤”的均衡解。
- `EMA + RSI bull range` 的股票池默认参数在当前 8 只美股样本里会明显过度交易；把它也收敛到同一组保守参数后，结果与 `EMA + RSI` 完全一致，说明这两个脚本在股票池模式下的最稳健解已经收敛到同一套执行区间。
- `EMA cross` 在更大的股票池里仍然保持相对温和的风险暴露，虽然收益仍为负，但回撤控制明显，`return_pct` 为 `-4.57%`，`max_drawdown_pct` 仅 `-5.72%`。
- `RSI reversion` 在统一持仓上限口径（默认 `--max-open-positions -1`）和 8 只股票池下显著恶化，`return_pct` 降到 `-45.74%`，`max_drawdown_pct` 扩大到 `-46.84%`，说明这套分钟级均值回归在扩容后的样本外窗口里不稳定。

## 实现备注

- 本文档结果基于各策略当前默认参数与统一费用口径重跑；分钟级策略命令以当前脚本实际支持参数为准。
- `dual momentum` 已于 `2026-03-17` 用下方基线命令单独复跑确认，输出为：`Trades = 50 (BUY 25, SELL 25)`、`Ending cash = 221343.02`、`Final value = 221343.02`、`Total return = 121.34%`、`Max drawdown = -14.44%`。
- 新增窗口 `2025-01-01 ~ 2026-01-01` 也已于 `2026-03-17` 复跑确认：`dual momentum` 输出为 `Trades = 53 (BUY 27, SELL 26)`、`Ending cash = -37510.57`、`Final value = 185287.43`、`Total return = 85.29%`、`Max drawdown = -20.22%`。
- `EMA cross` 在新增窗口输出为：`Trades = 2890 (BUY 1445, SELL 1445)`、`Final value = 87808.95`、`Total return = -12.19%`、`Max drawdown = -13.86%`。
- `EMA + RSI` 在新增窗口输出为：`Trades = 12766 (BUY 6383, SELL 6383)`、`Final value = 180185.63`、`Total return = 80.19%`、`Max drawdown = -14.98%`。
- `EMA + RSI bull range` 在新增窗口参数与 `EMA + RSI` 保持一致，汇总输出也一致：`Final value = 180185.63`、`Total return = 80.19%`、`Max drawdown = -14.98%`。
- `RSI reversion` 在新增窗口输出为：`Trades = 44921 (BUY 22462, SELL 22459)`、`Final value = 47647.88`、`Total return = -52.35%`、`Max drawdown = -52.70%`。
- `EMA + RSI` 已于 `2026-03-16` 用新的股票池基线参数复跑确认，输出为：`Trades = 6408 (BUY 3204, SELL 3204)`、`Final value = 117761.64`、`Total return = 17.76%`、`Max drawdown = -12.37%`。
- `EMA + RSI bull range` 当前股票池基线也改成同一组保守参数；由于 [`backtest_ema_rsi_bull_range.py`](README_backtest_ema_rsi_bull_range.md) 内部直接复用 [`backtest_ema_rsi_combo.py`](README_backtest_ema_rsi_combo.md) 的股票池执行引擎，在 `fast/slow/rsi/buy/sell/volume/max-open-positions` 参数完全一致时，汇总结果也与 `EMA + RSI` 相同。
- 由于数据目录已延伸到 `2026-03-13`，本文档现在维护两套固定评分窗口：`2025-03-07 ~ 2026-03-06`（窗口一）与 `2025-01-01 ~ 2026-01-01`（窗口二）；两套命令都显式传入 `--eval-start/--eval-end`，保证可复现且不混入窗口外统计。
- 分钟级股票池脚本与 `dual momentum` 现在都支持 `--eval-start` / `--eval-end`；窗口外数据只用于预热，不再混入评分结果。
- `dual momentum` 现支持 `--max-gross-exposure`（默认 `1.0`），用于限制最大总仓位倍率；默认值不改变历史口径，只有显式提高该参数时才会使用受控杠杆。
- [`backtest_ema_rsi_bull_range.py`](../backtest/backtest_ema_rsi_bull_range.py) 复用了 [`backtest_ema_rsi_combo.py`](../backtest/backtest_ema_rsi_combo.py) 的股票池引擎，只是默认参数不同。

## 当前基线命令

后续更新这份文档时，优先复用下面这组命令（即当前排行榜口径，`dual momentum` 显式写出最佳参数）：

所有命令都必须显式传入 `--market US`。

```bash
./.venv/bin/python -m backtest.backtest_rsi_reversion \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --market US \
  --initial-cash 100000 \
  --fee-account futu_alt \
  --sell-threshold 70 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

./.venv/bin/python -m backtest.backtest_ema_cross \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --market US \
  --initial-cash 100000 \
  --fee-account futu_alt \
  --position-ratio 0.15 \
  --max-open-positions 1 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

./.venv/bin/python -m backtest.backtest_ema_rsi_combo \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --market US \
  --initial-cash 100000 \
  --fee-account futu_alt \
  --buy-threshold 35 \
  --sell-threshold 60 \
  --min-volume-ratio 1.2 \
  --max-open-positions 1 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

./.venv/bin/python -m backtest.backtest_ema_rsi_bull_range \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --market US \
  --initial-cash 100000 \
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

./.venv/bin/python -m backtest.backtest_dual_momentum \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --market US \
  --initial-cash 100000 \
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
