# livetrading 配置参考

这份文档是 `livetrading` 的完整配置手册，目标是回答两类问题：

- 4 份 JSON 各自负责什么，能不能内联，顶层 key 有哪些别名
- 每个字段的含义、默认值、合法取值，以及跨字段组合约束

当前配置构建入口在 [livetrading/config.py](../livetrading/config.py)。
代码里的校验逻辑以该文件为准；本文是对当前实现的人工整理。

## 1. 总览

运行 `livetrading.py` 或 `python -m livetrading` 时，推荐拆成 4 份 JSON：

- quote 配置
  - 实时行情入口和运行时日志配置
  - 典型样例：[config/livetrading.quote.futu.sample.json](../config/livetrading.quote.futu.sample.json)、[config/livetrading.quote.mock.sample.json](../config/livetrading.quote.mock.sample.json)
- history 配置
  - warm-up 日线来源
  - 典型样例：[config/livetrading.history.futu.sample.json](../config/livetrading.history.futu.sample.json)、[config/livetrading.history.polygon.sample.json](../config/livetrading.history.polygon.sample.json)、[config/livetrading.history.local.sample.json](../config/livetrading.history.local.sample.json)
- pool 配置
  - 股票池代码和 live 策略参数
  - 典型样例：[config/livetrading.pool.sample.json](../config/livetrading.pool.sample.json)
- trade account 配置
  - 单个账户的 broker 连接方式和执行器参数
  - 典型样例：[config/livetrading.trade_account.mock.sample.json](../config/livetrading.trade_account.mock.sample.json)、[config/livetrading.trade_account.simulate.sample.json](../config/livetrading.trade_account.simulate.sample.json)、[config/livetrading.trade_account.futu.sample.json](../config/livetrading.trade_account.futu.sample.json)

最终 4 份配置会合并成 `LiveTradingConfig`。合并规则：

- `quote` 必填
- `trade_account` 必填
- `history` 可以单独传 `--history-config`，也可以内联在 quote 配置里
- `pool` 可以单独传 `--pool-config`，也可以内联在 quote 配置里
- `quote` 和单独的 `history` / `pool` 不能重复定义同一段配置

## 2. 通用规则

### 2.1 当前固定美股口径

`livetrading` 当前固定按美股口径运行，不再从配置里暴露 `market`。

### 2.2 配置文件是 JSON object

4 份配置文件都必须是顶层 JSON object，不能是数组或裸值。

### 2.3 单进程单账户

`livetrading` 当前按“一个进程实例只服务一个交易账户”设计。  
因此交易配置顶层直接使用 `trade_account` 单对象，不再接受数组形状。

### 2.4 热更新

运行中会周期性重新读取这 4 份文件。只要文件内容摘要变化，就会触发重新解析和重新应用配置。

### 2.5 顶层别名

为了兼容旧格式，当前解析器接受一些 wrapper / alias：

- quote 配置
  - 可用 `realtime_broker`
  - 也可用 `quote_broker` 或 `broker` 作为别名
  - 如果只给 `quote_broker` / `broker`，且没有单独给 `history_broker`，同一段配置会同时被当作 realtime 和 history broker
- history 配置
  - 可用 `history_broker`
  - 也可用 `broker`
  - 也支持直接把 `type` / `host` / `port` / `data_root` 写在顶层
- pool 配置
  - 可用 `stock_pool`
  - 也可用 `pool`
  - 也支持直接把 `codes` / `strategy` 写在顶层
- trade account 配置
  - 顶层固定使用 `trade_account`

同一份文件里不能同时混用两种等价写法。比如：

- quote 配置不能同时写 `realtime_broker` 和 `broker`
- history 配置不能同时写 `history_broker` 和顶层 `type/host/...`
- pool 配置不能同时写 `stock_pool` 和顶层 `codes/strategy`

## 3. quote 配置

最常见的结构：

```json
{
  "realtime_broker": {
    "type": "futu",
    "host": "127.0.0.1",
    "port": 11111
  }
}
```

