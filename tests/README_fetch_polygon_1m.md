# `fetch_polygon_1m.py` 使用说明

## 功能

通过 Polygon Stocks API 拉取指定股票、指定时间范围内的 1 分钟历史数据，并转换成仓库当前使用的按交易日拆分 CSV 格式。

## 前提条件

1. 你已经有可用的 Polygon API key。
2. Python 环境已安装依赖：

```bash
./.venv/bin/pip install -r requirements.txt
```

如果只想安装这个脚本的最小依赖，也可以单独安装：

```bash
./.venv/bin/pip install pandas
```

3. 推荐通过环境变量提供 API key：

```bash
export POLYGON_API_KEY=your_api_key
```

## 脚本位置

脚本文件：

`tests/fetch_polygon_1m.py`

## 参数

```bash
./.venv/bin/python tests/fetch_polygon_1m.py \
  --symbol <美股代码> \
  --start <开始日期> \
  --end <结束日期>
```

必填参数：

- `--symbol`：Polygon 股票代码，例如 `MSFT`
- `--start`：开始日期，格式 `YYYY-MM-DD`
- `--end`：结束日期，格式 `YYYY-MM-DD`

可选参数：

- `--code`：输出目录和文件名前缀；默认等于 `symbol`
- `--api-key`：直接传入 Polygon API key；默认读取 `POLYGON_API_KEY`
- `--output-dir`：输出根目录，默认 `kline_minute`
- `--adjusted`：请求复权后的分钟数据；默认请求原始成交价
- `--include-extended-hours`：保留盘前和盘后数据；默认只保留美东 `09:30-16:00`，包含 `16:00:00`
- `--keep-existing`：保留请求区间之外的旧 CSV；默认不保留
- `--rate-limit-seconds`：每次月度请求之间的等待秒数，默认 `13.0`
- `--insecure`：禁用 TLS 证书校验，仅在本机 CA 环境异常时使用

说明：

- `start` 不能晚于 `end`
- 脚本会按月份拆请求，再合并、去重并转成仓库本地 CSV 格式
- 默认会过滤掉美股盘前和盘后分钟线，但会保留 `16:00:00` 这根收盘分钟 bar；如果需要完整时段，显式加 `--include-extended-hours`
- 默认会把输出目录里不在这次请求范围内的旧日文件删掉，避免后续回测混入陈旧数据

## 使用示例

抓取 `MSFT` 从 `2025-03-07` 到 `2025-03-31` 的常规交易时段分钟数据：

```bash
./.venv/bin/python tests/fetch_polygon_1m.py \
  --symbol MSFT \
  --code US.MSFT \
  --start 2025-03-07 \
  --end 2025-03-31
```

如果想保留盘前盘后并显式设置 API key：

```bash
./.venv/bin/python tests/fetch_polygon_1m.py \
  --symbol NVDA \
  --code US.NVDA \
  --start 2025-03-07 \
  --end 2025-03-31 \
  --include-extended-hours \
  --api-key your_api_key
```

如果你已经确认自己的套餐允许更快的请求，也可以调整限速：

```bash
./.venv/bin/python tests/fetch_polygon_1m.py \
  --symbol GOOG \
  --code US.GOOG \
  --start 2025-03-07 \
  --end 2025-03-31 \
  --rate-limit-seconds 13
```

## 输出结果

默认输出到：

```text
kline_minute/<输出代码>/
```

例如：

```text
kline_minute/US.MSFT/
```

文件名格式：

```text
<输出代码>_YYYY-MM-DD.csv
```

例如：

```text
US.MSFT_2025-03-07.csv
US.MSFT_2025-03-10.csv
US.MSFT_2025-03-11.csv
```

## CSV 字段

每个 CSV 文件包含以下列：

- `time_key`：美东时间的分钟时间戳
- `open`：开盘价
- `close`：收盘价
- `high`：最高价
- `low`：最低价
- `volume`：成交量

说明：

- 脚本会把 Polygon 原始字段名 `o/c/h/l/v/t` 转成仓库统一字段
- 默认输出只保留仓库当前回测脚本需要的 6 列
- 一个文件对应一个交易日

## 运行完成后的输出

脚本执行成功后会打印：

- 实际拉取的总行数
- 写出的日文件数量
- 清理掉的旧日文件数量，或者提示已保留旧文件
- 当前写入的字段列表

## 常见问题

### 1. 提示缺少 API key

确认你已经：

- 传入 `--api-key`
- 或者设置了 `POLYGON_API_KEY`

### 2. 返回空数据

检查：

- 股票代码是否正确
- 日期范围是否正确
- 当前 Polygon 套餐是否覆盖所请求的数据范围

### 3. 请求过慢或被限流

脚本默认每个月请求之间等待 `13` 秒，以避免超出免费或低配套餐限制。如果你的环境更严格，可以把 `--rate-limit-seconds` 调大。

### 4. HTTPS 证书异常

只有在本机证书链损坏、且你明确知道风险时，才使用 `--insecure`。
