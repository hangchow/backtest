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
- [Dual Momentum 股票池说明](scripts/README_backtest_dual_momentum.md)

## 七标的默认参数对比

下面这组对比结果是 `2026-03-11` 生成的，使用的是当前已经加入 volume 处理后的默认参数。
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
| HK.00700 | RSI reversion | 491405.10 | 391.41 | -10.14 | 3208 |
| HK.00700 | EMA cross | 92739.70 | -7.26 | -10.59 | 786 |
| HK.00700 | EMA + RSI | 250760.00 | 150.76 | -3.13 | 2472 |
| HK.00700 | EMA + RSI bull range | 385851.30 | 285.85 | -3.28 | 4502 |
| HK.09988 | RSI reversion | 485308.30 | 385.31 | -8.11 | 3476 |
| HK.09988 | EMA cross | 92886.45 | -7.11 | -14.64 | 722 |
| HK.09988 | EMA + RSI | 215142.90 | 115.14 | -4.15 | 2286 |
| HK.09988 | EMA + RSI bull range | 251209.50 | 151.21 | -5.07 | 4038 |
| HK.00005 | RSI reversion | 286442.98 | 186.44 | -8.13 | 2792 |
| HK.00005 | EMA cross | 96853.50 | -3.15 | -6.98 | 852 |
| HK.00005 | EMA + RSI | 225399.45 | 125.40 | -6.34 | 2760 |
| HK.00005 | EMA + RSI bull range | 286016.50 | 186.02 | -5.35 | 4400 |
| US.MSFT | RSI reversion | 116975.07 | 16.98 | -15.03 | 4300 |
| US.MSFT | EMA cross | 98772.69 | -1.23 | -6.87 | 942 |
| US.MSFT | EMA + RSI | 135930.17 | 35.93 | -4.80 | 2862 |
| US.MSFT | EMA + RSI bull range | 115964.97 | 15.96 | -11.66 | 4714 |
| US.NVDA | RSI reversion | 137748.57 | 37.75 | -18.61 | 4486 |
| US.NVDA | EMA cross | 94341.33 | -5.66 | -12.48 | 1028 |
| US.NVDA | EMA + RSI | 112572.82 | 12.57 | -15.87 | 3438 |
| US.NVDA | EMA + RSI bull range | 121675.65 | 21.68 | -15.87 | 4964 |
| US.GOOG | RSI reversion | 118282.86 | 18.28 | -14.22 | 4322 |
| US.GOOG | EMA cross | 112003.70 | 12.00 | -7.81 | 988 |
| US.GOOG | EMA + RSI | 114388.78 | 14.39 | -6.13 | 2972 |
| US.GOOG | EMA + RSI bull range | 115707.60 | 15.71 | -11.58 | 5074 |
| US.TSLA | RSI reversion | 91670.84 | -8.33 | -33.11 | 4373 |
| US.TSLA | EMA cross | 122998.53 | 23.00 | -9.67 | 952 |
| US.TSLA | EMA + RSI | 128901.81 | 28.90 | -9.16 | 3176 |
| US.TSLA | EMA + RSI bull range | 127930.61 | 27.93 | -20.02 | 4740 |

### 每个标的的最佳结果

| code | strategy | final_value | return_pct | max_drawdown_pct |
| --- | --- | --- | --- | --- |
| HK.00005 | RSI reversion | 286442.98 | 186.44 | -8.13 |
| HK.00700 | RSI reversion | 491405.10 | 391.41 | -10.14 |
| HK.09988 | RSI reversion | 485308.30 | 385.31 | -8.11 |
| US.GOOG | RSI reversion | 118282.86 | 18.28 | -14.22 |
| US.MSFT | EMA + RSI | 135930.17 | 35.93 | -4.80 |
| US.NVDA | RSI reversion | 137748.57 | 37.75 | -18.61 |
| US.TSLA | EMA + RSI | 128901.81 | 28.90 | -9.16 |

## 美股股票池（`--codes`）默认参数回测

以下结果基于同一批美股分钟数据，使用股票池模式统一资金回测：

- 股票池：`US.MSFT`、`US.NVDA`、`US.GOOG`、`US.TSLA`
- 初始资金：`100000`
- `--max-open-positions`：`2`
- 默认允许隔夜（仅在传入 `--flat-at-close` 时日内平仓）
- `RSI reversion` 量能参数：`avg(5) / 0.6x`
- `EMA cross` 量能参数：`avg(5) / 0.6x`
- `EMA + RSI` 量能参数：`avg(20) / 0.9x`
- `EMA + RSI bull range` 量能参数：`avg(20) / 0.9x`

### 股票池回测结果

| strategy | final_value | return_pct | max_drawdown_pct | trade_count |
| --- | --- | --- | --- | --- |
| RSI reversion | 139534.51 | 39.53 | -19.67 | 12967 |
| EMA cross | 114868.28 | 14.87 | -9.02 | 2722 |
| EMA + RSI | 133187.07 | 33.19 | -8.61 | 11256 |
| EMA + RSI bull range | 142168.32 | 42.17 | -11.32 | 17940 |

### 更强的股票池轮动备选

基于同一批 `US.MSFT`、`US.NVDA`、`US.GOOG`、`US.TSLA` 数据，我新增了一个日频 dual momentum 股票池策略：

- 脚本：`scripts/backtest_dual_momentum.py`
- 默认参数：最近 `40` 个交易日动量，持有最强 `1` 只，只有当日成交量高于 `1.3x avg(20)` 时才给动量额外加分
- 回测结果：`final_value = 202227.59`，`return_pct = 102.23%`，`max_drawdown_pct = -10.03%`，`trade_count = 36`

## 当前结论

- 在当前这 7 只标的、加入 volume 处理后的默认参数下，`RSI reversion` 拿到了 `5/7` 个单票最佳结果，港股这三只样本也都回到了它领先。
- `EMA + RSI` 仍然是更均衡的美股单票方案，在 `US.MSFT` 和 `US.TSLA` 上是当前默认参数里最好的结果，而且回撤普遍浅于 `RSI reversion`。
- 在当前这 4 只美股股票池上，`EMA + RSI` 的样本内结果提升到 `33.19%`，同时最大回撤压到 `-8.61%`；`EMA + RSI bull range` 的收益率是 `42.17%`，虽然略低于旧版文档里的更激进样本内峰值，但回撤更收敛。
- `EMA cross` 的 volume 优化主要改善了风险侧，当前股票池最大回撤约 `-9.02%`，明显小于旧版的 `-17.08%`；但它没有成为收益冠军，所以更像低风险对照组。
- `RSI reversion` 的股票池收益率是 `39.53%`，和旧版 `40.82%` 接近，但最大回撤从 `-20.33%` 收敛到 `-19.67%`，说明这组 volume 过滤更偏风险控制。
- `dual momentum` 里，volume 现在只在明显放量时给动量加分，不再惩罚普通量能；当前样本内结果 `102.23%`，仍然显著强于 4 套分钟级股票池策略。

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
- [Dual Momentum 股票池说明](scripts/README_backtest_dual_momentum.md)
- [tests 目录说明（含实验脚本）](tests/README.md)
- [ValueSider 持仓抓取说明（非主流程）](tests/README_valuesider_holdings.md)
