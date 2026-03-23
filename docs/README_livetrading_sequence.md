# `livetrading` 实盘链路时序图

这份文档针对 `livetrading` 的实盘链路，主要整理关键代码文件之间的时序关系。

下面的启动命令只是为了给时序图提供一个具体入口示例，不代表本文只讨论 `mock` 行情模式。

推荐使用安装后的包入口 `livetrading ...`（等价于 `python -m livetrading ...`）。
根目录 `livetrading.py` 目前保留为兼容 shim。

如果你要看执行器设计、`mock / futu_simulate / futu_real` 三种模式的差异，见 [README_livetrading_real_order_plan.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_real_order_plan.md)。

示例命令：

```bash
livetrading \
  --quote-config config/livetrading.quote.mock.sample.json \
  --history-config config/livetrading.history.local.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_accounts.mock.sample.json
```

下面的时序图主要聚焦这些文件之间的交互：

- [livetrading.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading.py)
- [livetrading/engine.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/engine.py)
- [livetrading/runtime_state.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/runtime_state.py)
- [livetrading/config_applier.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/config_applier.py)
- [livetrading/event_sinks.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/event_sinks.py)
- [livetrading/portfolio.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/portfolio.py)
- [livetrading/pool_strategy_registry.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/pool_strategy_registry.py)
- [livetrading/config.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/config.py)
- [livetrading/broker_registry.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/broker_registry.py)
- [livetrading/broker.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/broker.py)
- [livetrading/execution.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/execution.py)
- [livetrading/futu/adapters.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/futu/adapters.py)
- [livetrading/futu/runtime.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/futu/runtime.py)
- [livetrading/history_providers/base.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/base.py)
- [livetrading/history_providers/common.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/common.py)
- [livetrading/history_providers/local.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/local.py)
- [livetrading/history_providers/cached.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/cached.py)
- [livetrading/history_providers/polygon.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/polygon.py)
- [livetrading/history_providers/futu.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/futu.py)
- [livetrading/quote_brokers/base.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/base.py)
- [livetrading/quote_brokers/mock.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/mock.py)
- [livetrading/quote_brokers/futu.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/futu.py)
- [livetrading/trade_accounts/base.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/trade_accounts/base.py)
- [livetrading/trade_accounts/futu.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/trade_accounts/futu.py)
- [livetrading/trade_accounts/mock.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/trade_accounts/mock.py)
- [livetrading/pool_strategies.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/pool_strategies.py)
- [strategy/dual_momentum_state.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/dual_momentum_state.py)
- [strategy/dual_momentum.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/dual_momentum.py)
- [trading_domain/rebalance.py](/Users/sean/workspace/backtest-feature-livetrading-startup/trading_domain/rebalance.py)
- [trading_domain/fees.py](/Users/sean/workspace/backtest-feature-livetrading-startup/trading_domain/fees.py)

下面 Mermaid 里的方法说明，和代码里对应方法的中文注释保持一致，方便你对着图直接跳代码。

当前实现里，`livetrading/engine.py` 已经收缩成装配层：

- 配置 diff / 连接重建 / warm-up 由 `livetrading/config_applier.py` 负责
- quote / trade account 回调由 `livetrading/event_sinks.py` 负责
- 组合决策拆单和执行器分发由 `livetrading/portfolio.py` 负责
- quote/history/trade 的内建实现由各自子包注册到 `livetrading/broker_registry.py`，`livetrading/broker.py` 只保留 facade
- live pool strategy 的内建实现由 `livetrading/pool_strategies.py` 注册到 `livetrading/pool_strategy_registry.py`

下面的 Mermaid 图仍用 `ENG` 表示整体入口，便于阅读；对应代码时，要连同这些协作者一起看。

## 1. 启动 + 配置加载 + quote / history / pool / trade client 选择

