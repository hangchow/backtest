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

## 结果边界

- 文档里的收益数字只是当前这段腾讯样本上的样本内结果。
- 回测还没有计入手续费、平台费、印花税、滑点。
- 目前也没有处理港股整手限制，回测允许按股数买卖。

## 当前样本上的结果

默认参数下，这个策略在当前腾讯样本上的结果是：

- 回测区间：`2025-03-07 09:30:00` 到 `2026-03-06 16:00:00`
- 结果已在 `2026-03-08` 用修正后的 RSI 实现重新验证
- 期末总资产：`604046.80` 港币
- 总收益率：`504.05%`
- 最大回撤：`-10.19%`
- 交易次数：`3628`

## 基本用法

指定标的代码运行：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py --code HK.00700
```

如果要每天收盘前强制平仓：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py --code HK.00700 --flat-at-close
```

## 常用参数

- `--code`：股票代码，脚本会从 `data/<code>/` 读取数据
- `--data-root`：配合 `--code` 使用的数据根目录，默认 `data`
- `--data-dir`：直接指定完整数据目录；传了以后会覆盖 `--code`
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
  --code HK.00700 \
  --initial-cash 100000 \
  --rsi-period 6 \
  --buy-threshold 30 \
  --sell-threshold 60 \
  --position-ratio 1.0
```

不打印交易样例：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py --code HK.00700 --show-trades 0
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
