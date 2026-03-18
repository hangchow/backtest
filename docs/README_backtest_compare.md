# `backtest_compare.py` 使用说明

## 功能

`backtest/backtest_compare.py` 会比较两类策略：

- 分钟级策略
  - `rsi_reversion`
  - `ema_cross`
  - `ema_rsi_combo`
  - `ema_rsi_bull_range`
- 原生股票池策略
  - `dual_momentum`
  - `momentum_monthly`
  - `dual_momentum_ema_rsi_hybrid`

脚本会按默认参数运行所选策略，并把结果整理成 Markdown 报告输出到标准输出。前 4 个分钟级策略既可以出现在单标 section，也可以在多标场景下以股票池模式出现在股票池 section。`--market` 仍然是必传参数，脚本不会从代码前缀自动推断市场。

默认评估窗口是 `2025-03-07` 到 `2026-03-06`。如果本地数据里有更早的数据，脚本会自动把它用于指标预热，但不会把它计入默认回测统计窗口。

## 默认行为

- 默认 `--scope single`
- 不传 `--scope` 时：只比较 4 个分钟级策略的单标模式
- 如果你想看股票池结果，必须显式传 `--scope pool`
- 如果你既想看单标结果又想看股票池结果，就分别跑两次
- 如果你想限制比较范围，可以重复传 `--strategy`
- 如果你想显式控制输出范围，使用 `--scope`
  - `single`：只跑单标 section
  - `pool`：只跑股票池 section

## 数据要求

- 分钟级策略的单标模式读取 `kline_minute/<code>/`
- 分钟级策略的股票池模式也读取 `kline_minute/<code>/`
- `dual_momentum` / `momentum_monthly` 读取 `kline_day/<code>/`
- `dual_momentum_ema_rsi_hybrid` 同时读取
  - `kline_day/<code>/`
  - `kline_minute/<code>/`
- 所有 `--code` 必须和 `--market` 一致，且不能混用 HK/US

## 基本用法

单标默认比较 4 个分钟级策略的单标模式：

```bash
./.venv/bin/python backtest/backtest_compare.py \
  --market US \
  --code US.MSFT
```

只跑单标 section：

```bash
./.venv/bin/python backtest/backtest_compare.py \
  --scope single \
  --market US \
  --code US.MSFT \
  --code US.TSLA
```

输出

```text
## 回测数据集

### kline_minute（RSI reversion, EMA cross, EMA + RSI, EMA + RSI bull range）

| code    |   rows | days | start               | end                 |
| ------- | -----: | ---: | ------------------- | ------------------- |
| US.MSFT | 317760 |  500 | 2024-03-15 09:30:00 | 2026-03-13 19:59:00 |
| US.TSLA | 461744 |  500 | 2024-03-15 09:30:00 | 2026-03-13 19:59:00 |

## 单标策略对比

| code    | strategy             | final_value | return_pct | max_drawdown_pct | trade_count | duration |
| ------- | -------------------- | ----------: | ---------: | ---------------: | ----------: | -------- |
| US.MSFT | RSI reversion        |   294887.69 |     194.89 |            -5.72 |        6875 | 0:02     |
| US.MSFT | EMA + RSI            |   151271.44 |      51.27 |            -4.54 |        4918 | 0:02     |
| US.MSFT | EMA + RSI bull range |   149518.19 |      49.52 |           -10.70 |        7940 | 0:02     |
| US.MSFT | EMA cross            |    78623.92 |     -21.38 |           -26.97 |        1786 | 0:02     |
| US.TSLA | EMA + RSI bull range |   171579.27 |      71.58 |           -12.23 |       11128 | 0:03     |
| US.TSLA | RSI reversion        |   170724.53 |      70.72 |           -31.35 |       10257 | 0:03     |
| US.TSLA | EMA + RSI            |   154629.52 |      54.63 |           -16.93 |        7472 | 0:03     |
| US.TSLA | EMA cross            |   103626.50 |       3.63 |           -14.91 |        2288 | 0:03     |
```

只跑股票池 section：

```bash
./.venv/bin/python backtest/backtest_compare.py \
  --scope pool \
  --market HK \
  --code HK.00700 \
  --code HK.09988 \
  --code HK.00005
```

只跑股票池 section，且只保留原生股票池策略：

```bash
./.venv/bin/python backtest/backtest_compare.py \
  --scope pool \
  --market HK \
  --code HK.00700 \
  --code HK.09988 \
  --code HK.00005 \
  --strategy dual_momentum \
  --strategy momentum_monthly \
  --strategy dual_momentum_ema_rsi_hybrid
```

输出

```
## 回测数据集

### kline_minute（Dual momentum + EMA + RSI hybrid）

| code     |   rows | days | start               | end                 |
| -------- | -----: | ---: | ------------------- | ------------------- |
| HK.00700 | 161110 |  490 | 2024-03-07 09:30:00 | 2026-03-06 16:00:00 |
| HK.09988 | 161110 |  490 | 2024-03-07 09:30:00 | 2026-03-06 16:00:00 |
| HK.00005 | 161110 |  490 | 2024-03-07 09:30:00 | 2026-03-06 16:00:00 |

### kline_day（Dual momentum, Momentum monthly, Dual momentum + EMA + RSI hybrid）

| code     | rows | days | start      | end        |
| -------- | ---: | ---: | ---------- | ---------- |
| HK.00700 |  490 |  490 | 2024-03-15 | 2026-03-16 |
| HK.09988 |  490 |  490 | 2024-03-15 | 2026-03-16 |
| HK.00005 |  490 |  490 | 2024-03-15 | 2026-03-16 |

## 股票池策略对比

| pool        | strategy                         | final_value | return_pct | max_drawdown_pct | trade_count | duration |
| ----------- | -------------------------------- | ----------: | ---------: | ---------------: | ----------: | -------- |
| HK pool (3) | Momentum monthly                 |  1270594.20 |      58.82 |           -22.03 |           9 | 0:00     |
| HK pool (3) | Dual momentum + EMA + RSI hybrid |   928759.18 |      16.09 |           -19.70 |          20 | 0:03     |
| HK pool (3) | Dual momentum                    |   828150.49 |       3.52 |           -25.88 |          36 | 0:03     |
```

