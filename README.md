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
  - 交易账户配置：`trade_account`
- `livetrading/pool_strategy_registry.py`
  - 维护 live pool strategy 的注册表。
  - 当前内建策略由 `livetrading/pool_strategies.py` 注册，配置校验也从这里读取支持的策略名。
- `livetrading/pool_strategies.py`
  - 定义 `PoolLiveStrategy` 抽象，并提供 `build_pool_strategy()` facade。
  - 当前内建 live 策略 `dual_momentum` 也在这里实现并注册。
- `livetrading/runtime_state.py`
  - 统一承载 engine 运行期共享状态：当前配置、broker/client、价格缓存、warm-up pending 标记等。
- `livetrading/config_applier.py`
  - 负责配置 diff、连接重建、策略 warm-up 和账户侧配置应用。
- `livetrading/event_sinks.py`
  - 把 quote/trade account 外部事件收口到独立 sink，分别处理行情事件和账户事件。
- `livetrading/portfolio.py`
  - 提供 `PortfolioCoordinator`，负责把组合决策拆成账户级计划并交给执行器。
- `livetrading/broker_registry.py`
  - 维护 quote broker / history provider / trade account client 的注册表。
  - 当前内建类型由各自基础设施子包注册进来，配置校验也从这里读取支持类型。
- `livetrading/broker.py`
  - 对外暴露 create/register facade，运行时按注册表解析具体实现。
  - 当前内建注册：
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
- `trade_account`
  - 支持 `futu` 和 `mock` 两种账户 client。
  - `futu` 负责查询资金、持仓、订单回报和成交回报。
  - `mock` 直接把配置里的 `initial_cash / initial_positions` 推进 engine，不访问 Futu。
- `livetrading/engine.py`
  - 保留主循环和整体装配职责，但把配置应用、事件接收和组合执行分别委托给独立协作者。
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
  - 交易账户配置文件当前只允许 1 个账户，单进程只服务这个账户。
- 配置现在拆成 4 份 JSON：
  - `realtime_broker`
  - 负责价格变更通知和分钟 K 输入。
  - `history_broker`
  - 负责策略 warm-up 用的历史日线获取。
  - `stock_pool`
  - 负责股票池代码列表和组合策略参数。
  - `trade_account`
  - 负责账户同步和执行器选择。
- `realtime_broker` 支持 `futu` 和 `mock`；`history_broker` 支持 `polygon`、`futu` 和 `local`；`trade_account.broker.type` 支持 `futu` 和 `mock`。
- `stock_pool.strategy.name` 的支持列表来自 `livetrading/pool_strategy_registry.py` 的当前注册表。
- 这些支持类型不是写死在 `config.py` 里，而是来自 `livetrading/broker_registry.py` 的当前注册表。
- 如果你要扩一个新 broker/provider/account/strategy 类型，需要先在启动阶段 import 你的扩展模块并调用对应 `register_*`，再去加载配置文件。
- 如果你只想做完全本地的 mock 联调，可以用：
  - `realtime_broker.type=mock`
  - `history_broker.type=local`
  - `trade_account.broker.type=mock`
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

完整字段说明见 [docs/README_livetrading_config.md](docs/README_livetrading_config.md)。

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
- `config/livetrading.trade_account.mock.sample.json`
  - mock 执行账户样例。
  - 适合“mock 行情 + 本地日线 warm-up + mock 账户 + mock 执行”的联调场景。
- `config/livetrading.trade_account.futu.sample.json`
  - Futu 真实环境下单样例。
  - 会走 `execution.executor = futu_real`，只适合确认好 OpenD 和真实账户后使用。
- `config/livetrading.trade_account.simulate.sample.json`
  - Futu 模拟环境下单样例。
  - 适合“Futu 实时行情订阅 + Futu 模拟交易环境提单”。

关键字段：

- 实时行情配置
  - `realtime_broker.type`
  - 支持 `futu` 和 `mock`。
  - `realtime_broker.host` / `realtime_broker.port`
  - `futu` 模式下是 OpenD 地址。
  - `mock` 模式下是本地 HTTP 推送服务监听地址。
  - `runtime.config_reload_interval_seconds`
  - 多久轮询一次 4 份配置文件的变更。
- 历史 warm-up 配置
  - `history_broker.type`
  - 支持 `polygon`、`futu` 和 `local`。
  - `history_broker.host` / `history_broker.port`
  - 仅 `futu` 模式生效，对应 OpenD 地址。
  - `polygon` / `local` 模式下可以省略。
  - `history_broker.data_root`
  - 默认 `.kline_day`。
  - `local` 模式下表示直接读取的本地日线目录。
  - `futu` / `polygon` 模式下表示 warm-up 日线的本地缓存目录。
