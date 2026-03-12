# Tests

## 作用
这个目录放仓库里的自动化测试，以及数据抓取相关脚本和说明文档。

## 说明文档入口

- [Futu 1 分钟抓取说明](README_fetch_futu_1m.md)
- [Polygon 1 分钟抓取说明](README_fetch_polygon_1m.md)
- [ValueSider 持仓抓取说明](README_valuesider_holdings.md)

## 文件清单
- `test_backtest_scripts.py`
  - 校验 RSI 在单边上涨、单边下跌、横盘时的边界输出
  - 校验 `fetch_futu_1m.py` 默认会清理请求区间之外的旧 CSV
- `fetch_futu_1m.py`
  - 通过 Futu OpenD 抓取 1 分钟历史数据
- `fetch_polygon_1m.py`
  - 通过 Polygon API 抓取 1 分钟历史数据
- `minute_csv_utils.py`
  - 保存和清理按交易日拆分 CSV 的共用逻辑
- [README_fetch_futu_1m.md](README_fetch_futu_1m.md)
  - `fetch_futu_1m.py` 的使用说明
- [README_fetch_polygon_1m.md](README_fetch_polygon_1m.md)
  - `fetch_polygon_1m.py` 的使用说明
- [README_valuesider_holdings.md](README_valuesider_holdings.md)
  - ValueSider 持仓抓取的使用说明
- `backtest_three_minute_momentum.py`
  - 最早的三分钟连涨买入 / 连跌卖出实验
- `search_better_strategy.py`
  - 用来批量搜索简单策略和参数组合的研究脚本
  - 支持单标的（`--data-dir`）和股票池（`--codes`）两种模式
  - 当前会一起扫描以下策略族：
    - EMA 金叉死叉
    - RSI 反转
    - 通道突破
    - Bollinger Bands 均值回归（bollinger_band_reversion）
    - MACD 信号线交叉（macd_signal_crossover）  

## 推荐运行方式

在仓库根目录运行全部测试：

```bash
./.venv/bin/python -m unittest discover -s tests
```

只跑这一份测试文件：

```bash
./.venv/bin/python -m unittest tests.test_backtest_scripts
```

也可以直接执行：

```bash
./.venv/bin/python tests/test_backtest_scripts.py
```

## 导入说明

`test_backtest_scripts.py` 会先根据自身文件位置计算仓库根目录并加入 `sys.path`，所以里面这几个导入是有效的：

- `from scripts.backtest_rsi_reversion import compute_rsi`
- `from tests.minute_csv_utils import remove_stale_daily_files, save_daily_files`

这意味着只要测试文件还在当前仓库的 `tests/` 目录下，上面的三种运行方式都可以正确导入目标模块，不依赖你当前 shell 的工作目录碰巧是什么。
