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

按 `2025-03-07` 到 `2026-03-06` 记分窗口里的收益率排序（股票池为 `HK.00700 HK.09988 HK.00005 HK.01810 HK.03690 HK.01211 HK.03750 HK.00981`）：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| EMA cross | minute | 531025.84 | -33.62 | -34.11 | 1313 |
| dual momentum | daily | 520437.21 | -34.95 | -51.79 | 64 |
| RSI reversion | minute | 378.63 | -99.95 | -99.95 | 16554 |
| EMA + RSI | minute | 33.33 | -100.00 | -100.00 | 3570 |
| EMA + RSI bull range | minute | 33.33 | -100.00 | -100.00 | 3570 |

## 结果解读

- 把港股股票池从 3 只扩到 8 只之后，收益榜第一名从 `dual momentum` 变成了 `EMA cross`。不过 `EMA cross` 也只有 `return_pct = -33.62%`，说明股票池扩容并没有改善这套参数的样本外表现，只是让相对排序发生了变化。
- `dual momentum` 这轮退到第二名，`final_value = 520437.21`、`return_pct = -34.95%`、`max_drawdown_pct = -51.79%`。它比 `EMA cross` 少交易很多，但回撤反而更深，说明在这 8 只港股里，日频轮动的筛选优势被明显削弱了。
- `RSI reversion` 扩池后进一步恶化到几乎归零，`final_value = 378.63`、`return_pct = -99.95%`，交易数暴增到 `16554`。这基本延续了同一个结论：高换手逆势均值回归在港股分钟级样本里会被费用和噪音持续碾压。
- `EMA + RSI` 与 `EMA + RSI bull range` 这次仍完全一致，都是 `3570` 笔交易、`final_value = 33.33`。这说明在当前参数和股票池下，bull range 约束依旧没有改变实际成交路径。
- `HK.03750` 的可用历史明显短于另外 7 只股票，分钟数据从 `2025-05-20` 才开始，日线周文件从 `2025-05-19` 那周才开始。回测脚本仍能跑完，说明它会容忍单个标的早期窗口缺失，但这也让 8 只股票池结果不再是完全等长历史样本上的对比。

## 实现备注

- 本文档结果记录的是 `2026-03-17` 那轮港股股票池实际复跑输出；下方基线命令现已显式补齐 `--initial-cash 800000`，用于对齐统一港股资金口径。
- 本轮股票池使用：`HK.00700 HK.09988 HK.00005 HK.01810 HK.03690 HK.01211 HK.03750 HK.00981`。
- `EMA cross` 这次输出为：`Trades = 1313 (BUY 657, SELL 656)`、`Final value = 531025.84`、`Total return = -33.62%`、`Max drawdown = -34.11%`。
- `dual momentum` 这次输出为：`Trades = 64 (BUY 32, SELL 32)`、`Final value = 520437.21`、`Total return = -34.95%`、`Max drawdown = -51.79%`。
- `RSI reversion` 这次输出为：`Trades = 16554 (BUY 8277, SELL 8277)`、`Final value = 378.63`、`Total return = -99.95%`、`Max drawdown = -99.95%`。
- `EMA + RSI` 与 `EMA + RSI bull range` 这次输出仍完全一致，都是 `Trades = 3570 (BUY 1785, SELL 1785)`、`Final value = 33.33`、`Total return = -100.00%`、`Max drawdown = -100.00%`。
- `HK.03750` 当前本地数据窗口短于其他标的：分钟文件从 `2025-05-20` 开始，日线周文件从 `2025-05-19` 当周开始。
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
  --codes HK.00700 HK.09988 HK.00005 HK.01810 HK.03690 HK.01211 HK.03750 HK.00981 \
  --initial-cash 800000 \
  --fee-account futu_alt \
  --sell-threshold 70 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

./.venv/bin/python backtest/backtest_ema_cross.py \
  --codes HK.00700 HK.09988 HK.00005 HK.01810 HK.03690 HK.01211 HK.03750 HK.00981 \
  --initial-cash 800000 \
  --fee-account futu_alt \
  --position-ratio 0.15 \
  --max-open-positions 1 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --show-trades 0

./.venv/bin/python backtest/backtest_ema_rsi_combo.py \
  --codes HK.00700 HK.09988 HK.00005 HK.01810 HK.03690 HK.01211 HK.03750 HK.00981 \
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
  --codes HK.00700 HK.09988 HK.00005 HK.01810 HK.03690 HK.01211 HK.03750 HK.00981 \
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
  --codes HK.00700 HK.09988 HK.00005 HK.01810 HK.03690 HK.01211 HK.03750 HK.00981 \
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