- 股票池配置
  - `stock_pool.codes`
  - 股票池代码列表。
  - `stock_pool.strategy`
  - 当前内建支持 `dual_momentum`。
- 实盘交易配置
  - `trade_account.account_id`
  - 本地账户标识，用于日志和账户侧状态跟踪。
  - `trade_account.broker.type`
  - 支持 `futu` 和 `mock`。
  - `trade_account.broker.host` / `trade_account.broker.port`
  - 仅 `futu` 模式生效，对应账户自己的 OpenD 地址。
  - `trade_account.broker.trade_env`
  - 仅 `futu` 模式有意义。
  - `SIMULATE` 或 `REAL`。
  - `trade_account.broker.account_index`
  - 仅 `futu` 模式生效，表示 Futu 交易账户索引。
  - `trade_account.broker.initial_cash`
  - 仅 `mock` 模式生效，表示本地账户初始现金。
  - `trade_account.broker.initial_positions`
  - 仅 `mock` 模式生效，表示本地账户初始持仓。
  - `trade_account.execution.executor`
  - 支持：
    - `mock`
    - `futu_simulate`
    - `futu_real`
  - `trade_account.execution.order_session`
  - 支持 `RTH`、`ETH`、`ALL`。
  - `executor=futu_real` 且 `broker.trade_env=REAL` 时，默认会落到 `ETH`。
  - `futu_simulate` 和 `mock` 默认走 `RTH`。
  - quote 侧是否订阅扩展时段，也会从这个唯一账户的 `order_session` 派生：
  - `RTH` 只订阅常规时段 bar。
  - `ETH` / `ALL` 会订阅扩展时段 bar。

## 运行

下面三组命令继续使用根目录 `livetrading.py` 作为兼容入口；如果你更偏好模块方式，可以把 `livetrading.py` 等价替换成 `-m livetrading`。

Futu行情订阅、Futu历史数据、Futu真实环境下单：

```bash
./.venv/bin/python livetrading.py \
  --quote-config config/livetrading.quote.futu.sample.json \
  --history-config config/livetrading.history.futu.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_account.futu.sample.json
```

这条命令会走 Futu `REAL` 环境真实提单。

对美股实盘交易，仓库现在默认就支持盘前盘后：

- 实盘账户样例 [config/livetrading.trade_account.futu.sample.json](config/livetrading.trade_account.futu.sample.json) 默认使用：
  - `trade_account.execution.order_session = ETH`

如果你只想做常规时段交易，再显式改回：

- `trade_account.execution.order_session = RTH`

Futu行情订阅、polygon历史数据、Futu模拟环境下单：

```bash
export POLYGON_API_KEY=your_api_key
./.venv/bin/python livetrading.py \
  --quote-config config/livetrading.quote.futu.sample.json \
  --history-config config/livetrading.history.polygon.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_account.simulate.sample.json
```

Mock行情订阅、polygon历史数据、Mock下单：

```bash
./.venv/bin/python livetrading.py \
  --quote-config config/livetrading.quote.mock.sample.json \
  --history-config config/livetrading.history.local.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_account.mock.sample.json
```

Mock行情订阅、本地历史数据、Mock下单：

```bash
./.venv/bin/python livetrading.py \
  --quote-config config/livetrading.quote.mock.sample.json \
  --history-config config/livetrading.history.local.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_account.mock.sample.json
```

- warm-up 日线来自本地 `.kline_day`，如果 `.kline_day` 里没有对应股票的日线，warm-up 会缺数据，策略信号也就不稳定
- 账户资金和持仓基线来自 `livetrading.trade_account.mock.sample.json` 里的 `initial_cash / initial_positions`




如果你要看 `mock` 行情入口的推送格式、健康检查，以及怎么稳定复现 `BUY / SELL` 信号，统一看 [docs/README_livetrading_mock_signal.md](docs/README_livetrading_mock_signal.md)。

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

- 运行时序： [docs/README_livetrading_sequence.md](docs/README_livetrading_sequence.md)
- 执行层说明： [docs/README_livetrading_real_order_plan.md](docs/README_livetrading_real_order_plan.md)
- mock 联调说明： [docs/README_livetrading_mock_signal.md](docs/README_livetrading_mock_signal.md)
