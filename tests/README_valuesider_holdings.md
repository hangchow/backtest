# ValueSider 持仓抓取与汇总

> 说明：该工具用于辅助数据收集，不是本项目（量化与回测）的主流程脚本。

脚本：`tests/fetch_valuesider_holdings.py`

## 用途

1. 访问 `https://valuesider.com/value-investors` 获取投资人组合页链接；
2. 抓取每个投资人 `portfolio` 页面中的持仓表；
3. 导出每位投资人明细 CSV；
4. 清洗 `ticker/stock` 字段，并生成可交易 ticker 的汇总结果；
5. 统计每个 ticker 被多少位投资人持有；
6. 输出需要人工复核的数据质量问题清单。

## 使用示例

```bash
./.venv/bin/python tests/fetch_valuesider_holdings.py --output-dir output/valuesider
```

说明：

- 脚本会默认把最终统计结果同步到 `stock_select/valuesider`
- 如果只想写入 `output/` 而不同步到仓库目录，可加 `--no-publish`

- 如果网络不可用、只想基于已有缓存重算并发布，可使用：

```bash
./.venv/bin/python tests/fetch_valuesider_holdings.py   --publish-from-cache stock_select/valuesider/all_holdings.csv   --output-dir output/valuesider
```

该模式不会访问 ValueSider 网站，只会读取缓存 `all_holdings.csv` 并重建/发布汇总文件。

## 输出文件

- `output/valuesider/investors/<investor_slug>.csv`：单个投资人持仓明细
- `output/valuesider/all_holdings.csv`：全部投资人持仓明细
- `output/valuesider/summary_by_ticker.csv`：按有效 `ticker` 汇总并按 `value` 降序
- `output/valuesider/holder_count_by_ticker.csv`：按有效 `ticker` 统计持有人数并按人数降序
- `output/valuesider/data_quality_issues.csv`：空 ticker、非正值、代码型 ticker 等需人工复核的记录
- `output/valuesider/errors.csv`：抓取失败页面（如有）
- `stock_select/valuesider/*.csv`：默认同步主统计结果，便于提交到代码库

说明：

- `data_quality_issues.csv` 和 `errors.csv` 只保留在 `output/`，不会发布到 `stock_select/valuesider`
