# 项目说明

这个仓库提供一个实时交易框架，当前支持“股票池 + 单一组合策略”的模式。执行层按账户支持 3 种模式：

- `mock`
  - 打印 `DRY_RUN_*` 日志，不提交给 Futu
  - 同时维护本地 `shadow_cash / shadow_positions`
- `futu_simulate`
  - 把订单提交到 Futu 模拟交易环境
- `futu_real`
  - 把订单提交到 Futu 真实交易环境

当前支持两条运行路径：

- 走 `Futu OpenD` 的实时行情 / 交易账户路径
- 完全本地的 `mock` 联调路径

也就是说，行情、日线 warm-up 和账户侧都已经可以按配置拆开，不再强制依赖同一个外部服务。

如果你要看回测相关文档，入口在 [backtest/README.md](backtest/README.md)。

## 环境准备

在仓库根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
source .venv/bin/active
```

## 架构

- `livetrading/config.py`
  - 负责读取四类 JSON 配置：
  - 实时行情配置：`realtime_broker + runtime`
  - 历史 warm-up 配置：`history_broker`
  - 股票池配置：`stock_pool`
  - 交易账户配置：`trade_accounts[]`
- `livetrading/pool_strategies.py`
  - 实现组合级策略适配，当前支持 `dual_momentum`。
- `livetrading/broker.py`
  - 定义 `QuoteBrokerClient`、`DailyHistoryProvider` 和 `TradeAccountClient` 抽象。
  - 当前实现：
  - `realtime_broker`
  - 支持 `futu` 和 `mock`。
  - `futu` 通过 OpenD 订阅 `QUOTE` 和 `K_1M`。
  - `mock` 在本地启动一个 HTTP 推送入口，外部可以在运行中手工推送分钟 K。
- `history_broker`
  - 支持 `polygon`、`futu` 和 `local`。
  - `polygon`
  - 启动 warm-up 顺序：先读 `.kline_day/<code>/*.csv`（实盘缓存日线，按周文件）→ 若缓存缺失或过期，则直接从 Polygon 拉日线写回 `.kline_day/`，再从缓存读取。
  - `futu`
  - 通过 OpenD `get_cur_kline(..., K_DAY)` 直接拉历史日线，`history_broker.host` / `history_broker.port` 会真实生效。
  - `local`
  - 只从 `.kline_day/` 读取本地日线，不访问外部服务。
  - `kline_day/` 与 `kline_minute/` 仅保留给回测和离线研究使用，不参与实盘 warm-up。
- `trade_accounts`
  - 支持 `futu` 和 `mock` 两种账户 client。
  - `futu` 负责查询资金、持仓、订单回报和成交回报。
  - `mock` 直接把配置里的 `initial_cash / initial_positions` 推进 engine，不访问 Futu。
- `livetrading/engine.py`
  - 驱动双配置热更新、组合级调仓信号判定、账户运行态推进，以及按账户选择执行器。
- `livetrading/account_state.py`
  - 统一维护 `actual_*`、`shadow_*`、`expected_*` 和 `pending_orders`。
  - live 提单路径会先乐观推进 `expected_*`，再根据订单/成交回报纠偏。
- `livetrading/execution.py`
  - 提供 `RebalancePlanner`、`MockExecutor`、`FutuSimulateExecutor`、`FutuRealExecutor`。
- `livetrading.py`
  - 兼容保留的根目录 CLI 入口；内部转发到包内 CLI。
- `livetrading/__main__.py`
  - 包入口，支持 `python -m livetrading`。

## 设计要点

- 行情订阅和交易账户完全解耦：
  - 只需要一个开通对应行情权限的账号负责订阅。
  - 交易账户配置文件可以定义一个或多个账户，未来扩成多实盘用户时不用改行情文件。
- 配置现在拆成 4 份 JSON：
  - `realtime_broker`
  - 负责价格变更通知和分钟 K 输入。
  - `history_broker`
  - 负责策略 warm-up 用的历史日线获取。
  - `stock_pool`
  - 负责股票池代码列表和组合策略参数。
  - `trade_accounts`
  - 负责账户同步和执行器选择。
- `realtime_broker` 支持 `futu` 和 `mock`；`history_broker` 支持 `polygon`、`futu` 和 `local`；`trade_accounts[].broker.type` 支持 `futu` 和 `mock`。
- 如果你只想做完全本地的 mock 联调，可以用：
  - `realtime_broker.type=mock`
  - `history_broker.type=local`
  - `trade_accounts[].broker.type=mock`
- 如果当前 OpenD 账号没有开通美股实时订阅，但仍希望 warm-up 走远端日线，可以只把 `realtime_broker` 切到 `mock`，同时保留 `history_broker=polygon` 或 `futu`。
- `dual_momentum` 用日线维度计算，在收到“新交易日第一根分钟 bar”时，使用上一交易日的已完成日线数据生成调仓信号。
- `futu` 账户的资金、持仓目前先用“定时查询 + 差异日志”实现成统一事件流；`mock` 账户则在启动时直接注入本地基线。后续切到其他券商时可替换成原生 push。
- 每个交易账户都会维护自己独立的账户运行态：
  - `shadow_positions` / `shadow_cash`
  - 给 `mock` 执行器使用
  - `expected_positions` / `expected_cash`
  - 给 `futu_simulate` / `futu_real` 执行器使用
  - `pending_orders`
  - 用来衔接提交回报和账户实际同步之间的时间差
- 不支持单标策略配置；运行时必须能拿到 `stock_pool`，可以内联在 quote 配置里，也可以通过 `--pool-config` 单独传入。

## 配置文件

现在运行 `livetrading.py` 时，推荐拆成 4 份 JSON。

等价的模块入口也可用：

```bash
./.venv/bin/python -m livetrading --quote-config ... --trade-config ...
```

下面的示例继续沿用根目录 `livetrading.py` 写法：

- `config/livetrading.quote.futu.sample.json`
  - 实时行情配置样例。
- `config/livetrading.quote.mock.sample.json`
  - 使用 mock 实时行情推送的样例。
- `config/livetrading.history.polygon.sample.json`
  - Polygon warm-up 日线配置样例。
- `config/livetrading.history.futu.sample.json`
  - Futu OpenD warm-up 日线配置样例。
- `config/livetrading.history.local.sample.json`
  - 本地 `.kline_day` warm-up 日线配置样例。
- `config/livetrading.pool.sample.json`
  - 股票池和组合策略样例。
- `config/livetrading.trade_accounts.mock.sample.json`
  - mock 执行账户样例。
  - 适合“mock 行情 + 本地日线 warm-up + mock 账户 + mock 执行”的联调场景。
- `config/livetrading.trade_accounts.futu.sample.json`
  - Futu 真实环境下单样例。
  - 会走 `execution.executor = futu_real`，只适合确认好 OpenD 和真实账户后使用。
- `config/livetrading.trade_accounts.simulate.sample.json`
  - Futu 模拟环境下单样例。
  - 适合“Futu 实时行情订阅 + Futu 模拟交易环境提单”。

关键字段：

- 实时行情配置
  - `realtime_broker.type`
  - 支持 `futu` 和 `mock`。
  - `realtime_broker.host` / `realtime_broker.port`
  - `futu` 模式下是 OpenD 地址。
  - `mock` 模式下是本地 HTTP 推送服务监听地址。
  - `realtime_broker.extended_time`
  - 仅 `futu` 模式生效，决定是否订阅扩展时段分钟行情。
  - `runtime.config_reload_interval_seconds`
  - 多久轮询一次 4 份配置文件的变更。
- 历史 warm-up 配置
  - `history_broker.type`
  - 支持 `polygon`、`futu` 和 `local`。
  - `history_broker.host` / `history_broker.port`
  - 仅 `futu` 模式生效，对应 OpenD 地址。
  - `polygon` / `local` 模式下可以省略。
  - `history_broker.data_root`
  - 仅 `local` 模式生效，表示本地日线目录，默认 `.kline_day`。
- 股票池配置
  - `stock_pool.codes`
  - 股票池代码列表。
  - `stock_pool.strategy`
  - 当前支持 `dual_momentum`。
- 实盘交易配置
  - `trade_accounts[].account_id`
  - 本地账户标识，用于日志和后续多用户隔离。
  - `trade_accounts[].broker.type`
  - 支持 `futu` 和 `mock`。
  - `trade_accounts[].broker.host` / `trade_accounts[].broker.port`
  - 仅 `futu` 模式生效，对应账户自己的 OpenD 地址。
  - `trade_accounts[].broker.trade_env`
  - 仅 `futu` 模式有意义。
  - `SIMULATE` 或 `REAL`。
  - `trade_accounts[].broker.account_index`
  - 仅 `futu` 模式生效，表示 Futu 交易账户索引。
  - `trade_accounts[].broker.initial_cash`
  - 仅 `mock` 模式生效，表示本地账户初始现金。
  - `trade_accounts[].broker.initial_positions`
  - 仅 `mock` 模式生效，表示本地账户初始持仓。
  - `trade_accounts[].execution.executor`
  - 支持：
    - `mock`
    - `futu_simulate`
    - `futu_real`
  - `trade_accounts[].execution.enable_real_trading`
  - 只有 `futu_real` 时才允许设成 `true`
  - `trade_accounts[].execution.allow_extended_hours_trading`
  - 是否允许订单进入美股盘前盘后时段。
  - `trade_accounts[].execution.order_session`
  - 支持 `RTH`、`ETH`、`ALL`、`OVERNIGHT`。
  - 只有 `allow_extended_hours_trading=true` 时才允许用非 `RTH`。
  - `trade_accounts[].execution.max_order_notional`
  - 单笔订单最大名义金额
  - `trade_accounts[].execution.max_order_qty`
  - 单笔订单最大股数

## 运行

下面三组命令继续使用根目录 `livetrading.py` 作为兼容入口；如果你更偏好模块方式，可以把 `livetrading.py` 等价替换成 `-m livetrading`。

Futu行情订阅、Futu历史数据、Futu真实环境下单：

```bash
./.venv/bin/python livetrading.py \
  --quote-config config/livetrading.quote.futu.sample.json \
  --history-config config/livetrading.history.futu.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_accounts.futu.sample.json
```

这条命令会走 Futu `REAL` 环境真实提单，样例里的 `execution.enable_real_trading = true` 也是为此准备的。

如果要支持美股盘前盘后交易，需要同时满足两件事：

- 行情侧把 `realtime_broker.extended_time` 设成 `true`
- 下单侧把 `trade_accounts[].execution.allow_extended_hours_trading` 设成 `true`
  - 常见配置是 `order_session = ETH`

Futu行情订阅、polygon历史数据、Futu模拟环境下单：

```bash
export POLYGON_API_KEY=your_api_key
./.venv/bin/python livetrading.py \
  --quote-config config/livetrading.quote.futu.sample.json \
  --history-config config/livetrading.history.polygon.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_accounts.simulate.sample.json
```

Mock行情订阅、本地历史数据、Mock账户、Mock下单：

```bash
./.venv/bin/python livetrading.py \
  --quote-config config/livetrading.quote.mock.sample.json \
  --history-config config/livetrading.history.local.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_accounts.mock.sample.json
```

这份样例不依赖 `Futu OpenD` 和 `Polygon`。

- 分钟行情来自本地 `mock /push`
- warm-up 日线来自本地 `.kline_day`
- 账户资金和持仓基线来自 `trade_accounts.mock.sample.json` 里的 `initial_cash / initial_positions`
- 如果 `.kline_day` 里没有对应股票的日线，warm-up 会缺数据，策略信号也就不稳定



如果你要看 `mock` 行情入口的推送格式、健康检查，以及怎么稳定复现 `BUY / SELL` 信号，统一看 [docs/README_livetrading_mock_signal.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_mock_signal.md)。

## 日志输出

如果账户执行器是 `mock`，触发调仓信号时会输出：

```text
DRY_RUN_REBALANCE account_id=sim_primary signal_time=... target_weights=...
DRY_RUN_ORDER account_id=sim_primary action=BUY ... command=place_order(price=..., qty=..., code='US.MSFT', ...)
```

如果账户执行器是 `futu_simulate` 或 `futu_real`，会继续输出：

```text
ORDER_PLAN account_id=... executor=futu_simulate ...
ORDER_SUBMITTING account_id=... executor=futu_simulate ...
ORDER_SUBMITTED account_id=... executor=futu_simulate ...
ORDER_UPDATE account_id=... broker_order_id=...
FILL account_id=... broker_order_id=...
```

也就是说，现在不是“只有 dry-run”，而是“每个账户按 `execution.executor` 选择自己的执行路径”。

## 更多文档

- 运行时序： [docs/README_livetrading_sequence.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_sequence.md)
- 执行层说明： [docs/README_livetrading_real_order_plan.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_real_order_plan.md)
- mock 联调说明： [docs/README_livetrading_mock_signal.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_mock_signal.md)
