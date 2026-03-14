# 港股股票池回测结果与分析

- 这份文档当前结果基于统一费用口径（`--fee-account futu_alt`）的全样本回测
- 费用与参数口径请以「统一回测口径与账户费用」小节所链接基线文档为准
- 这还不是完整的滚动 walk-forward，只是一段固定的样本外窗口
- 没有处理港股整手限制、停牌、除权除息等问题

## 统一回测口径与账户费用

- [回测统一口径（scripts/README.md）](README.md#回测统一口径)
- [账户费用规则（scripts/README.md）](README.md#费用规则futu_alt)

- 本文档聚焦港股股票池结果、解读与复现命令，不再重复维护统一口径与费用细则。

## 默认参数股票池收益榜

按本次重跑结果的收益率排序：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| dual momentum | daily | 259451.03 | 159.45 | -29.97 | 47 |
| EMA cross | minute | 210.59 | -99.79 | -99.79 | 2640 |
| RSI reversion | minute | 132.19 | -99.87 | -99.87 | 2706 |
| EMA + RSI | minute | 129.15 | -99.87 | -99.87 | 2680 |
| EMA + RSI bull range | minute | 116.74 | -99.88 | -99.88 | 2674 |

## 结果解读

- 本次重跑下，`dual momentum` 显著领先（`return_pct = 159.45%`），与分钟级策略形成明显分化。
- 四个分钟级策略在当前费用口径下全部接近“净值归零”区间（`-99.79%` 到 `-99.88%`），说明高换手 + 费用冲击非常明显。
- 在分钟策略内部，`EMA cross` 相对最优（`-99.79%`），`EMA + RSI bull range` 最弱（`-99.88%`），但差异已非常接近极限亏损区间。
- `dual momentum` 的交易数仅 `47`，远低于分钟级策略（约 `2.6k`~`2.7k`），低换手在费用环境下优势明显。

## 实现备注

- 本文档结果基于各策略当前默认参数与统一费用口径重跑；分钟级策略命令以当前脚本实际支持参数为准。
- `dual momentum` 支持 `--eval-start`，按日频交易日解释该起点；若不传该参数则按全样本区间统计。
- [`backtest_ema_rsi_bull_range.py`](backtest_ema_rsi_bull_range.py) 复用了 [`backtest_ema_rsi_combo.py`](backtest_ema_rsi_combo.py) 的股票池引擎，只是默认参数不同。

## 当前基线命令

后续更新这份文档时，优先复用下面这组命令：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --fee-account futu_alt \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_cross.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --fee-account futu_alt \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_combo.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --fee-account futu_alt \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --fee-account futu_alt \
  --show-trades 0

./.venv/bin/python scripts/backtest_dual_momentum.py \
  --codes HK.00700 HK.09988 HK.00005 \
  --fee-account futu_alt \
  --show-trades 0
```

## 更新约定

- 只要是港股股票池结果、分析、结论更新，优先修改这份文档。
- 如果是美股股票池结果更新，修改 [美股股票池回测结果与分析](README_backtest_us_stock_pool.md)。
- 如果是单标结果更新，修改 [单标的回测结果与分析](README_backtest_single_symbol.md)。
- 如果未来把股票池评估从单一窗口升级成滚动 walk-forward，也优先直接更新这份文档顶部口径，而不是只在根目录 `README.md` 里补一句。
