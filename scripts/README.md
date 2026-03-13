# Scripts

## 作用
这个目录放仓库里的正式回测脚本、公共回测组件，以及各类回测结果说明文档。

## 回测口径
- 原始数据范围：`2024-03-07 09:30:00` 到 `2026-03-06 16:00:00`
- 指标预热窗口：`2024-03-07 09:30:00` 到 `2025-03-06 16:00:00`
- 正式记分窗口：`2025-03-07 09:30:00` 到 `2026-03-06 16:00:00`
- 初始资金：`100000`
- 默认允许隔夜；只有显式传入 `--flat-at-close` 才会日内平仓
- `--max-open-positions` 默认是 `-1`，等同全池可同时持仓
- 港股股票池：`HK.00700`、`HK.09988`、`HK.00005`
- 美股股票池：`US.MSFT`、`US.NVDA`、`US.GOOG`、`US.TSLA`，谷歌这里使用的是 `GOOG`，不是 `GOOGL`
- `dual momentum` 使用同一批分钟数据聚合出的日线收盘价和日成交量

## 文档入口
- [港美股单标回测](README_backtest_single_symbol.md)
- [港股股票池回测](README_backtest_hk_stock_pool.md)
- [美股股票池回测](README_backtest_us_stock_pool.md)
- [RSI 策略说明](README_backtest_rsi_reversion.md)
- [EMA 策略说明](README_backtest_ema_cross.md)
- [EMA + RSI 策略说明](README_backtest_ema_rsi_combo.md)
- [优化版 EMA + RSI 策略说明](README_backtest_ema_rsi_bull_range.md)
- [Dual Momentum 策略说明](README_backtest_dual_momentum.md)

## 文件清单
- `backtest_common.py`
  - 回测公共逻辑，包括数据源参数、CSV 加载、量能过滤、`--eval-start` 预热等
- `compare_backtests.py`
  - 对多只单标跑 4 套默认分钟策略，并输出 Markdown 对比表
- `backtest_rsi_reversion.py`
  - 分钟级 RSI 反转策略，支持单标和股票池两种入口
- `backtest_ema_cross.py`
  - 分钟级 EMA 金叉死叉策略，支持单标和股票池两种入口
- `backtest_ema_rsi_combo.py`
  - 分钟级 EMA 趋势过滤 + RSI 回踩策略
- `backtest_ema_rsi_bull_range.py`
  - `EMA + RSI` 的 bull range 参数变体，复用同一套核心回测引擎
- `backtest_dual_momentum.py`
  - 日频 dual momentum 股票池轮动策略，使用分钟数据聚合出的日线
- [README_backtest_single_symbol.md](README_backtest_single_symbol.md)
  - 单标默认参数对比、最佳结果和单标分析
- [README_backtest_hk_stock_pool.md](README_backtest_hk_stock_pool.md)
  - 港股股票池回测结果、收益榜和分析
- [README_backtest_us_stock_pool.md](README_backtest_us_stock_pool.md)
  - 美股股票池回测结果、收益榜和分析
- [README_backtest_rsi_reversion.md](README_backtest_rsi_reversion.md)
  - RSI 策略的实现说明和基线结果
- [README_backtest_ema_cross.md](README_backtest_ema_cross.md)
  - EMA 策略的实现说明和基线结果
- [README_backtest_ema_rsi_combo.md](README_backtest_ema_rsi_combo.md)
  - EMA + RSI 策略的实现说明和基线结果
- [README_backtest_ema_rsi_bull_range.md](README_backtest_ema_rsi_bull_range.md)
  - 优化版 EMA + RSI 策略的实现说明和基线结果
- [README_backtest_dual_momentum.md](README_backtest_dual_momentum.md)
  - Dual Momentum 股票池策略的实现说明和基线结果
- `__init__.py`
  - 让 `scripts` 目录可作为 Python 包导入

## 推荐运行方式

在仓库根目录直接执行这些脚本：

```bash
./.venv/bin/python scripts/compare_backtests.py \
  --code HK.00700 \
  --code US.MSFT
```

单标策略示例：

```bash
./.venv/bin/python scripts/backtest_rsi_reversion.py \
  --data-dir data/US.MSFT
```

股票池策略示例：

```bash
./.venv/bin/python scripts/backtest_dual_momentum.py \
  --codes US.MSFT US.NVDA US.GOOG US.TSLA
```

## 执行说明

当前更推荐从仓库根目录使用 `./.venv/bin/python scripts/<script>.py ...` 这种方式运行。

原因是这个目录下有些脚本直接 import 同目录模块，也有些脚本兼容相对导入；统一从仓库根按脚本路径执行，最稳定，不需要依赖当前 shell 恰好在 `scripts/` 目录里。