```mermaid
sequenceDiagram
    actor U as User
    participant CLI as livetrading
    participant ENG as livetrading/engine.py
    participant CFG as livetrading/config.py
    participant REG as broker_registry.py
    participant FAC as broker.py\ncreate_quote_broker_client
    participant FRT as futu/runtime.py\n_load_futu_api
    participant QBASE as quote_brokers/base.py\nQuoteBrokerClient / QuoteBrokerEventSink
    participant MQ as quote_brokers/mock.py\nMockRealtimeQuoteClient
    participant FQ as quote_brokers/futu.py\nFutuRealtimeQuoteClient
    participant TAF as broker.py\ncreate_trade_account_client
    participant TB as trade_accounts/futu.py\nFutuTradeAccountClient
    participant TM as trade_accounts/mock.py\nMockTradeAccountClient

    U->>CLI: livetrading --quote-config ... --history-config ... --pool-config ... --trade-config ...
    CLI->>ENG: main()<br/>初始化日志并启动实盘主流程
    ENG->>CFG: load_quote_config_from_text()<br/>把实时行情配置 JSON 文本解析成 QuoteConfig
    ENG->>CFG: load_history_config_from_text()<br/>把历史 warm-up 配置 JSON 文本解析成 HistoryBrokerConfig
    ENG->>CFG: load_pool_config_from_text()<br/>把股票池配置 JSON 文本解析成 StockPoolConfig
    ENG->>CFG: load_trade_accounts_config_from_text()<br/>把交易账户配置 JSON 文本解析成 TradeAccountsConfig
    CFG-->>ENG: QuoteConfig + HistoryBrokerConfig + StockPoolConfig + TradeAccountsConfig
    ENG->>CFG: build_livetrading_config()<br/>合并 quote/history/pool/trade 配置并校验 market
    CFG-->>ENG: LiveTradingConfig

    ENG->>FAC: create_quote_broker_client()<br/>按注册表解析 realtime quote client 实现
    FAC->>REG: resolve_quote_broker_factory()
    Note over ENG,QBASE: engine 只依赖 QuoteBrokerClient 抽象，<br/>同时实现 QuoteBrokerEventSink 回调接口
    alt realtime_broker.type == "mock"
        FAC->>MQ: instantiate MockRealtimeQuoteClient
        ENG->>MQ: connect()<br/>启动本地 HTTP 服务并切换当前订阅股票池
        MQ-->>ENG: on_broker_message()<br/>回报 /push 监听地址
    else realtime_broker.type == "futu"
        FAC->>FQ: instantiate FutuRealtimeQuoteClient
        ENG->>FQ: connect()<br/>创建 OpenQuoteContext 并订阅 QUOTE + K_1M
        FQ->>FRT: _load_futu_api()
        FQ->>FQ: OpenQuoteContext.start()
    end

    ENG->>ENG: _apply_trade_accounts_config()<br/>按配置增删或重连 trade account client
    ENG->>TAF: create_trade_account_client()<br/>按注册表解析交易账户 client 实现
    TAF->>REG: resolve_trade_account_client_factory()
    alt trade_accounts[].broker.type == "mock"
        TAF->>TM: instantiate MockTradeAccountClient
        ENG->>TM: connect()<br/>直接把本地 initial_cash / initial_positions 推给 engine
        TM-->>ENG: on_account()<br/>初始化账户现金基线
        TM-->>ENG: on_positions()<br/>初始化本地持仓基线
    else trade_accounts[].broker.type == "futu"
        TAF->>TB: instantiate FutuTradeAccountClient
        ENG->>TB: connect()<br/>连接 Futu 交易上下文并立即同步账户/持仓
    end
    ENG->>ENG: _sync_shadow_state()<br/>裁剪过期状态并补齐 shadow / expected 状态
    ENG-->>CLI: CONFIG_APPLIED log

    Note over TB,ENG: futu 分支下，connect() 之后账户/持仓会继续后台异步轮询进入 engine
    TB-->>ENG: on_account()<br/>同步账户资金快照并初始化 shadow_cash / expected_cash
    TB-->>ENG: on_positions()<br/>同步实际持仓并初始化 shadow_positions / expected_positions
    ENG-->>CLI: ACCOUNT / POSITIONS logs
```

这一步的关键点：

