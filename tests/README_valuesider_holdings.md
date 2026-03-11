# ValueSider 持仓抓取与汇总

> 说明：该工具用于辅助数据收集，不是本项目（量化与回测）的主流程脚本。

脚本：`tests/fetch_valuesider_holdings.py`

## 用途

1. 访问 `https://valuesider.com/value-investors` 获取投资人组合页链接；
2. 抓取每个投资人 `portfolio` 页面中的持仓表；
3. 导出每位投资人明细 CSV；
4. 汇总所有持仓并按 `value` 总和降序输出。

## 使用示例

```bash
./.venv/bin/python tests/fetch_valuesider_holdings.py --output-dir output/valuesider
```

## 输出文件

- `output/valuesider/investors/<investor_slug>.csv`：单个投资人持仓明细
- `output/valuesider/all_holdings.csv`：全部投资人持仓明细
- `output/valuesider/summary_by_ticker.csv`：按 `ticker + stock` 汇总并按 `value` 降序
- `output/valuesider/errors.csv`：抓取失败页面（如有）
