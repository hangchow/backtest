# `backtest_rsi_reversion.py` 使用说明

## 功能

用分钟级 K 线数据回测一个简单的 RSI 反转策略：

- `RSI` 低于买入阈值时买入
- 买点还要求当前成交量不低于最近均量的一定比例，用来过滤过薄的反转信号
- `RSI` 高于卖出阈值时卖出

## 脚本位置

`backtest/backtest_rsi_reversion.py`

## 结果边界

- 文档里的收益数字（如有）都只是样本内结果。
- 回测还没有计入手续费、平台费、印花税、滑点。
- 目前也没有处理港股整手限制，回测允许按股数买卖。

## 基本用法

指定标的代码运行：

```bash
./.venv/bin/python backtest/backtest_rsi_reversion.py --codes HK.00700 --initial-cash 800000
```

如果要每天收盘前强制平仓：

```bash
./.venv/bin/python backtest/backtest_rsi_reversion.py --codes HK.00700 --initial-cash 800000 --flat-at-close
```

## 常用参数

- `--codes`：股票代码列表（空格分隔），脚本会从 `kline_minute/<code>/` 读取数据
- `--data-root`：配合 `--codes` 使用的数据根目录，默认 `kline_minute`
- `--data-dir`：直接指定单标的数据目录；不能和 `--codes` 同时使用
- `--initial-cash`：初始资金，默认 `100000`
- `--rsi-period`：RSI 周期，默认 `6`
- `--buy-threshold`：买入阈值，默认 `30`
- `--sell-threshold`：卖出阈值，默认 `60`
- `--position-ratio`：每次买入使用的现金比例，范围 `(0, 1]`，默认 `1.0`
- `--max-open-positions`：股票池模式下的最大同时持仓数，默认 `-1`（不限制）
- `--eval-start`：评估起点（可选）；更早的 K 线只用于指标预热，不计入交易和收益
- `--eval-end`：评估终点（可选）；更晚的 K 线不计入交易和收益
- `--volume-window`：成交量比较窗口，用于计算当前量和近期均量的比值，默认 `5`
- `--min-volume-ratio`：买点要求的最小相对成交量，默认 `0.6`
- `--flat-at-close`：收盘前平仓（默认允许隔夜，即不传该参数）
- `--show-trades`：打印前后各多少笔交易，默认显示首尾 `10` 笔，设为 `0` 可关闭

## 示例

自定义参数运行：

```bash
./.venv/bin/python backtest/backtest_rsi_reversion.py \
  --codes HK.00700 \
  --initial-cash 800000 \
  --rsi-period 6 \
  --buy-threshold 30 \
  --sell-threshold 60 \
  --position-ratio 1.0
```

不打印交易样例：

```bash
./.venv/bin/python backtest/backtest_rsi_reversion.py --codes HK.00700 --initial-cash 800000 --show-trades 0
```

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
