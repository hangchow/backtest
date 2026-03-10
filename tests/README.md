# Tests

## 作用

这个目录放仓库里的自动化测试。

当前测试文件：

- `test_backtest_scripts.py`
  - 校验 RSI 在单边上涨、单边下跌、横盘时的边界输出
  - 校验 `fetch_futu_1m.py` 默认会清理请求区间之外的旧 CSV

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
- `from scripts.fetch_futu_1m import remove_stale_daily_files, save_daily_files`

这意味着只要测试文件还在当前仓库的 `tests/` 目录下，上面的三种运行方式都可以正确导入目标模块，不依赖你当前 shell 的工作目录碰巧是什么。