- `quote_brokers/base.py` 只定义 `QuoteBrokerClient` / `QuoteBrokerEventSink` 抽象
- [livetrading/engine.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/engine.py) 通过这个抽象持有 realtime quote client
- 当前示例命令走的是 `mock` 分支，但工厂同时也能返回 [livetrading/quote_brokers/futu.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/futu.py) 里的 `FutuRealtimeQuoteClient`
- 配置文件读取、broker 初始化、trade account 连接都在这一段完成
- warm-up 本身单独放到下一张图看

## 2. warm-up

```mermaid
sequenceDiagram
    participant ENG as livetrading/engine.py
    participant PLS as pool_strategies.py\nDualMomentumPoolStrategy
    participant SREG as pool_strategy_registry.py
    participant STATE as dual_momentum_state.py\nDualMomentumDailyState
    participant REG as broker_registry.py
    participant HFAC as broker.py\ncreate_daily_history_provider
    participant HB as history_providers/*.py\nDailyHistoryProvider impl

    ENG->>PLS: build_pool_strategy()<br/>按注册表构建 live 股票池策略
    PLS->>SREG: resolve_pool_strategy_factory()
    ENG->>PLS: required_daily_warmup_bars()<br/>返回 dual momentum 至少需要的 warm-up 日线根数
    PLS-->>ENG: warmup_bars

    ENG->>HFAC: create_daily_history_provider()<br/>按注册表解析 warm-up 日线 provider 实现
    HFAC->>REG: resolve_daily_history_provider_factory()
    HFAC->>HB: instantiate provider
    ENG->>HB: fetch_daily_histories()<br/>为股票池拉取 warm-up 所需的日线窗口
    HB-->>ENG: warmup daily histories

    ENG->>PLS: bootstrap()<br/>把 warm-up 日线喂给日频状态机
    PLS->>STATE: bootstrap()<br/>用 warm-up 日线初始化每个股票的日频历史状态
    STATE->>STATE: normalize_daily_history()<br/>把不同 provider 的日线格式规整成统一输入
```

这一步的关键点：

- 策略 warm-up 仍然走 `history_broker`
- warm-up 的输出是“已完成日线窗口”，不是直接下单指令
- 账户基线怎么进入 engine，在下一张图里单独看

## 3. 账户基线进入 engine 对后续调仓的影响

```mermaid
sequenceDiagram
    participant TM as trade_accounts/mock.py\nMockTradeAccountClient
    participant TB as trade_accounts/futu.py\nFutuTradeAccountClient
    participant ENG as livetrading/engine.py

    alt trade_accounts[].broker.type == "mock"
        TM->>TM: connect()<br/>读取 initial_cash / initial_positions
        TM-->>ENG: on_account()<br/>推送本地账户现金基线
        ENG->>ENG: state.actual_account = snapshot
        ENG->>ENG: if shadow_cash is None -> shadow_cash = initial_cash
        TM-->>ENG: on_positions()<br/>推送本地持仓基线
        ENG->>ENG: state.actual_positions = positions
        ENG->>ENG: 初始化 shadow_positions / expected_positions
    else trade_accounts[].broker.type == "futu"
        loop polling
            TB->>TB: _poll_account()<br/>拉取账户资金快照并回调给事件接收方
            TB-->>ENG: on_account()<br/>同步账户资金快照并初始化 shadow_cash
            ENG->>ENG: state.actual_account = snapshot
            ENG->>ENG: if shadow_cash is None -> shadow_cash = available_funds

            TB->>TB: _poll_positions()<br/>拉取当前持仓快照并回调给事件接收方
            TB-->>ENG: on_positions()<br/>同步实际持仓并补齐 shadow_positions
            ENG->>ENG: state.actual_positions = positions
            ENG->>ENG: 初始化 shadow_positions / expected_positions
        end
    end

    Note over ENG: 不管账户基线来自 mock 还是 futu，<br/>如果还没有现金 / 持仓起点，后续 rebalance 可能直接变成 REBALANCE_SKIPPED
```

这里要分开理解：

- 如果 trade account 走 `mock`，账户基线来自本地配置，不需要 Futu。
- 如果 trade account 走 `futu`，账户基线来自 Futu 同步。

