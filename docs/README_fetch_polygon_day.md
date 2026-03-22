# `fetch_polygon_day.py` 使用说明

## 功能

通过 Polygon API 拉取美股日 K 历史数据，并按仓库当前 `kline_day/` 使用的自然周文件格式写出。

默认目标股票池是仓库当前 8 只美股：

- `AAPL`
- `AMZN`
- `GOOG`
- `MSFT`
- `NVDA`
- `TSLA`
- `V`
- `VOO`

## 前提条件

1. 你有可用的 Polygon API key。
2. Python 环境已安装依赖：

```bash
./.venv/bin/pip install -e .
```

如果只想安装这个脚本的最小依赖，也可以单独安装：

```bash
./.venv/bin/pip install pandas
```

## 脚本位置

脚本文件：

`tests/fetch_polygon_day.py`

## 参数

```bash
./.venv/bin/python tests/fetch_polygon_day.py \
  --start <开始日期> \
  --end <结束日期>
```

可选参数：

- `--symbols`：要抓取的美股 ticker 列表，默认是仓库 8 只美股股票池
- `--api-key`：Polygon API key，默认读取 `POLYGON_API_KEY`
- `--output-dir`：输出目录根目录，默认 `kline_day`
- `--raw`：改成抓取 Polygon 原始未复权日线；默认抓取 split-adjusted 日线
- `--keep-existing`：保留请求区间之外已有的周文件
- `--rate-limit-seconds`：不同 ticker 请求之间的延迟，默认 `13`
- `--insecure`：禁用 TLS 校验，仅用于本机证书链异常时排障

必填参数：

- `--start`：开始日期，格式 `YYYY-MM-DD`
- `--end`：结束日期，格式 `YYYY-MM-DD`

说明：

- `start` 不能晚于 `end`
- 默认写出的目录名是 `US.<ticker>`，例如 `US.MSFT`
- 每个文件按自然周切分，文件名使用该周周一日期
- 默认会清理请求区间之外的旧周文件；如果不想清理，加 `--keep-existing`
- 如果请求的起点早于你当前 Polygon 账号可访问的历史窗口，脚本会按 Polygon 实际返回的最早日期落盘，并在输出里打印 `Actual returned range`

## 使用示例

抓取默认 8 只美股，从 `2024-03-15` 到 `2026-03-13`：

```bash
./.venv/bin/python tests/fetch_polygon_day.py \
  --start 2024-03-15 \
  --end 2026-03-13
```

只抓取 `MSFT` 和 `NVDA`：

```bash
./.venv/bin/python tests/fetch_polygon_day.py \
  --symbols MSFT NVDA \
  --start 2024-03-15 \
  --end 2026-03-13
```

如果你要保留未复权价格：

```bash
./.venv/bin/python tests/fetch_polygon_day.py \
  --symbols MSFT \
  --start 2024-03-15 \
  --end 2026-03-13 \
  --raw
```

## 输出结果

默认输出到：

```text
kline_day/US.<ticker>/
```

例如：

```text
kline_day/US.MSFT/
```

文件名格式：

```text
US.MSFT_YYYY-MM-DD.csv
```

这里的日期是该周周一的日期。例如：

```text
US.MSFT_2024-03-18.csv
US.MSFT_2024-03-25.csv
US.MSFT_2024-04-01.csv
```

## CSV 字段

每个 CSV 文件包含以下列：

- `time_key`：交易日时间戳，格式 `YYYY-MM-DD 00:00:00`
- `open`：日开盘价
- `close`：日收盘价
- `high`：日最高价
- `low`：日最低价
- `volume`：日成交量

## 运行完成后的输出

脚本执行成功后会打印：

- 每个 ticker 实际拉取的总行数
- 写出的周文件数量
- 清理掉的旧周文件数量
- 当前写入的字段列表
