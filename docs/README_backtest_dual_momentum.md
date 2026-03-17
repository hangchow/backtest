# `backtest_dual_momentum.py` 使用说明

## 功能

这是一个股票池日频轮动策略：

- 用每只股票最近一段时间的涨幅做相对动量排序
- 只持有动量为正的标的，动量为负时留在现金
- 当日成交量明显高于最近均量时，会给该标的的动量分数额外加分
- 默认只持有最强的 `1` 只股票

这类做法对应文献里常见的 relative momentum + absolute momentum，也就是常说的 dual momentum。

## 脚本位置

`backtest/backtest_dual_momentum.py`

## 基本用法

```bash
./.venv/bin/python backtest/backtest_dual_momentum.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO \
  --market US \
  --initial-cash 100000 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --fee-account futu_alt
```

默认会从 `kline_day/<code>/` 读取按自然周拆分的日线 CSV。

## 常用参数

- `--codes`：股票池代码列表（必填）
- `--data-root`：数据根目录，默认 `kline_day`
- `--market`：必传，指定 `HK` 或 `US`；backtest 不会再从代码或目录名自动推断 market
- `--initial-cash`：初始资金，默认 `100000`
- `--lookback-days`：短周期动量回看窗口，默认 `90`
- `--long-lookback-days`：长周期动量回看窗口，默认 `180`
- `--long-lookback-weight`：长周期动量权重，默认 `0.25`
- `--top-n`：同时持有的最强标的数量，默认 `1`
- `--volume-window`：成交量比较窗口，默认 `20`
- `--min-volume-ratio`：放量加分阈值，默认 `1.3`
- `--market-filter-window`：市场风险开关均线窗口，默认 `120`
- `--rebalance-band-pct`：调仓带宽阈值，默认 `0.10`
- `--volatility-window`：波动率估计窗口，默认 `20`
- `--target-annual-vol`：组合年化波动率目标，默认 `0.30`
- `--max-gross-exposure`：最大总仓位倍率上限，默认 `1.0`（不使用杠杆）
- `--eval-start`：评估起点日期（可选），不传则按全样本统计
- `--eval-end`：评估终点日期（可选），不传则按全样本统计
- `--fee-account`：可选费用账户（如 `futu_alt`）
- `--security-type`：费用规则对应证券类型，默认 `stock`
- `--show-trades`：`1` 打印所有交易记录；`0`（默认）不打印交易记录

> 说明：当 `--max-gross-exposure > 1.0` 时，脚本会在“波动率目标缩放后的名义仓位上限”内进行受控放大，并在每笔买入前按当前仓位实时校验剩余可用名义仓位，避免超出上限。

## 指定股票池 + 双时间窗口（4 组回测）

按你的要求，分别用港股 8 只与美股 8 只股票池，在两个时间窗口上使用同一组参数（仅初始资金不同：港股 `800000`、美股 `100000`）重跑了 4 次：

- 参数一致：`lookback 40/120`、`long-weight 0.25`、`top-n 1`、`volume-window 20`、`min-volume-ratio 1.0`、`market-filter-window 60`、`rebalance-band 5%`、`volatility-window 20`、`target-annual-vol 0.60`、`max-gross-exposure 1.20`、`fee-account futu_alt`
- 时间窗口 A：`2025-01-01` 到 `2026-01-01`
- 时间窗口 B：`2025-03-07` 到 `2026-03-06`
- 港股股票池（8）：`HK.00700 HK.09988 HK.00005 HK.01810 HK.03690 HK.01211 HK.03750 HK.00981`
- 美股股票池（8）：`US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO`

### 4 组结果对比

| 市场 | 时间窗口 | 初始资金 | 交易次数(BUY/SELL) | 期末总资产 | 总收益率 | 最大回撤 |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| HK | 2025-01-01 ~ 2026-01-01 | 800000 | 62 (31/31) | 772409.98 | -3.45% | -54.84% |
| HK | 2025-03-07 ~ 2026-03-06 | 800000 | 64 (32/32) | 520437.21 | -34.95% | -51.79% |
| US | 2025-01-01 ~ 2026-01-01 | 100000 | 53 (27/26) | 185287.43 | 85.29% | -20.22% |
| US | 2025-03-07 ~ 2026-03-06 | 100000 | 50 (25/25) | 221343.02 | 121.34% | -14.44% |

## 共同参数调优（以提升 HK 为目标）

按“共享参数”的约束做了额外复跑后，当前可复现的最优折中参数是：

- `lookback 40/120`、`long-weight 0.25`、`top-n 1`
- `volume-window 20`、`min-volume-ratio 1.0`
- `market-filter-window 120`、`rebalance-band 5%`
- `volatility-window 20`、`target-annual-vol 0.80`、`max-gross-exposure 1.20`

该组参数能明显提升 HK 两个窗口收益，且交易频率仍在中等以上（HK 85/90 笔，US 45/42 笔），但 US 在窗口 B 收益会小幅回落（`121.34% -> 120.12%`）。

### 基线参数 vs 调优参数（收益率/交易次数）

| 市场 | 时间窗口 | 基线收益率 | 调优后收益率 | 基线交易次数 | 调优后交易次数 |
| --- | --- | ---: | ---: | ---: | ---: |
| HK | 2025-01-01 ~ 2026-01-01 | -3.45% | 6.19% | 62 | 85 |
| HK | 2025-03-07 ~ 2026-03-06 | -34.95% | -31.04% | 64 | 90 |
| US | 2025-01-01 ~ 2026-01-01 | 85.29% | 92.95% | 53 | 45 |
| US | 2025-03-07 ~ 2026-03-06 | 121.34% | 120.12% | 50 | 42 |

## 输出内容

脚本会输出：

- 回测区间
- 股票池
- 交易次数
- 期末现金
- 期末持仓
- 期末总资产
- 总收益率
- 最大回撤