真正必须成立的条件不是“必须连 Futu”，而是“engine 在调仓前必须先拿到一版现金和持仓基线”。

## 4. 实时行情入口

这一节只讨论“分钟行情怎么进入 engine”。

`4.1` 和 `4.2` 是两种可替换的实时行情入口，运行时按 `realtime_broker.type` 二选一：

- `type=mock` 时走 `4.1`
- `type=futu` 时走 `4.2`

它们不是说同一次启动里两个都要启用。

### 4.1 mock 接收 `/push` 并把行情送进引擎

```mermaid
sequenceDiagram
    actor C as curl / external pusher
    participant QBASE as quote_brokers/base.py\nQuoteBrokerEventSink
    participant QB as quote_brokers/mock.py\nMockRealtimeQuoteClient
    participant ENG as livetrading/engine.py

    C->>QB: POST /push {code,time_key,open,close,high,low,volume}
    QB->>QB: _normalize_bar_payload()<br/>把外部 push 的 bar 归一化成内部统一字段
    Note over ENG,QBASE: engine 实现 QuoteBrokerEventSink，<br/>mock / futu quote client 都通过这个回调接口推事件
    QB-->>ENG: on_quote()<br/>先推一条合成 QuoteUpdate 作为参考价
    ENG->>ENG: _latest_quotes[code] = update

    QB-->>ENG: on_bar()<br/>再推分钟 bar 给策略引擎
    ENG->>ENG: _latest_bar_prices[code] = bar.close
```

### 4.2 futu 订阅实盘股价并把推送送进引擎

```mermaid
sequenceDiagram
    participant ENG as livetrading/engine.py
    participant QB as quote_brokers/futu.py\nFutuRealtimeQuoteClient
    participant QCTX as futu SDK\nOpenQuoteContext
    participant ADP as futu/adapters.py

    ENG->>QB: connect(codes)<br/>按股票池代码建立实时行情连接
    QB->>QCTX: OpenQuoteContext(host, port)
    QB->>QCTX: set_handler(QuoteHandler / KlineHandler)
    QB->>QCTX: start()
    QB->>QCTX: subscribe(codes, [QUOTE, K_1M], subscribe_push=True)

    loop Futu push
        QCTX-->>QB: QuoteHandler.on_recv_rsp(frame)<br/>收到实时报价 DataFrame
        QB->>ADP: iter_quote_updates(frame)<br/>把 Futu quote DataFrame 转成 QuoteUpdate
        ADP-->>QB: QuoteUpdate
        QB-->>ENG: on_quote()<br/>推送最新参考价

        QCTX-->>QB: KlineHandler.on_recv_rsp(frame)<br/>收到 1 分钟 K DataFrame
        QB->>ADP: iter_kline_bars(frame)<br/>把 Futu 1m K DataFrame 转成标准 bar
        ADP-->>QB: code + bar
        QB-->>ENG: on_bar()<br/>推送分钟 bar 给策略引擎
    end
```

## 5. 分钟 bar 进入策略层，并在换日时决定是否出信号

```mermaid
sequenceDiagram
    participant ENG as livetrading/engine.py
    participant PLS as pool_strategies.py\nDualMomentumPoolStrategy
    participant STATE as dual_momentum_state.py\nDualMomentumDailyState
    participant SIG as dual_momentum.py\nbuild_dual_momentum_signal

    ENG->>PLS: on_bar()<br/>把分钟 bar 交给股票池策略
    PLS->>STATE: on_bar()<br/>消费一根分钟 bar 并尝试吐出已完成日线窗口

    alt 还在同一个交易日
        STATE-->>PLS: None
        PLS-->>ENG: None
        ENG-->>ENG: 不触发调仓
    else 新交易日第一根 bar
        STATE-->>PLS: CompletedDailyFrames<br/>已完成日线窗口：prices / volumes / signal_time
        PLS->>SIG: build_dual_momentum_signal()<br/>基于已完成日线窗口计算 dual momentum 目标权重
        SIG-->>PLS: DualMomentumSignal<br/>策略信号结果：target_weights / target_codes / risk_on
        PLS-->>ENG: PortfolioRebalanceDecision<br/>组合调仓决策：target_weights / reason
    end
```

