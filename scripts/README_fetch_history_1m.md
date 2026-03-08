# `fetch_history_1m.py` 使用说明

## 功能

通过本机运行的 Futu OpenD 拉取指定股票、指定时间范围内的 1 分钟 K 线历史数据，并按交易日拆分为单独的 CSV 文件。

## 前提条件

1. 本机已经启动 Futu OpenD。
2. OpenD 监听地址可用，默认是 `127.0.0.1:11111`。
3. Python 环境已安装依赖：

```bash
./.venv/bin/pip install futu-api pandas
```

## 脚本位置

脚本文件：

`scripts/fetch_history_1m.py`

## 参数

```bash
./.venv/bin/python scripts/fetch_history_1m.py \
  --code <股票代码> \
  --start <开始日期> \
  --end <结束日期>
```

可选参数：

- `--host`：OpenD 地址，默认 `127.0.0.1`
- `--port`：OpenD 端口，默认 `11111`
- `--output-dir`：输出目录根目录，默认 `data`
- `--keep-existing`：保留请求区间之外的旧 CSV；默认不保留

必填参数：

- `--code`：股票代码，例如 `HK.00700`
- `--start`：开始日期，格式 `YYYY-MM-DD`
- `--end`：结束日期，格式 `YYYY-MM-DD`

说明：

- `start` 不能晚于 `end`
- 脚本请求的是 Futu 的 `K_1M` 历史 K 线
- 默认会把输出目录里不在这次请求范围内的旧日文件删掉，避免后续回测混入陈旧数据
- 如果你想把多次抓取累积到同一个目录，再显式加 `--keep-existing`

## 使用示例

抓取腾讯控股从 `2025-03-07` 到 `2026-03-07` 的 1 分钟 K 线：

```bash
./.venv/bin/python scripts/fetch_history_1m.py \
  --code HK.00700 \
  --start 2025-03-07 \
  --end 2026-03-07
```

如果 OpenD 不在默认端口：

```bash
./.venv/bin/python scripts/fetch_history_1m.py \
  --host 127.0.0.1 \
  --port 11111 \
  --code HK.00700 \
  --start 2025-03-07 \
  --end 2026-03-07
```

## 输出结果

默认输出到：

```text
data/<股票代码>/
```

例如：

```text
data/HK.00700/
```

文件名格式：

```text
<股票代码>_YYYY-MM-DD.csv
```

例如：

```text
HK.00700_2025-03-07.csv
HK.00700_2025-03-10.csv
HK.00700_2025-03-11.csv
```

## CSV 字段

每个 CSV 文件包含以下列：

- `time_key`：K 线时间，对应这一分钟的时间戳
- `open`：开盘价，对应这一分钟的开盘价
- `close`：收盘价，对应这一分钟的收盘价
- `high`：最高价，对应这一分钟内的最高成交价
- `low`：最低价，对应这一分钟内的最低成交价
- `volume`：成交量，对应这一分钟内的成交股数

说明：

- `code` 和 `name` 没有写入文件，因为在单个股票目录下它们是重复信息
- 一个文件对应一个交易日

## 运行完成后的输出

脚本执行成功后会打印：

- 实际拉取的总行数
- 写出的日文件数量
- 清理掉的旧日文件数量，或者提示已保留旧文件
- 当前写入的字段列表

## 常见问题

### 1. 连不上 OpenD

检查：

- OpenD 是否已经启动
- 端口是否正确
- OpenD 是否允许当前机器连接

### 2. 提示日期非法

确认日期格式是 `YYYY-MM-DD`，并且开始日期不晚于结束日期。

### 3. 历史数据请求失败

常见原因：

- OpenD 登录状态失效
- 行情权限不足
- 请求时间范围过大或频率受限

## 备注

脚本内部会自动处理 Futu SDK 的日志目录问题，尽量避免因为默认日志目录不可写而失败。
