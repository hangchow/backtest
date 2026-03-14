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

## 默认参数

- 初始资金：`100000`
- 动量回看窗口：`90` 个交易日
- 长周期动量回看窗口：`180` 个交易日
- 长周期动量权重：`0.25`
- 同时持有标的数：`1`
- 成交量窗口：`20`
- 放量加分阈值：`1.3x` 最近均量
- `--show-trades`：`0`（默认，不打印交易记录）

## 基本用法

```bash
./.venv/bin/python scripts/backtest_dual_momentum.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA \
  --fee-account futu_alt
```

## 常用参数

- `--codes`：股票池代码列表
- `--data-root`：数据根目录，默认 `data`
- `--initial-cash`：初始资金
- `--lookback-days`：动量回看窗口
- `--top-n`：同时持有的最强标的数量
- `--fee-account`：可选费用账户（如 `futu_alt`）
- `--security-type`：费用规则对应证券类型（默认 `stock`）
- `--volume-window`：成交量比较窗口，用于计算当前量和近期均量的比值
- `--min-volume-ratio`：相对成交量高于这个阈值时，动量分数会得到放量加分
- `--show-trades`：`1` 打印所有交易记录；`0`（默认）不打印交易记录

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
