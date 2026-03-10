# Backtest

## 项目概览

这个项目基于多只股票的 1 分钟 K 线数据，做几个简单策略的样本内回测。

## 开发环境

- 建议使用 Python `3.10+`；当前仓库里的 `.venv` 是 Python `3.14.3`。
- 仓库目前没有 `pyproject.toml`，Python 依赖以根目录的 `requirements.txt` 为准。
- 回测和测试依赖 `pandas`；通过 Futu 抓数还需要 `futu-api`。

## 环境准备

在仓库根目录执行：

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```

如果你已经有 `.venv`，也可以直接复用并继续使用 `./.venv/bin/python`、`./.venv/bin/pip` 这类显式路径命令。

## 测试

运行全部测试：

```bash
./.venv/bin/python -m unittest discover -s tests
```

只跑单个测试文件，例如：

```bash
./.venv/bin/python -m unittest tests.test_backtest_scripts
```

更多测试说明见 `tests/README.md`。

## 数据抓取前提

- `tests/fetch_futu_1m.py` 依赖本机已启动的 Futu OpenD，默认连接 `127.0.0.1:11111`。
- `tests/fetch_polygon_1m.py` 需要 Polygon API key，推荐通过环境变量设置：

```bash
export POLYGON_API_KEY=your_api_key
```

- 回测脚本本身只读取本地 `data/` 目录下的 CSV，不依赖外部服务。

当前数据范围：

- 对比标的：`HK.00700`、`HK.09988`、`HK.00005`、`US.MSFT`、`US.NVDA`、`US.GOOG`、`US.TSLA`
- 区间：`2025-03-07 09:30:00` 到 `2026-03-06 16:00:00`
- 数据粒度：`1 分钟`
- 港股样本：每只 `246` 个交易日 CSV
- 美股样本：每只 `251` 个交易日 CSV

## 数据目录

- 数据目录：`data/<股票代码>/`
- 目录示例：`data/HK.00700/`、`data/HK.09988/`、`data/HK.00005/`、`data/US.MSFT/`
- 单文件格式：`<股票代码>_YYYY-MM-DD.csv`
- 字段：`time_key, open, close, high, low, volume`

抓取脚本和说明：

- [Futu 抓取说明](tests/README_fetch_futu_1m.md)
- [Polygon 抓取说明](tests/README_fetch_polygon_1m.md)
- `scripts/compare_backtests.py`：按参数比较多只标的的默认回测结果

## 七标的默认参数对比

下面这组对比结果是 `2026-03-09` 生成的，使用的是当前 4 个回测脚本的默认参数。
谷歌这里使用的是 `GOOG`，不是 `GOOGL`。

### 数据概览

| code | rows | days | start | end |
| --- | --- | --- | --- | --- |
| HK.00700 | 80886 | 246 | 2025-03-07 09:30:00 | 2026-03-06 16:00:00 |
| HK.09988 | 80886 | 246 | 2025-03-07 09:30:00 | 2026-03-06 16:00:00 |
| HK.00005 | 80886 | 246 | 2025-03-07 09:30:00 | 2026-03-06 16:00:00 |
| US.MSFT | 97353 | 251 | 2025-03-07 09:30:00 | 2026-03-06 15:59:00 |
| US.NVDA | 97353 | 251 | 2025-03-07 09:30:00 | 2026-03-06 15:59:00 |
| US.GOOG | 97353 | 251 | 2025-03-07 09:30:00 | 2026-03-06 15:59:00 |
| US.TSLA | 97353 | 251 | 2025-03-07 09:30:00 | 2026-03-06 15:59:00 |

### 回测对比

| code | strategy | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- | --- |
| HK.00700 | RSI reversion | 604046.80 | 504.05 | -10.19 | 3628 |
| HK.00700 | EMA cross | 93218.80 | -6.78 | -9.24 | 786 |
| HK.00700 | EMA + RSI | 476907.80 | 376.91 | -3.70 | 3988 |
| HK.00700 | EMA + RSI bull range | 1648402.70 | 1548.40 | -2.84 | 9560 |
| HK.09988 | RSI reversion | 530574.40 | 430.57 | -8.86 | 3712 |
| HK.09988 | EMA cross | 93140.95 | -6.86 | -12.73 | 722 |
| HK.09988 | EMA + RSI | 393132.45 | 293.13 | -5.02 | 3834 |
| HK.09988 | EMA + RSI bull range | 774807.30 | 674.81 | -7.15 | 8770 |
| HK.00005 | RSI reversion | 398540.57 | 298.54 | -7.91 | 3558 |
| HK.00005 | EMA cross | 97056.80 | -2.94 | -5.95 | 852 |
| HK.00005 | EMA + RSI | 477974.00 | 377.97 | -5.89 | 4896 |
| HK.00005 | EMA + RSI bull range | 2388441.35 | 2288.44 | -4.34 | 11576 |
| US.MSFT | RSI reversion | 116482.41 | 16.48 | -15.84 | 4448 |
| US.MSFT | EMA cross | 99955.15 | -0.04 | -5.43 | 942 |
| US.MSFT | EMA + RSI | 136895.03 | 36.90 | -5.03 | 4594 |
| US.MSFT | EMA + RSI bull range | 123259.76 | 23.26 | -14.13 | 9736 |
| US.NVDA | RSI reversion | 139385.44 | 39.39 | -18.86 | 4532 |
| US.NVDA | EMA cross | 95625.18 | -4.37 | -10.70 | 1028 |
| US.NVDA | EMA + RSI | 114412.63 | 14.41 | -16.97 | 5072 |
| US.NVDA | EMA + RSI bull range | 126605.87 | 26.61 | -16.48 | 10578 |
| US.GOOG | RSI reversion | 117532.53 | 17.53 | -14.30 | 4456 |
| US.GOOG | EMA cross | 109678.82 | 9.68 | -6.43 | 988 |
| US.GOOG | EMA + RSI | 105602.72 | 5.60 | -13.94 | 4894 |
| US.GOOG | EMA + RSI bull range | 115981.03 | 15.98 | -16.65 | 10338 |
| US.TSLA | RSI reversion | 92446.69 | -7.55 | -32.59 | 4395 |
| US.TSLA | EMA cross | 118632.64 | 18.63 | -8.18 | 952 |
| US.TSLA | EMA + RSI | 120114.39 | 20.11 | -10.53 | 4550 |
| US.TSLA | EMA + RSI bull range | 147371.74 | 47.37 | -16.05 | 9982 |

### 每个标的的最佳结果

| code | strategy | final_value | return_pct | max_drawdown_pct |
| --- | --- | --- | --- | --- |
| HK.00005 | EMA + RSI bull range | 2388441.35 | 2288.44 | -4.34 |
| HK.00700 | EMA + RSI bull range | 1648402.70 | 1548.40 | -2.84 |
| HK.09988 | EMA + RSI bull range | 774807.30 | 674.81 | -7.15 |
| US.GOOG | RSI reversion | 117532.53 | 17.53 | -14.30 |
| US.MSFT | EMA + RSI | 136895.03 | 36.90 | -5.03 |
| US.NVDA | RSI reversion | 139385.44 | 39.39 | -18.86 |
| US.TSLA | EMA + RSI bull range | 147371.74 | 47.37 | -16.05 |

## 美股股票池（`--codes`）默认参数回测

以下结果基于同一批美股分钟数据，使用股票池模式统一资金回测：

- 股票池：`US.MSFT`、`US.NVDA`、`US.GOOG`、`US.TSLA`
- 初始资金：`100000`
- `--max-open-positions`：`2`
- 默认允许隔夜（仅在传入 `--flat-at-close` 时日内平仓）

### 股票池回测结果

| strategy | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- |
| RSI reversion | 140824.13 | 40.82 | -20.33 | 13187 |
| EMA cross | 122243.48 | 22.24 | -17.08 | 2446 |
| EMA + RSI | 127005.30 | 27.01 | -12.57 | 16350 |
| EMA + RSI bull range | 144382.78 | 44.38 | -14.89 | 33486 |

## 当前结论

- 在当前这 7 只标的、默认参数的设定下，`EMA + RSI` 和 `EMA + RSI bull range` 都能在所有标的上拿到正向收益。
- 如果只看这批样本内结果，`EMA + RSI bull range` 的平均收益率约 `660.70%`，明显高于原版 `EMA + RSI` 的约 `160.72%`，但交易次数也大幅上升。
- 港股这三只样本里，收益最高的默认策略都已经变成 `EMA + RSI bull range`。
- 美股这四只样本里，`TSLA` 的最佳结果来自 `EMA + RSI bull range`，`MSFT` 仍然是原版 `EMA + RSI` 最好，`NVDA` 和 `GOOG` 仍然是 `RSI 反转` 最好。
- 纯 `EMA 金叉死叉` 在七只标的里都不是收益最高的默认策略，但在 `HK.00005`、`GOOG` 和 `TSLA` 上的回撤控制明显好于纯 RSI。
- `EMA + RSI bull range` 不是逐标的全面占优；它在 `MSFT`、`GOOG` 等美股上的回撤明显更深，所以更像一套样本内更激进的优化版本，而不是已经验证过的通用替代品。

## 已知缺陷

- 目前是样本内回测，只在同一段数据上调参与评估，存在明显过拟合风险。
- 没有做训练集 / 验证集 / 测试集拆分。
- 没有加入手续费、平台费、印花税、滑点。
- 默认按分钟收盘价成交，真实成交未必能拿到这个价格。
- 没有处理港股整手限制，回测里允许按股数买卖。
- 没有处理停牌、除权除息、公司行为等更复杂情况。
- 目前虽然已经扩到 7 只标的，但样本仍然偏少，结论很容易被个股风格主导。

## 风险提示

- 文档里的高收益结果不代表可实盘复制。
- 单个策略页里展示的数字也同样只是样本内回测快照，不是可直接外推的收益预期。
- 交易次数很多，加入真实费用后，收益会显著下降。
- 使用分钟级数据做高频触发时，执行延迟和滑点会非常敏感。
- 样本内最优参数，未来很可能失效。

## 建议的下一步

- 加入港股手续费、交易征费、印花税。
- 增加整手限制和现金不足约束。
- 做样本外测试，而不是只看当前这一年。
- 把交易明细、权益曲线、回撤曲线导出。
- 持续扩大标的范围，降低策略被个股风格主导的风险。

## 目录入口

- [Futu 抓取说明](tests/README_fetch_futu_1m.md)
- [Polygon 抓取说明](tests/README_fetch_polygon_1m.md)
- `scripts/compare_backtests.py`
- [RSI 策略说明](scripts/README_backtest_rsi_reversion.md)
- [EMA 策略说明](scripts/README_backtest_ema_cross.md)
- [EMA + RSI 策略说明](scripts/README_backtest_ema_rsi_combo.md)
- [优化版 EMA + RSI 说明](scripts/README_backtest_ema_rsi_bull_range.md)
- [labs 实验脚本](labs/README.md)
