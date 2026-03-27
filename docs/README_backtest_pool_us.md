# 美股股票池回测结果与分析
这份文档只记录美股股票池相关工作

## 统一回测口径与账户费用

- [回测统一口径（backtest/README.md）](../backtest/README.md#回测统一口径)
- [账户费用规则（backtest/README.md）](../backtest/README.md#费用规则futu_alt)

- 本文档只保留美股股票池的结果表、最少量结论和复现命令；统一口径与费用细则以上面两份基线文档为准。

## 优化参数股票池收益榜（窗口一）

按 `2025-03-07` 到 `2026-03-06` 记分窗口里的收益率排序（股票池扩展为 `US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO US.GLD`）：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| dual momentum | daily | 166616.16 | 66.62 | -20.92 | 54 |
| EMA + RSI | minute | 165536.79 | 65.54 | -10.93 | 12936 |
| EMA + RSI bull range | minute | 165536.79 | 65.54 | -10.93 | 12936 |
| EMA cross | minute | 89639.92 | -10.36 | -10.53 | 2831 |
| RSI reversion | minute | 42774.79 | -57.23 | -57.62 | 48595 |

## 优化参数股票池收益榜（窗口二）

按新增记分窗口 `2025-01-01` 到 `2026-01-01`（交易日实际落在 `2025-01-02` 到 `2025-12-31`）收益率排序（股票池同样为 `US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO US.GLD`）：

| strategy | frequency | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| EMA + RSI | minute | 166096.84 | 66.10 | -16.45 | 12818 |
| EMA + RSI bull range | minute | 166096.84 | 66.10 | -16.45 | 12818 |
| dual momentum | daily | 157978.18 | 57.98 | -20.90 | 57 |
| EMA cross | minute | 92821.41 | -7.18 | -9.23 | 2686 |
| RSI reversion | minute | 37385.02 | -62.61 | -62.78 | 48009 |

## 结论与复现

- 本文档结果是 `2026-03-27` 对 9 只股票池 `US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO US.GLD` 的最新双窗口复跑；具体数值以上面两张表为准。
- 窗口一里 `dual momentum` 仍是第一，但只小幅领先 `EMA + RSI`；窗口二里榜首切换成 `EMA + RSI` / `EMA + RSI bull range`，而且回撤也优于 `dual momentum`。
- `EMA + RSI bull range` 与 `EMA + RSI` 结果完全一致，因为股票池模式下它直接复用 [`backtest_ema_rsi_combo.py`](../backtest/backtest_ema_rsi_combo.py) 的执行引擎，当前基线参数也已收敛到同一组区间。
- `EMA cross` 仍是低收益、相对低回撤基线；`RSI reversion` 仍是高换手、最差结果的策略。
- `US.GLD` 的本地日线和分钟线已补齐；当前数据目录覆盖到 `2026-03-26`。
- 本文档固定维护两套评分窗口：`2025-03-07 ~ 2026-03-06` 和 `2025-01-01 ~ 2026-01-01`。所有命令都显式传入 `--eval-start/--eval-end`，窗口外数据只用于预热；`dual momentum` 额外支持 `--max-gross-exposure`。

## 当前基线命令

后续更新这份文档时，优先复用批量脚本和参数文件 [baseline_strategy_config.json](./backtest_pool_us/baseline_strategy_config.json)。它固定当前表格使用的 5 个策略参数：`rsi_reversion`、`ema_cross`、`ema_rsi_combo`、`ema_rsi_bull_range`、`dual_momentum`。

窗口一：

```bash
./.venv/bin/python -m backtest.backtest_pool_batch \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO US.GLD \
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
  --strategy-config docs/backtest_pool_us/baseline_strategy_config.json
```

窗口二：

```bash
./.venv/bin/python -m backtest.backtest_pool_batch \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO US.GLD \
  --market US \
  --initial-cash 100000 \
  --fee-account futu_alt \
  --eval-start 2025-01-01 \
  --eval-end 2026-01-01 \
  --strategy rsi_reversion \
  --strategy ema_cross \
  --strategy ema_rsi_combo \
  --strategy ema_rsi_bull_range \
  --strategy dual_momentum \
  --strategy-config docs/backtest_pool_us/baseline_strategy_config.json
```

## 更新约定

- 只要是美股股票池结果、分析、结论更新，优先修改这份文档。
- 如果是港股股票池结果更新，修改港股股票池文档；如果是单标结果更新，修改单标文档。
- 如果未来把股票池评估从单一窗口升级成滚动 walk-forward，也优先直接更新这份文档顶部口径，而不是只在根目录 `README.md` 里补一句。
