# `backtest_dual_momentum.py` 使用说明

## 功能

这是一个股票池日频轮动策略：

- 用每只股票最近一段时间的涨幅做相对动量排序
- 只持有动量为正的标的，动量为负时留在现金
- 当日成交量明显高于最近均量时，会给该标的的动量分数额外加分
- 默认只持有最强的 `1` 只股票

这类做法对应文献里常见的 relative momentum + absolute momentum，也就是常说的 dual momentum。

## 脚本位置

`scripts/backtest_dual_momentum.py`

## 基本用法

```bash
./.venv/bin/python scripts/backtest_dual_momentum.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt
```

## 常用参数

- `--codes`：股票池代码列表（必填）
- `--data-root`：数据根目录，默认 `data`
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
- `--fee-account`：可选费用账户（如 `futu_alt`）
- `--security-type`：费用规则对应证券类型，默认 `stock`
- `--show-trades`：`1` 打印所有交易记录；`0`（默认）不打印交易记录

> 说明：当 `--max-gross-exposure > 1.0` 时，脚本会在“波动率目标缩放后的名义仓位上限”内进行受控放大，并在每笔买入前按当前仓位实时校验剩余可用名义仓位，避免超出上限。

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