### 3.1 `realtime_broker`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `type` | `string` | `futu` | 支持 `futu`、`mock` |
| `host` | `string` | 无 | 必填；`futu` 时是 OpenD 地址，`mock` 时是本地 HTTP push 监听地址 |
| `port` | `int` | 无 | 必填；必须为正整数 |

补充：`futu` 实时行情不再通过配置开关控制 `extended_time`。
当前实际订阅范围会从唯一交易账户的 `execution.order_session` 派生：

- `order_session=RTH`
  - 只订阅常规时段 bar
- `order_session=ETH` / `ALL`
  - 订阅扩展时段 bar

### 3.2 `runtime`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `config_reload_interval_seconds` | `float` | `10.0` | 配置轮询间隔，必须大于 0 |
| `log_level` | `string` | `INFO` | 支持 `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` |
| `log_price_updates` | `bool` | `true` | 是否打印 `QUOTE` 级别日志 |
| `log_account_updates` | `bool` | `true` | 是否打印 `ACCOUNT` 级别日志 |
| `log_position_updates` | `bool` | `true` | 是否打印 `POSITIONS` 级别日志 |

### 3.3 可选内联段

quote 配置里还允许内联：

- `history_broker`
- `stock_pool`

如果你已经通过 `--history-config` / `--pool-config` 单独传入，就不要再在 quote 里重复定义。

## 4. history 配置

最常见的结构：

```json
{
  "history_broker": {
    "type": "polygon"
  }
}
```

### 4.1 通用字段

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `type` | `string` | `futu` | 支持 `polygon`、`futu`、`local` |
| `data_root` | `string` | `.kline_day` | 本地日线目录；`local` 直接读取这里，`futu` / `polygon` 把这里当 warm-up 缓存目录 |

### 4.2 `type=futu`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `host` | `string` | 无 | 必填；Futu OpenD 地址 |
| `port` | `int` | 无 | 必填；必须为正整数 |

兼容别名：

- `history_host`
- `history_port`
- `data_root` 可选；默认 `.kline_day`，用于本地 warm-up 缓存目录

### 4.3 `type=polygon`

`polygon` 模式下，代码不会强制要求 `host` / `port`。样例里通常只写：

```json
{
  "history_broker": {
    "type": "polygon"
  }
}
```

说明：

- `host` / `port` 可以省略
- 真实的 Polygon 认证通常来自运行环境，而不是这份 JSON
- `data_root` 可选；默认 `.kline_day`，用于本地 warm-up 缓存目录

### 4.4 `type=local`

`local` 模式下会直接从 `data_root` 读取本地日线，默认 `.kline_day`。

兼容别名：

- `kline_day_root`

## 5. pool 配置

最常见的结构：

```json
{
  "stock_pool": {
    "codes": ["US.AAPL", "US.MSFT"],
    "strategy": {
      "name": "dual_momentum",
      "params": {}
    }
  }
}
```

### 5.1 `stock_pool.codes`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `codes` | `string[]` | 无 | 必填，非空数组，不能重复，代码必须是 `US.*` |

### 5.2 `stock_pool.strategy`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `name` | `string` | 无 | 必填；当前内建支持 `dual_momentum` |
| `params` | `object` | `{}` | 传给 live pool strategy 的参数字典 |

### 5.3 `dual_momentum` 参数

当前 live 侧会把 `stock_pool.strategy.params` 同时喂给：

- [strategy/dual_momentum.py](../strategy/dual_momentum.py) 的 `DualMomentumParams`
- [strategy/rebalance.py](../strategy/rebalance.py) 的 `RebalancePolicy`

