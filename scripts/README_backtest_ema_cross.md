# `backtest_ema_cross.py` 使用说明

## 功能

用分钟级 K 线数据回测一个 EMA 金叉死叉策略：

- 短周期 EMA 上穿长周期 EMA 时买入
- 短周期 EMA 下穿长周期 EMA 时卖出
- 成交量不会直接否决金叉信号，但放量的候选会优先成交，而且仓位会略微放大
- 默认允许隔夜；加 `--flat-at-close` 可改成日内平仓

## 脚本位置

`scripts/backtest_ema_cross.py`

## 结果边界

- 文档中的样例数字（如有）只是样本内结果。
- 回测还没有计入手续费、平台费、印花税、滑点。
- 目前也没有处理港股整手限制，回测允许按股数买卖。

## 基本用法

```bash
./.venv/bin/python scripts/backtest_ema_cross.py --codes HK.00700
```

如果你不想隔夜持仓：

```bash
./.venv/bin/python scripts/backtest_ema_cross.py --codes HK.00700 --flat-at-close
```

## 常用参数

- `--codes`：股票代码列表（空格分隔），脚本会从 `data/<code>/` 读取数据
- `--data-root`：配合 `--codes` 使用的数据根目录，默认 `data`
- `--data-dir`：直接指定单标的数据目录；不能和 `--codes` 同时使用
- `--initial-cash`：初始资金，默认 `100000`
- `--fast-span`：短周期 EMA，默认 `30`
- `--slow-span`：长周期 EMA，默认 `120`
- `--position-ratio`：每次买入使用的现金比例，范围 `(0, 1]`，默认 `0.5`
- `--max-open-positions`：股票池模式下的最大同时持仓数，默认 `-1`（不限制）
- `--volume-window`：成交量比较窗口，用于计算当前量和近期均量的比值，默认 `5`
- `--min-volume-ratio`：相对成交量高于这个阈值时，可在基础仓位上做放量加仓，默认 `0.6`
- `--flat-at-close`：每天最后一分钟强制平仓（默认允许隔夜，即不传该参数）
- `--show-trades`：打印前后各多少笔交易，默认显示首尾 `10` 笔，设为 `0` 可关闭

## 输出内容

脚本会输出：

- 回测区间
- 策略参数
- 交易次数
- 期末现金
- 期末持仓
- 期末总资产
- 总收益率
- 最大回撤
