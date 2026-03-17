# 项目说明

这个仓库提供一个“只出信号、不真实下单”的实时交易框架，当前只支持“股票池 + 单一组合策略”的模式。当前行情和交易实现都基于 `Futu OpenD`，并保留了未来切到其他行情源或券商 API 的架构分层。

如果你要看回测相关文档，入口在 [backtest/README.md](backtest/README.md)。

## 环境准备

在仓库根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
source .venv/bin/active
```

## 架构

- `live_trading/config.py`
  - 负责读取两类 JSON 配置：
  - 行情订阅配置：`realtime_broker + history_broker + runtime + stock_pool`
  - 实盘交易配置：`trade_accounts[]`
- `live_trading/pool_strategies.py`
  - 实现组合级策略适配，当前支持 `dual_momentum`。
- `live_trading/broker.py`
  - 定义 `QuoteBrokerClient`、`DailyHistoryProvider` 和 `TradeAccountClient` 抽象。
  - 当前实现：
  - `realtime_broker`
  - 支持 `futu` 和 `mock`。
  - `futu` 通过 OpenD 订阅 `QUOTE` 和 `K_1M`。
  - `mock` 在本地启动一个 HTTP 推送入口，外部可以在运行中手工推送分钟 K。
- `history_broker`
  - 支持 `polygon` 和 `futu`。
  - `polygon`
  - 启动 warm-up 顺序：先读 `.kline_day/<code>/*.csv`（实盘缓存日线，按周文件）→ 若缓存缺失或过期，则直接从 Polygon 拉日线写回 `.kline_day/`，再从缓存读取。
  - `futu`
  - 通过 OpenD `get_cur_kline(..., K_DAY)` 直接拉历史日线，`history_broker.host` / `history_broker.port` 会真实生效。
  - `kline_day/` 与 `kline_minute/` 仅保留给回测和离线研究使用，不参与实盘 warm-up。
  - `trade_accounts`
  - 分别查询资金和持仓，并保留未来接真实下单的接口位置。
- `live_trading/engine.py`
  - 驱动双配置热更新、组合级调仓信号判定、每个账户各自的影子仓位/影子现金维护，以及 dry-run 下单日志输出。
- `run_live_trading.py`
  - CLI 入口。

## 设计要点

- 行情订阅和交易账户完全解耦：
  - 只需要一个开通对应行情权限的账号负责订阅。
  - 交易账户配置文件可以定义一个或多个账户，未来扩成多实盘用户时不用改行情文件。
- 行情配置文件里把“实时分钟级订阅”和“历史日线预热”拆成两个配置项，但仍放在同一个 JSON 文件里：
  - `realtime_broker`
  - 负责价格变更通知和分钟 K 输入。
  - `history_broker`
  - 负责策略 warm-up 用的历史日线获取。
- `realtime_broker` 支持 `futu` 和 `mock`；`history_broker` 支持 `polygon` 和 `futu`。
- 如果当前 OpenD 账号没有开通美股实时订阅，可以把 `realtime_broker` 切到 `mock`；实盘 warm-up 建议把 `history_broker` 设成 `polygon`，走 `.kline_day/` + Polygon 日线缓存。
- `dual_momentum` 用日线维度计算，在收到“新交易日第一根分钟 bar”时，使用上一交易日的已完成日线数据生成调仓信号。
- 资金、持仓目前先用“定时查询 + 差异日志”实现成统一事件流；后续切到其他券商时可替换成原生 push。
- 每个交易账户都会维护自己独立的 `shadow_positions` / `shadow_cash`，用于 dry-run 模式下避免重复买入卖出逻辑失真。
- 不支持单标策略配置；行情配置文件必须定义 `stock_pool`。

## 配置文件

使用两个 JSON 文件：

- `config/live_trading.quote.sample.json`
  - 行情订阅配置样例。
- `config/live_trading.quote.mock.sample.json`
  - 使用 mock 实时行情推送的样例。
- `config/live_trading.trade_accounts.sample.json`
  - 交易账户配置样例。

关键字段：

- 行情订阅配置
  - `realtime_broker.type`
  - 支持 `futu` 和 `mock`。
  - `realtime_broker.host` / `realtime_broker.port`
  - `futu` 模式下是 OpenD 地址。
  - `mock` 模式下是本地 HTTP 推送服务监听地址。
  - `realtime_broker.extended_time`
  - 仅 `futu` 模式生效，决定是否订阅扩展时段分钟行情。
  - `history_broker.type`
  - 支持 `polygon` 和 `futu`。
  - `history_broker.host` / `history_broker.port`
  - 仅 `futu` 模式生效，对应 OpenD 地址。
  - `polygon` 模式下可以省略。
  - `stock_pool.codes`
  - 股票池代码列表。
  - `stock_pool.strategy`
  - 当前支持 `dual_momentum`。
  - `runtime.config_reload_interval_seconds`
  - 多久轮询一次两个配置文件的变更。
- 实盘交易配置
  - `trade_accounts[].account_id`
  - 本地账户标识，用于日志和后续多用户隔离。
  - `trade_accounts[].broker.host` / `trade_accounts[].broker.port`
  - 对应账户自己的 OpenD 地址。
  - `trade_accounts[].broker.trade_env`
  - `SIMULATE` 或 `REAL`。
  - `trade_accounts[].broker.account_index`
  - Futu 交易账户索引。

## 运行

```bash
export POLYGON_API_KEY=your_api_key
./.venv/bin/python run_live_trading.py \
  --quote-config config/live_trading.quote.sample.json \
  --trade-config config/live_trading.trade_accounts.sample.json
```

如果实时行情改走 mock：

```bash
export POLYGON_API_KEY=your_api_key
./.venv/bin/python run_live_trading.py \
  --quote-config config/live_trading.quote.mock.sample.json \
  --trade-config config/live_trading.trade_accounts.sample.json
```

启动后，可以向 mock 行情入口推送分钟 K：

```bash
curl -X POST http://127.0.0.1:19111/push \
  -H 'Content-Type: application/json' \
  -d '{
    "code": "US.AAPL",
    "time_key": "2026-03-16 09:30:00",
    "open": 212.10,
    "close": 212.55,
    "high": 212.80,
    "low": 211.98,
    "volume": 15800
  }'
```

也支持批量推送：

```bash
curl -X POST http://127.0.0.1:19111/push \
  -H 'Content-Type: application/json' \
  -d '{
    "bars": [
      {"code": "US.AAPL", "time_key": "2026-03-16 09:30:00", "close": 212.55, "volume": 15800},
      {"code": "US.MSFT", "time_key": "2026-03-16 09:30:00", "close": 428.40, "volume": 9100}
    ]
  }'
```

`mock` 会先发一条合成 `quote`，再发对应的分钟 `bar`，这样引擎里的参考价和策略输入会一起更新。

## 日志输出

触发调仓信号时不会调用真实 `place_order`，只会输出类似：

```text
DRY_RUN_REBALANCE account_id=sim_primary signal_time=... target_weights=...
DRY_RUN_ORDER account_id=sim_primary action=BUY ... command=place_order(price=..., qty=..., code='US.MSFT', ...)
```

这样后续要接真实下单时，可以把 dry-run 执行器替换成真实订单路由。
