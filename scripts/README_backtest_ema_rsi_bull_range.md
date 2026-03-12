# `backtest_ema_rsi_bull_range.py` 使用说明

## 功能

这是一个更激进的 `EMA + RSI` 顺势回撤版本：

- 只有在 `EMA(快线) > EMA(慢线)` 的上升趋势里才允许买入
- 买点不再等经典 `RSI < 30`，而是放在更高的牛市回撤区间
- 买点还要求当前成交量至少接近最近均量，避免太薄的牛市回撤信号
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
- 量能窗口：`20`
- 最低相对成交量：`0.9x` 最近均量
- 默认允许隔夜；加 `--flat-at-close` 才改成日内平仓

## 结果边界

- 文档中的样例数字（如有）都只是样本内结果。
- 回测还没有计入手续费、平台费、印花税、滑点。
- 目前也没有处理港股整手限制，回测允许按股数买卖。

## 选择这组参数的原因

这版不是简单多堆指标，而是沿着更适合强趋势回撤的方向收紧节奏：

- `Fidelity` 的 RSI 说明提到，上升趋势里 RSI 常运行在更高区间，`40-50` 经常像支撑位
- `Fidelity` 的均线说明也强调，强趋势里常见做法是等价格回撤到趋势线附近再跟随
- 我实际试过 `ADX` 和 `ATR` 版增强，但在这批样本上反而拖后腿，所以默认没有保留那套过滤

## 基本用法

```bash
./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py --codes HK.00700
```

如果你不想隔夜持仓：

```bash
./.venv/bin/python scripts/backtest_ema_rsi_bull_range.py --codes HK.00700 --flat-at-close
```

## 常用参数

- `--codes`：股票代码列表（空格分隔），脚本会从 `data/<code>/` 读取数据
- `--data-root`：配合 `--codes` 使用的数据根目录，默认 `data`
- `--data-dir`：直接指定单标的数据目录；不能和 `--codes` 同时使用
- `--initial-cash`：初始资金
- `--fast-span`：短周期 EMA
- `--slow-span`：长周期 EMA
- `--rsi-period`：RSI 周期
- `--buy-threshold`：买入阈值
- `--sell-threshold`：卖出阈值
- `--position-ratio`：每次买入使用的现金比例，范围 `(0, 1]`
- `--max-open-positions`：股票池模式下的最大同时持仓数，默认 `-1`（不限制）
- `--volume-window`：成交量比较窗口，用于计算当前量和近期均量的比值
- `--min-volume-ratio`：买点要求的最小相对成交量
- `--flat-at-close`：每天最后一分钟强制平仓
- `--show-trades`：打印前后各多少笔交易，设为 `0` 可关闭

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
