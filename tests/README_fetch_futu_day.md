# `fetch_futu_day.py` 使用说明

## 功能

通过本机运行的 Futu OpenD 拉取指定股票、指定时间范围内的日 K 历史数据，并按仓库当前 `kline_day/` 使用的周文件格式写出。

## 前提条件

1. 本机已经启动 Futu OpenD。
2. OpenD 监听地址可用，默认是 `127.0.0.1:11111`。
3. Python 环境已安装依赖：

```bash
./.venv/bin/pip install -r requirements.txt
```

如果只想安装这个脚本的最小依赖，也可以单独安装：

```bash
./.venv/bin/pip install futu-api pandas
```

## 脚本位置

脚本文件：

`tests/fetch_futu_day.py`

## 参数

```bash
./.venv/bin/python tests/fetch_futu_day.py \
  --code <股票代码> \
  --start <开始日期> \
  --end <结束日期>
```

可选参数：

- `--host`：OpenD 地址，默认 `127.0.0.1`
- `--port`：OpenD 端口，默认 `11111`
- `--output-dir`：输出目录根目录，默认 `kline_day`

必填参数：

- `--code`：股票代码，例如 `HK.00700`
- `--start`：开始日期，格式 `YYYY-MM-DD`
- `--end`：结束日期，格式 `YYYY-MM-DD`

说明：

- `start` 不能晚于 `end`
- 脚本请求的是 Futu 的 `K_DAY` 历史 K 线
- 输出目录结构与仓库现有美股 `kline_day/<code>/` 保持一致
- 每个文件按自然周切分，文件名使用周一日期

## 使用示例

抓取腾讯控股从 `2024-03-15` 到 `2026-03-16` 的日 K：

```bash
./.venv/bin/python tests/fetch_futu_day.py \
  --code HK.00700 \
  --start 2024-03-15 \
  --end 2026-03-16
```

如果 OpenD 不在默认端口：

```bash
./.venv/bin/python tests/fetch_futu_day.py \
  --host 127.0.0.1 \
  --port 11111 \
  --code HK.00700 \
  --start 2024-03-15 \
  --end 2026-03-16
```

## 输出结果

默认输出到：

```text
kline_day/<股票代码>/
```

例如：

```text
kline_day/HK.00700/
```

文件名格式：

```text
<股票代码>_YYYY-MM-DD.csv
```

这里的日期是该周周一的日期。例如：

```text
HK.00700_2024-03-11.csv
HK.00700_2024-03-18.csv
HK.00700_2024-03-25.csv
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

- 实际拉取的总行数
- 写出的周文件数量
- 当前写入的字段列表