## 6. 引擎按账户选择执行器并执行调仓

```mermaid
sequenceDiagram
    participant ENG as livetrading/engine.py
    participant STORE as account_state.py\nAccountStateStore
    participant PLAN as execution.py\nRebalancePlanner
    participant EXE as execution.py\nMockExecutor / FutuSimulateExecutor / FutuRealExecutor
    participant TAC as trade_accounts/futu.py\nFutuTradeAccountClient
    participant RB as trading_domain/rebalance.py
    participant FEE as trading_domain/fees.py

    ENG->>ENG: _execute_portfolio_rebalance()<br/>收集参考价并按账户循环执行
    ENG->>STORE: planning_cash / planning_positions()<br/>按 executor 选择 shadow 或 expected 视图
    ENG->>PLAN: build_account_plan()<br/>把目标权重转换成账户级买卖 intent
    PLAN->>RB: compute_portfolio_value()<br/>按规划视图估算当前组合总资产
    PLAN->>RB: build_desired_shares()<br/>把目标权重转换成目标股数并应用调仓带

    alt executor == mock
        loop 先卖后买
            EXE->>FEE: compute_order_fees()<br/>按 fee_account 规则计算手续费
            EXE->>RB: compute_affordable_qty_with_fee()<br/>买单时反推现金可买股数
            EXE->>EXE: 更新 shadow_cash / shadow_positions
            EXE-->>ENG: DRY_RUN_ORDER log
        end
    else executor == futu_simulate / futu_real
        loop 每笔 intent
            EXE->>TAC: submit_order(intent)<br/>真的调用 Futu place_order(...)
            TAC-->>ENG: on_order_update()<br/>结构化订单回报
            TAC-->>ENG: on_fill()<br/>结构化成交回报
            ENG->>STORE: mark_submitted / apply_order_update / apply_fill
        end
    end
```

这里最重要的时序关系是：

1. 实时行情入口按 `realtime_broker.type` 二选一：要么是 `mock /push`，要么是 Futu `QUOTE + K_1M subscribe push`；两者最终都会通过 `on_quote` / `on_bar` 进入 engine。
2. 策略层只有在“新交易日第一根分钟 bar”到来时，才会从 `DualMomentumDailyState` 吐出已完成日线窗口。
3. `build_dual_momentum_signal(...)` 用这份已完成日线窗口生成目标权重。
4. 引擎拿到 `PortfolioRebalanceDecision` 后，会按账户读取 `execution.executor`，选择 `mock / futu_simulate / futu_real` 三种执行路径之一。
5. `mock` 会继续维护 `shadow_cash / shadow_positions` 并输出 `DRY_RUN_*` 日志；`futu_simulate / futu_real` 会在提交买单前先按 `expected_cash` 和手续费把数量收缩到可买范围，再走真实 `place_order(...)`，随后通过 `ORDER_PUSH / DEAL_PUSH` 按最终成交数量、均价和手续费估算纠偏，并等待真实账户快照把 `pending_orders` 清掉。

## 7. 文件职责对照

- [livetrading.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading.py)
  - CLI 入口，只负责启动和停止 engine
- [livetrading/config.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/config.py)
  - 解析 quote / history / pool / trade 四份配置，拼成 `LiveTradingConfig`
- [livetrading/pool_strategy_registry.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/pool_strategy_registry.py)
  - live pool strategy 的注册表边界
  - 配置解析和 `build_pool_strategy()` 都通过它查当前支持的策略名
- [livetrading/broker_registry.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/broker_registry.py)
  - quote broker / history provider / trade account client 的注册表边界
  - 内建类型由各自基础设施子包注册，配置校验也从这里读支持类型
- [livetrading/broker.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/broker.py)
  - facade / factory 层
  - 提供：
    - quote broker factory
    - history provider factory
    - trade account client factory