也就是说，这里既包含信号参数，也包含调仓带参数。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `lookback_days` | `int` | `90` | 短周期动量窗口，必须 `> 0` |
| `long_lookback_days` | `int` | `180` | 长周期动量窗口，必须 `> 0` |
| `long_lookback_weight` | `float` | `0.25` | 长周期动量权重，必须在 `[0, 1]` |
| `top_n` | `int` | `1` | 最多持有的目标股票数，必须 `> 0` |
| `volume_window` | `int` | `20` | 成交量相对窗口，必须 `> 0` |
| `min_volume_ratio` | `float` | `1.3` | 放量加分门槛，必须 `> 0` |
| `market_filter_window` | `int` | `120` | 市场风险过滤窗口，必须 `> 0` |
| `volatility_window` | `int` | `20` | 波动率估算窗口，必须 `> 1` |
| `target_annual_vol` | `float` | `0.30` | 目标年化波动率，必须 `> 0` |
| `max_gross_exposure` | `float` | `1.0` | 最大总暴露，必须 `>= 1` |
| `rebalance_band_pct` | `float` | `0.1` | 调仓带，必须在 `[0, 1]` |

补充：

- warm-up 所需日线根数会根据这些窗口自动计算，不需要你手动再配一个 `warmup_bars`
- 如果 `params` 里出现未使用字段，当前解析层不会报错，但策略实现也不会消费它

## 6. trade account 配置

最常见的结构：

```json
{
  "trade_account": {
    "account_id": "sim_primary",
    "broker": {
      "type": "futu",
      "host": "127.0.0.1",
      "port": 11111,
      "trade_env": "SIMULATE"
    },
    "execution": {
      "executor": "futu_simulate",
      "order_session": "RTH"
    }
  }
}
```

### 6.1 `trade_account`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `trade_account` | `object` | 无 | 必填；表示当前进程服务的唯一账户 |
| `trade_account.account_id` | `string` | 无 | 必填；当前单进程只会使用这 1 个账户 |

### 6.2 `trade_account.broker`

#### 通用字段

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `type` | `string` | `futu` | 支持 `futu`、`mock` |
| `fee_account` | `string \| null` | `futu_alt` | 手续费口径 |
| `account_poll_interval_seconds` | `float` | `15.0` | 账户资金轮询周期，必须 `> 0` |
| `position_poll_interval_seconds` | `float` | `15.0` | 持仓轮询周期，必须 `> 0` |

#### `type=futu`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `host` | `string` | 无 | 必填；账户 OpenD 地址 |
| `port` | `int` | 无 | 必填；必须为正整数 |
| `trade_env` | `string` | `SIMULATE` | 支持 `SIMULATE`、`REAL` |
| `account_index` | `int` | `0` | Futu 账户索引，必须 `>= 0` |

#### `type=mock`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `host` | `string` | `mock` | 占位字段，不参与真实连接 |
| `port` | `int` | `1` | 占位字段，必须 `>= 0` |
| `initial_cash` | `float` | `100000.0` | mock 账户初始现金，必须 `> 0` |
| `initial_positions` | `object` | `{}` | mock 账户初始持仓；key 必须是 `US.*`，qty 必须是 `>= 0` 的整数 |

补充：

- `mock` broker 不连 Futu，`trade_env` 在这里没有语义
- `initial_positions` 例子：

```json
{
  "US.AAPL": 100,
  "US.MSFT": 50
}
```

### 6.3 `trade_account.execution`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `executor` | `string` | `mock` | 支持 `mock`、`futu_simulate`、`futu_real` |
| `order_session` | `string` | 条件默认 | 支持 `RTH`、`ETH`、`ALL` |

`order_session` 的默认值有条件：

- `executor=futu_real` 且 `broker.trade_env=REAL` 时，默认 `ETH`
- 其他情况默认 `RTH`

补充：

- 如果你只想走常规时段，可以显式写 `order_session=RTH`

`order_session` 取值的中文含义：

- `RTH`
  - `Regular Trading Hours`
  - 常规交易时段
- `ETH`
  - `Extended Trading Hours`
  - 常规交易时段 + 盘前盘后
  - 不包含夜盘
- `ALL`
  - `All Sessions`
  - 所有可用时段
  - 可理解为常规时段 + 盘前盘后 + 其他 Futu 可用扩展时段

