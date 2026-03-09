# `backtest_ema_rsi_bull_range.py` 使用说明

## 功能

这是一个更激进的 `EMA + RSI` 顺势回撤版本：

- 只有在 `EMA(快线) > EMA(慢线)` 的上升趋势里才允许买入
- 买点不再等经典 `RSI < 30`，而是放在更高的牛市回撤区间
- 默认允许隔夜；如果需要也可以切成日内平仓

## 脚本位置

`scripts/backtest_ema_rsi_bull_range.py`

## 默认参数

这组默认值是按当前 7 只样本做过一轮样本内优化后选出来的平衡版本：

- 初始资金：`100000`
- 快线：`EMA(15)`
- 慢线：`EMA(180)`
- `RSI period`：`4`
- 买入阈值：`46`
- 卖出阈值：`52`
- 买入仓位：`100%`
- 默认允许隔夜；加 `--flat-at-close` 才改成日内平仓

## 选择这组参数的原因

这版不是简单多堆指标，而是沿着更适合强趋势回撤的方向收紧节奏：

- `Fidelity` 的 RSI 说明提到，上升趋势里 RSI 常运行在更高区间，`40-50` 经常像支撑位
- `Fidelity` 的均线说明也强调，强趋势里常见做法是等价格回撤到趋势线附近再跟随
- 我实际试过 `ADX` 和 `ATR` 版增强，但在这批样本上反而拖后腿，所以默认没有保留那套过滤

## 基本用法

```bash
./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py --code HK.00700
```

如果你不想隔夜持仓：

```bash
./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py --code HK.00700 --flat-at-close
```

## 常用参数

- `--code`：股票代码，脚本会从 `data/<code>/` 读取数据
- `--data-root`：配合 `--code` 使用的数据根目录，默认 `data`
- `--data-dir`：直接指定完整数据目录；传了以后会覆盖 `--code`
- `--initial-cash`：初始资金
- `--fast-span`：短周期 EMA
- `--slow-span`：长周期 EMA
- `--rsi-period`：RSI 周期
- `--buy-threshold`：买入阈值
- `--sell-threshold`：卖出阈值
- `--position-ratio`：每次买入使用的现金比例，范围 `(0, 1]`
- `--flat-at-close`：每天最后一分钟强制平仓
- `--show-trades`：打印前后各多少笔交易，设为 `0` 可关闭

## 相对当前默认 `EMA + RSI` 的样本内变化

按当前 7 只样本对比：

- 原版默认 `EMA + RSI`：平均收益率约 `160.72%`，最差标的收益率 `5.60%`
- 这版默认参数：平均收益率约 `660.70%`，最差标的收益率 `15.98%`
- 原版默认最坏回撤约 `-16.97%`
- 这版默认最坏回撤约 `-16.65%`

注意：这仍然是样本内结果，只能说明这组参数更适合当前这批数据，不能说明未来会继续成立。