- [livetrading/execution.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/execution.py)
  - 调仓规划和执行器选择层
  - 提供 `RebalancePlanner`、`MockExecutor`、`FutuSimulateExecutor`、`FutuRealExecutor`
- [livetrading/account_state.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/account_state.py)
  - 账户运行态存储层
  - 提供 `AccountRuntimeState`、`PendingOrder`、`AccountStateStore`
- [livetrading/futu/runtime.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/futu/runtime.py)
  - 提供共享的 Futu SDK 装载逻辑
  - 负责 `.futu_runtime` 的运行时环境准备
- [livetrading/futu/adapters.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/futu/adapters.py)
  - 负责把 Futu DataFrame 转成 `QuoteUpdate` 和标准化分钟 `bar`
- [livetrading/history_providers/base.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/base.py)
  - 定义 `DailyHistoryProvider` 抽象
- [livetrading/history_providers/common.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/common.py)
  - 提供市场日历、交易日判断、共享常量等 history 共用逻辑
- [livetrading/history_providers/local.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/local.py)
  - 本地日线 warm-up 实现
- [livetrading/history_providers/cached.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/cached.py)
  - “本地缓存 + 远端回源” 的 warm-up 基类
- [livetrading/history_providers/polygon.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/polygon.py)
  - Polygon 日线 warm-up 实现
- [livetrading/history_providers/futu.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/futu.py)
  - Futu 日线 warm-up 实现
- [livetrading/quote_brokers/base.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/base.py)
  - 定义 realtime quote 抽象边界：
    - `QuoteBrokerClient`
    - `QuoteBrokerEventSink`
- [livetrading/quote_brokers/mock.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/mock.py)
  - mock 实时行情入口
  - 负责 `/health` / `/push`、bar 归一化、合成 quote、再推 bar
- [livetrading/quote_brokers/futu.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/futu.py)
  - Futu 实时行情实现
  - 负责 `OpenQuoteContext`、订阅管理、handler 挂接
- [livetrading/trade_accounts/base.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/trade_accounts/base.py)
  - 定义 `TradeAccountClient` / `TradeAccountEventSink` 抽象
- [livetrading/trade_accounts/futu.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/trade_accounts/futu.py)
  - Futu 交易账户实现
  - 负责账户轮询、持仓轮询、`ORDER_PUSH` / `DEAL_PUSH`
- [livetrading/engine.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/engine.py)
  - 把行情、账户、策略、planner、executor、state store 串起来
- [livetrading/pool_strategies.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/pool_strategies.py)
  - live 侧股票池策略适配层
  - 定义 `PoolLiveStrategy` 抽象，并注册内建 `dual_momentum`
- [strategy/dual_momentum_state.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/dual_momentum_state.py)
  - 把分钟 bar 增量聚合成“已完成日线窗口”
- [strategy/dual_momentum.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/dual_momentum.py)
  - 纯信号逻辑，输出 `target_weights`
- [trading_domain/rebalance.py](/Users/sean/workspace/backtest-feature-livetrading-startup/trading_domain/rebalance.py)
  - 共享的目标股数、可买数量、调仓带计算
- [trading_domain/fees.py](/Users/sean/workspace/backtest-feature-livetrading-startup/trading_domain/fees.py)
  - 共享的手续费计算

## 8. 一句话总结

这条实盘链路本质上是：

```text
quote client / trade account client / history provider
-> broker_registry.py + broker.py facade
-> engine.py
-> pool_strategy_registry.py + pool_strategies.py facade
-> pool_strategies.py
-> dual_momentum_state.py + dual_momentum.py
-> account_state.py
-> execution.py
-> trading_domain/rebalance.py + trading_domain/fees.py
-> DRY_RUN_ORDER / ORDER_SUBMITTED / ORDER_UPDATE / FILL / ACCOUNT / POSITIONS logs
```

## 9. 相关文档

- 如果你要看怎么启动 mock 并复现 `BUY -> SELL -> BUY`，见 [README_livetrading_mock_signal.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_mock_signal.md)
- 如果你要看当前执行层结构和配置规则，见 [README_livetrading_real_order_plan.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_real_order_plan.md)