### 6.4 执行组合约束

这是最容易踩坑的部分。

#### `executor=mock`

- 可配 `broker.type=mock`
- 也可配 `broker.type=futu`
- 不会真的调 Futu `place_order(...)`
- 可配 `order_session=RTH` / `ETH` / `ALL`
- 非 `RTH` 时，主要影响 realtime quote 的准入时段和 mock `/push` 的 bar 过滤，不会产生真实券商下单语义

#### `executor=futu_simulate`

- 必须配 `broker.type=futu`
- 必须配 `broker.trade_env=SIMULATE`

#### `executor=futu_real`

- 必须配 `broker.type=futu`
- 必须配 `broker.trade_env=REAL`

#### `broker.type=mock`

- 只能配 `executor=mock`

#### extended-hours 交易

如果要支持美股盘前盘后交易，只需要在下单侧把 `trade_account.execution.order_session` 设成非 `RTH`。

当前限制：

- `executor=futu_simulate` / `executor=futu_real` 且 `order_session != RTH` 时，仍要求 `broker.type=futu`

补充：

- realtime quote 侧的 `subscribe_extended_time` 会从唯一账户的 `order_session` 派生
- `mock` quote broker 现在也会按这份派生结果过滤 `/push` 进来的分钟 bar，尽量对齐真实行情订阅的准入行为
- `executor=mock` 时，`ETH` / `ALL` 都会让 mock quote 入口接受扩展时段 bar；当前 quote 层只区分“RTH”与“非 RTH”，不会再细分 `ETH` 和 `ALL`

常见组合：

- 只做常规时段
  - `order_session=RTH`
- mock 联调盘前触发
  - `executor=mock`
  - `order_session=ETH`
- 美股实盘默认组合
  - `order_session=ETH`

## 7. 跨文件一致性约束

4 份配置合并时，还会做这些一致性校验：

- `history` 不能同时来自 quote 内联和 `--history-config`
- `pool` 不能同时来自 quote 内联和 `--pool-config`
- 最终必须能拿到一份 `history_broker`
- 最终必须能拿到一份 `stock_pool`

## 8. 推荐组合

### 8.1 全本地联调

- [config/livetrading.quote.mock.sample.json](../config/livetrading.quote.mock.sample.json)
- [config/livetrading.history.local.sample.json](../config/livetrading.history.local.sample.json)
- [config/livetrading.pool.sample.json](../config/livetrading.pool.sample.json)
- [config/livetrading.trade_account.mock.sample.json](../config/livetrading.trade_account.mock.sample.json)

### 8.2 Futu 行情 + Polygon warm-up + Futu 模拟下单

- [config/livetrading.quote.futu.sample.json](../config/livetrading.quote.futu.sample.json)
- [config/livetrading.history.polygon.sample.json](../config/livetrading.history.polygon.sample.json)
- [config/livetrading.pool.sample.json](../config/livetrading.pool.sample.json)
- [config/livetrading.trade_account.simulate.sample.json](../config/livetrading.trade_account.simulate.sample.json)

### 8.3 Futu 行情 + Futu warm-up + Futu 真实环境下单

- [config/livetrading.quote.futu.sample.json](../config/livetrading.quote.futu.sample.json)
- [config/livetrading.history.futu.sample.json](../config/livetrading.history.futu.sample.json)
- [config/livetrading.pool.sample.json](../config/livetrading.pool.sample.json)
- [config/livetrading.trade_account.futu.sample.json](../config/livetrading.trade_account.futu.sample.json)

## 9. 相关文档

- 快速启动和样例命令： [README.md](../README.md)
- 执行器和提单链路： [README_livetrading_real_order_plan.md](../docs/README_livetrading_real_order_plan.md)
- 实时链路时序图： [README_livetrading_sequence.md](../docs/README_livetrading_sequence.md)
- mock 推送格式和复现实验： [README_livetrading_mock_signal.md](../docs/README_livetrading_mock_signal.md)
