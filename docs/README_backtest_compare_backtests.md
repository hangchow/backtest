# `compare_backtests.py` 使用说明

## 功能

`backtest/compare_backtests.py` 用来快速横向比较同一批分钟级数据在 4 个默认分钟策略下的结果：

- `RSI reversion`
- `EMA cross`
- `EMA + RSI`
- `EMA + RSI bull range`

脚本会依次读取每个标的的分钟 K 线，运行上述 4 个脚本的默认参数回测，然后把结果整理成一份 Markdown 报告输出到标准输出。

## 脚本位置

`backtest/compare_backtests.py`

## 适用场景

- 想快速看某个标的更适合哪一种默认分钟策略
- 想同时比较多个标的在默认参数下的收益、回撤和交易频率
- 想把比较结果直接重定向成 Markdown 文档

## 数据要求

- 默认从 `kline_minute/<code>/` 读取分钟数据
- 每个 `code` 对应一个目录，例如 `kline_minute/US.MSFT/`
- 目录里至少要有一份 CSV；否则底层 `load_history()` 会报错

## 基本用法

比较单个标的：

```bash
./.venv/bin/python backtest/compare_backtests.py --code US.MSFT
```

比较多个标的：

```bash
./.venv/bin/python backtest/compare_backtests.py \
  --code US.MSFT \
  --code US.NVDA \
  --code US.AAPL
```

指定自定义数据根目录：

```bash
./.venv/bin/python backtest/compare_backtests.py \
  --data-root /path/to/kline_minute \
  --code HK.00700 \
  --code HK.09988
```

把输出直接保存成 Markdown 文件：

```bash
./.venv/bin/python backtest/compare_backtests.py \
  --code US.MSFT \
  --code US.NVDA \
  > /tmp/compare_backtests_report.md
```

## 参数说明

- `--code`：要比较的标的代码；必须重复传入，不能写成一个参数后面跟多个值
- `--data-root`：分钟数据根目录，默认是 `kline_minute`

## 输出内容

脚本会输出 3 个 Markdown 小节：

- `数据概览`：每个标的数据行数、交易天数、起止时间
- `回测对比`：每个标的在 4 个策略下的 `final_value`、`return_pct`、`max_drawdown_pct`、`trade_count`
- `每个标的的最佳结果`：按 `final_value` 最高选出该标的当前最佳策略

其中浮点数会统一格式化为两位小数。

## 当前比较口径

这个脚本不是“任意参数回测框架”，而是固定比较 4 个脚本的默认参数：

- `RSI reversion`：默认允许隔夜持仓
- `EMA cross`：默认 `flat_at_close=True`
- `EMA + RSI`：默认允许隔夜持仓
- `EMA + RSI bull range`：默认允许隔夜持仓

也就是说，这份对比更适合做“默认参数基线观察”，不适合拿来替代单个脚本的参数调优。

## 限制

- 只比较分钟级单标策略，不包含 `dual momentum`、`momentum_monthly` 或股票池回测脚本
- 不支持直接传入费用账户、评估窗口或策略参数
- 输出只打印到终端，不会自动写文件
- “最佳结果” 仅按 `final_value` 排序，不按风险调整收益排序
