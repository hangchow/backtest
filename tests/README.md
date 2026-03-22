# Tests

## 作用

这个目录放 3 类东西：

- 自动化测试
- 抓取历史数据的脚本
- 少量研究型辅助脚本

## 主要文件

- 自动化测试
  - `test_livetrading.py`
  - `test_backtest_scripts.py`
  - `test_backtest_compare.py`
  - `test_backtest_pool.py`
  - `test_backtest_ema_rsi_bull_range.py`
  - `test_fetch_polygon_1m.py`
- 数据抓取脚本
  - `fetch_futu_1m.py`
  - `fetch_futu_day.py`
  - `fetch_polygon_1m.py`
  - `fetch_polygon_day.py`
- 共用工具
  - `minute_csv_utils.py`
- 研究脚本
  - `search_better_strategy.py`

## 文档入口

- 总入口：[根目录 README](../README.md)
- 回测入口：[backtest/README.md](../backtest/README.md)
- Futu 1 分钟抓取说明：[README_fetch_futu_1m.md](../docs/README_fetch_futu_1m.md)
- Futu 日线抓取说明：[README_fetch_futu_day.md](../docs/README_fetch_futu_day.md)
- Polygon 1 分钟抓取说明：[README_fetch_polygon_1m.md](../docs/README_fetch_polygon_1m.md)
- Polygon 日线抓取说明：[README_fetch_polygon_day.md](../docs/README_fetch_polygon_day.md)
- livetrading mock 联调说明：[README_livetrading_mock_signal.md](../docs/README_livetrading_mock_signal.md)

## 推荐运行方式

跑全部测试：

```bash
./.venv/bin/python -m unittest discover -s tests
```

只跑 livetrading：

```bash
./.venv/bin/python -m unittest tests.test_livetrading
```

只跑 backtest 脚本相关测试：

```bash
./.venv/bin/python -m unittest tests.test_backtest_scripts
```

## 导入说明

推荐先执行 `./.venv/bin/pip install -e .`，然后统一通过 `python -m unittest ...` 运行测试；测试文件本身不再修改 `sys.path`。