指定分钟/日线数据根目录：

```bash
./.venv/bin/python backtest/backtest_compare.py \
  --minute-data-root /path/to/kline_minute \
  --daily-data-root /path/to/kline_day \
  --market US \
  --code US.MSFT \
  --code US.NVDA
```

覆盖默认评估窗口：

```bash
./.venv/bin/python backtest/backtest_compare.py \
  --market US \
  --code US.MSFT \
  --code US.NVDA \
  --eval-start 2025-01-01 \
  --eval-end 2026-01-01
```

统一指定所有策略的初始资金：

```bash
./.venv/bin/python backtest/backtest_compare.py \
  --market HK \
  --initial-cash 800000 \
  --code HK.00700 \
  --code HK.09988
```

把输出直接保存成 Markdown 文件：

```bash
./.venv/bin/python backtest/backtest_compare.py \
  --market US \
  --code US.MSFT \
  --code US.NVDA \
  > /tmp/backtest_compare_report.md
```

## 参数说明

- `--code`：要比较的标的代码；必须重复传入，不能写成一个参数后面跟多个值
- `--market`：必传，只能传当前股票代码对应的市场
- `--minute-data-root`：分钟数据根目录；`--data-root` 仍可作为它的别名
- `--daily-data-root`：日线数据根目录
- `--scope`：控制输出范围；可选值：
  - `single`：默认；只跑单标 section
  - `pool`：只跑股票池 section
- `--eval-start`：评估开始时间，默认 `2025-03-07`
- `--eval-end`：评估结束时间，默认 `2026-03-06`
- `--initial-cash`：所有比较策略共用的初始资金；不传时按市场默认
  - `HK`：`800000`
  - `US`：`100000`
- `--strategy`：可重复传入，用来限制比较的策略集合；可选值：
  - `rsi_reversion`
  - `ema_cross`
  - `ema_rsi_combo`
  - `ema_rsi_bull_range`
  - `dual_momentum`
  - `momentum_monthly`
  - `dual_momentum_ema_rsi_hybrid`
- 当 `--scope pool` 时，前 4 个分钟级策略会进入股票池 section，走各自的 `run_portfolio_backtest(...)`

## 输出内容

脚本会按实际比较范围输出最多 3 个 Markdown 小节：

- `回测数据集`
- `单标策略对比`
- `股票池策略对比`

其中：

- `回测数据集` 按每个 `code` 展示本次比较使用的数据集行数、交易日数、起止时间
- 单标模式下，`回测数据集` 会显示 `kline_minute` 子标题，括号里标出本次比较用到的分钟级策略名
- 股票池模式下，`回测数据集` 会按数据源拆分成 `kline_minute` / `kline_day`
- 股票池模式下，子标题括号里会标出使用该数据集的策略名字
- 浮点数统一格式化为两位小数
- `单标策略对比` 按 `code` 分组，并在每个 `code` 组内按 `return_pct` 从高到低排序
- 多标时，`股票池策略对比` 会同时包含：
  - 4 个分钟级策略的股票池执行模式（共享资金、共享持仓上限）
  - `dual_momentum` / `momentum_monthly` / `dual_momentum_ema_rsi_hybrid`
- `单标策略对比` 最后一列 `duration` 显示每个 `code + strategy` 组合在 compare 脚本中的耗时，格式为 `分钟:秒`
- `股票池策略对比` 按 `return_pct` 从高到低排序
- `股票池策略对比` 最后一列 `duration` 显示每个策略在 compare 脚本中的耗时，格式为 `分钟:秒`
- 使用 `--scope pool` 时，只会输出股票池相关 section
- 使用 `--scope single` 时，只会输出单标相关 section
- 不支持一个命令同时跑单标和股票池两类结果
- 收益、回撤、交易次数按 `--eval-start/--eval-end` 窗口统计

## 当前比较口径

这个脚本仍然是“默认参数基线对比工具”，不是参数搜索框架：

- 分钟级策略在单标 section 里使用各自脚本的默认单标参数
- 原生股票池策略使用各自脚本的默认参数
- 其中 4 个分钟级策略在股票池 section 里走的是各自脚本的 `run_portfolio_backtest(...)` 口径，而不是把单标结果简单拼起来
- compare 脚本只统一两件事
  - `market`
  - `initial_cash`

这意味着它适合做“同一份数据下的默认策略横向观察”，不适合替代单个脚本的调参实验。

## 限制

- 不支持直接透传费用账户、评估窗口或策略超参数
- 输出只打印到终端，不会自动写文件
- `--scope pool` 且只传 1 个 `--code` 时，默认只会跑 3 个原生股票池策略；4 个分钟级策略的股票池模式需要至少 2 个 code
- 原生股票池策略在只有 1 个 `code` 时也能运行，但结果的参考意义通常不如多标股票池
