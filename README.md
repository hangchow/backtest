# 实盘信号框架说明

这个仓库提供一个“只出信号、不真实下单”的实时交易框架，当前只支持“股票池 + 单一组合策略”的模式。当前行情和交易实现都基于 `Futu OpenD`，并保留了未来切到其他行情源或券商 API 的架构分层。

如果你要看回测相关文档，入口在 [backtest/README.md](backtest/README.md)。

## 架构

- `live_trading/config.py`
  - 负责读取两类 JSON 配置：
  - 行情订阅配置：`realtime_broker + history_broker + runtime + stock_pool`
  - 实盘交易配置：`trade_accounts[]`
- `live_trading/pool_strategies.py`
  - 实现组合级策略适配，当前支持 `dual_momentum`。
- `live_trading/broker.py`
  - 定义 `QuoteBrokerClient`、`DailyHistoryProvider` 和 `TradeAccountClient` 抽象。
  - 当前实现只有 `futu`：
  - `realtime_broker`
  - 通过 OpenD 订阅 `QUOTE` 和 `K_1M`。
  - `history_broker`
  - 通过 OpenD 拉取日 K 预热策略。
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
- 当前 `realtime_broker` 和 `history_broker` 都只支持 `futu`，但可以配置成不同的 OpenD 地址。
- `dual_momentum` 用日线维度计算，在收到“新交易日第一根分钟 bar”时，使用上一交易日的已完成日线数据生成调仓信号。
- 资金、持仓目前先用“定时查询 + 差异日志”实现成统一事件流；后续切到其他券商时可替换成原生 push。
- 每个交易账户都会维护自己独立的 `shadow_positions` / `shadow_cash`，用于 dry-run 模式下避免重复买入卖出逻辑失真。
- 不支持单标策略配置；行情配置文件必须定义 `stock_pool`。

## 配置文件

使用两个 JSON 文件：

- `config/live_trading.quote.sample.json`
  - 行情订阅配置样例。
- `config/live_trading.trade_accounts.sample.json`
  - 交易账户配置样例。

关键字段：

- 行情订阅配置
  - `realtime_broker.type`
  - 当前只支持 `futu`。
  - `realtime_broker.host` / `realtime_broker.port`
  - 分钟级行情订阅使用的 OpenD 地址。
  - `realtime_broker.extended_time`
  - 是否订阅扩展时段分钟行情。
  - `history_broker.type`
  - 当前只支持 `futu`。
  - `history_broker.host` / `history_broker.port`
  - 历史日线读取使用的 OpenD 地址。
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
./.venv/bin/python run_live_trading.py \
  --quote-config config/live_trading.quote.sample.json \
  --trade-config config/live_trading.trade_accounts.sample.json
```

## 日志输出

触发调仓信号时不会调用真实 `place_order`，只会输出类似：

```text
DRY_RUN_REBALANCE account_id=sim_primary signal_time=... target_weights=...
DRY_RUN_ORDER account_id=sim_primary action=BUY ... command=place_order(price=..., qty=..., code='US.MSFT', ...)
```

这样后续要接真实下单时，可以把 dry-run 执行器替换成真实订单路由。
