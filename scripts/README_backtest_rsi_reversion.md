# `backtest_rsi_reversion.py` 使用说明

## 功能

用腾讯分钟级 K 线数据回测一个简单的 RSI 反转策略：

- `RSI` 低于买入阈值时买入
- `RSI` 高于卖出阈值时卖出

## 脚本位置

`scripts/backtest_rsi_reversion.py`

## 默认参数

- 初始资金：`100000`
- `RSI period`：`6`
- 买入阈值：`30`
- 卖出阈值：`60`
- 买入仓位：`100%`
- 默认允许隔夜持仓

## 基本用法

直接运行默认参数：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py
```

如果要每天收盘前强制平仓：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py --flat-at-close
```

## 常用参数

- `--data-dir`：数据目录，默认 `data/HK.00700`
- `--initial-cash`：初始资金
- `--rsi-period`：RSI 周期
- `--buy-threshold`：买入阈值
- `--sell-threshold`：卖出阈值
- `--position-ratio`：每次买入使用的现金比例，范围 `(0, 1]`
- `--flat-at-close`：收盘前平仓
- `--show-trades`：打印前后各多少笔交易，设为 `0` 可关闭

## 示例

自定义参数运行：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py \
  --initial-cash 100000 \
  --rsi-period 6 \
  --buy-threshold 30 \
  --sell-threshold 60 \
  --position-ratio 1.0
```

不打印交易样例：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py --show-trades 0
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
