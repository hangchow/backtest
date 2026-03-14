# 美股股票池回测结果与分析
这份文档只记录美股股票池相关工作

## 统一回测口径与账户费用

- [回测统一口径（scripts/README.md）](README.md#回测统一口径)
- [账户费用规则（scripts/README.md）](README.md#费用规则futu_alt)

- 本文档聚焦美股股票池结果、解读与复现命令，不再重复维护统一口径与费用细则。

## 默认参数股票池收益榜

按 `2025-03-07` 到 `2026-03-06` 记分窗口里的收益率排序：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| RSI reversion | minute | 117827.65 | 17.83 | -27.37 | 25969 |
| EMA + RSI | minute | 90197.59 | -9.80 | -14.78 | 22386 |
| EMA cross | minute | 75639.22 | -24.36 | -46.33 | 4846 |
| EMA + RSI bull range | minute | 32107.89 | -67.89 | -69.33 | 35532 |
| dual momentum | daily | 28097.06 | -71.90 | -90.77 | 88 |

## 结果解读

- 在本次按统一费用口径（`--fee-account futu_alt`）重跑后，`RSI reversion` 成为收益第一（`return_pct = 17.83%`），但回撤明显扩大到 `-27.37%`。
- `EMA + RSI` 本次结果转为负收益（`-9.80%`），但回撤（`-14.78%`）显著小于其它多数策略，表现更偏防守。
- `EMA cross` 交易数明显低于其它分钟策略（`4846`），但收益与回撤都弱于 `RSI reversion` 与 `EMA + RSI`。
- `EMA + RSI bull range` 在当前口径下回撤与收益表现都较弱（`return_pct = -67.89%`，`max_drawdown_pct = -69.33%`），高换手下费用影响较重。
- `dual momentum` 在本次参数与费用口径下表现最弱（`return_pct = -71.90%`，`max_drawdown_pct = -90.77%`）；与此前版本相比，说明其对评估窗口与费用设定较敏感。

## 实现备注

- 本文档结果基于各策略当前默认参数与统一费用口径重跑；分钟级策略命令以当前脚本实际支持参数为准。
- `dual momentum` 支持 `--eval-start`，按日频交易日解释该起点；若不传该参数则按全样本区间统计。
- [`backtest_ema_rsi_bull_range.py`](backtest_ema_rsi_bull_range.py) 复用了 [`backtest_ema_rsi_combo.py`](backtest_ema_rsi_combo.py) 的股票池引擎，只是默认参数不同。

## 当前基线命令

后续更新这份文档时，优先复用下面这组命令：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_cross.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_combo.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt \
  --show-trades 0

./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt \
  --show-trades 0

./.venv/bin/python scripts/backtest_dual_momentum.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt \
  --show-trades 0
```

## 更新约定

- 只要是美股股票池结果、分析、结论更新，优先修改这份文档。
- 如果是港股股票池结果更新，修改港股股票池文档；如果是单标结果更新，修改单标文档。
- 如果未来把股票池评估从单一窗口升级成滚动 walk-forward，也优先直接更新这份文档顶部口径，而不是只在根目录 `README.md` 里补一句。
