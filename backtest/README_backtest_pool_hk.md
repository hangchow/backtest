# 港股股票池回测结果与分析

- 这份文档当前结果基于统一费用口径（`--fee-account futu_alt`）与美股股票池文档同一套显式参数模板重跑
- 费用与参数口径请以「统一回测口径与账户费用」小节所链接基线文档为准
- 这还不是完整的滚动 walk-forward，只是一段固定的样本外窗口
- 没有处理港股整手限制、停牌、除权除息等问题

## 统一回测口径与账户费用

- [回测统一口径（backtest/README.md）](README.md#回测统一口径)
- [账户费用规则（backtest/README.md）](README.md#费用规则futu_alt)

- 本文档聚焦港股股票池结果、解读与复现命令，不再重复维护统一口径与费用细则。

## 对齐美股参数后的股票池收益榜

按 `2025-03-07` 到 `2026-03-06` 记分窗口里的收益率排序（股票池为 `HK.00700 HK.09988 HK.00005`）：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| dual momentum | daily | 90959.86 | -9.04 | -35.86 | 44 |
| EMA cross | minute | 57781.42 | -42.22 | -42.50 | 1107 |
| RSI reversion | minute | 346.13 | -99.65 | -99.66 | 3540 |
| EMA + RSI | minute | 110.93 | -99.89 | -99.89 | 1866 |
| EMA + RSI bull range | minute | 110.93 | -99.89 | -99.89 | 1866 |

## 结果解读

- 这次把港股股票池改成“直接套用美股股票池文档里的同一组参数”后，`dual momentum` 仍然是相对最优，但结果已经从旧文档里的大幅正收益回落到 `-9.04%`，说明这组参数对港股并不天然适配。
- 四个分钟级策略里，`EMA cross` 相对最稳，`return_pct = -42.22%`、`max_drawdown_pct = -42.50%`，明显好于另外三条高换手策略，但仍然跑输日频轮动。
- `RSI reversion` 在统一费用口径和当前 3 只港股股票池下继续接近“净值归零”，`return_pct = -99.65%`，说明短周期均值回归在港股这组样本里仍然被费用和噪音严重侵蚀。
- `EMA + RSI` 与 `EMA + RSI bull range` 在这次参数对齐后结果完全一致，都是 `1866` 笔交易、`final_value = 110.93`，说明它们在当前股票池与参数组合下收敛到了同一条执行路径。
- `dual momentum` 的交易数只有 `44`，远低于分钟级策略（`1107` 到 `3540`），但即使换手优势还在，直接照搬美股参数到港股也没有保住正收益。

## 实现备注

- 本文档结果记录的是 `2026-03-17` 那轮港股股票池实际复跑输出；下方基线命令现已显式补齐 `--initial-cash 800000`，用于对齐统一港股资金口径。
- `dual momentum` 这次输出为：`Trades = 44 (BUY 22, SELL 22)`、`Final value = 90959.86`、`Total return = -9.04%`、`Max drawdown = -35.86%`。
- `EMA cross` 这次输出为：`Trades = 1107 (BUY 554, SELL 553)`、`Final value = 57781.42`、`Total return = -42.22%`、`Max drawdown = -42.50%`。
- 由于港股 `kline_day/` 已延伸到 `2026-03-16`，而当前分钟数据只到 `2026-03-06 16:00:00`，这次所有命令都显式传入 `--eval-start 2025-03-07 --eval-end 2026-03-06`，保证分钟级与日频结果严格对齐同一评分窗口。
- 下方基线命令现在统一显式传入 `--initial-cash 800000`，避免港股文档再依赖脚本默认资金。
- `dual momentum` 现在从 `kline_day/` 读取日线数据；其他分钟策略仍从 `kline_minute/` 读取分钟数据。
- 分钟级股票池脚本与 `dual momentum` 都支持 `--eval-start` / `--eval-end`；窗口外数据只用于预热，不再混入评分结果。
- `dual momentum` 当前也使用与美股文档相同的显式参数：`lookback 40/120`、`top_n 1`、`market_filter_window 60`、`target_annual_vol 0.60`、`max_gross_exposure 1.20`。
- [`backtest_ema_rsi_bull_range.py`](backtest_ema_rsi_bull_range.py) 复用了 [`backtest_ema_rsi_combo.py`](backtest_ema_rsi_combo.py) 的股票池引擎，只是默认参数不同。

## 当前基线命令

后续更新这份文档时，优先复用下面这组命令（即当前与美股文档对齐的参数口径）：

```bash
./.venv/bin/python backtest/backtest_rsi_reversion.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --initial-cash 800000 \
  --fee-account futu_alt \
  --sell-threshold 70 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

./.venv/bin/python backtest/backtest_ema_cross.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --initial-cash 800000 \
  --fee-account futu_alt \
  --position-ratio 0.15 \
  --max-open-positions 1 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

./.venv/bin/python backtest/backtest_ema_rsi_combo.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --initial-cash 800000 \
  --fee-account futu_alt \
  --buy-threshold 35 \
  --sell-threshold 60 \
  --min-volume-ratio 1.2 \
  --max-open-positions 1 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

./.venv/bin/python backtest/backtest_ema_rsi_bull_range.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --initial-cash 800000 \
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

./.venv/bin/python backtest/backtest_dual_momentum.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --initial-cash 800000 \
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

- 只要是港股股票池结果、分析、结论更新，优先修改这份文档。
- 如果是美股股票池结果更新，修改 [美股股票池回测结果与分析](README_backtest_pool_us.md)。
- 如果是单标结果更新，修改 [单标的回测结果与分析](README_backtest_single_symbol.md)。
- 如果未来把股票池评估从单一窗口升级成滚动 walk-forward，也优先直接更新这份文档顶部口径，而不是只在根目录 `README.md` 里补一句。
