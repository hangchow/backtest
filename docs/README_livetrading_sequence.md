# `livetrading.py` 实盘链路时序图

这份文档针对 `livetrading` 的实盘链路，主要整理关键代码文件之间的时序关系。

下面的启动命令只是为了给时序图提供一个具体入口示例，不代表本文只讨论 `mock` 行情模式。

等价的包入口 `./.venv/bin/python -m livetrading ...` 也可用；本文继续沿用根目录 `livetrading.py` 写法，方便和现有脚本命令保持一致。

如果你要看执行器设计、`mock / futu_simulate / futu_real` 三种模式的差异，见 [README_livetrading_real_order_plan.md](../docs/README_livetrading_real_order_plan.md)。

示例命令：

```bash
./.venv/bin/python livetrading.py \
  --quote-config config/livetrading.quote.mock.sample.json \
  --history-config config/livetrading.history.local.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_account.mock.sample.json
```

当前仓库里的 `config/livetrading.trade_account.mock.sample.json` 已把 `order_session` 设成 `ETH`。所以如果 quote 侧也走 mock，美股示例下 `04:00` 的盘前分钟 bar 可以通过实时行情入口并触发换日；如果改回 `RTH`，同样的 `04:00 /push` 会在 quote broker 入口被忽略。

下面的时序图主要聚焦这些文件之间的交互：

- [livetrading.py](../livetrading.py)
- [livetrading/engine.py](../livetrading/engine.py)
- [livetrading/runtime_state.py](../livetrading/runtime_state.py)
- [livetrading/config_applier.py](../livetrading/config_applier.py)
- [livetrading/event_sinks.py](../livetrading/event_sinks.py)
- [livetrading/portfolio.py](../livetrading/portfolio.py)
- [livetrading/pool_strategy_registry.py](../livetrading/pool_strategy_registry.py)
- [livetrading/config.py](../livetrading/config.py)
- [livetrading/broker_registry.py](../livetrading/broker_registry.py)
- [livetrading/broker.py](../livetrading/broker.py)
- [livetrading/execution.py](../livetrading/execution.py)
- [livetrading/futu/adapters.py](../livetrading/futu/adapters.py)
- [livetrading/futu/runtime.py](../livetrading/futu/runtime.py)
- [livetrading/history_providers/base.py](../livetrading/history_providers/base.py)
- [livetrading/history_providers/common.py](../livetrading/history_providers/common.py)
- [livetrading/market_hours.py](../livetrading/market_hours.py)
- [livetrading/history_providers/local.py](../livetrading/history_providers/local.py)
- [livetrading/history_providers/cached.py](../livetrading/history_providers/cached.py)
- [livetrading/history_providers/polygon.py](../livetrading/history_providers/polygon.py)
- [livetrading/history_providers/futu.py](../livetrading/history_providers/futu.py)
- [livetrading/quote_brokers/base.py](../livetrading/quote_brokers/base.py)
- [livetrading/quote_brokers/mock.py](../livetrading/quote_brokers/mock.py)
- [livetrading/quote_brokers/futu.py](../livetrading/quote_brokers/futu.py)
- [livetrading/trade_account/base.py](../livetrading/trade_account/base.py)
- [livetrading/trade_account/futu.py](../livetrading/trade_account/futu.py)
- [livetrading/trade_account/mock.py](../livetrading/trade_account/mock.py)
- [livetrading/pool_strategies.py](../livetrading/pool_strategies.py)
- [strategy/dual_momentum_state.py](../strategy/dual_momentum_state.py)
- [strategy/dual_momentum.py](../strategy/dual_momentum.py)
- [strategy/rebalance.py](../strategy/rebalance.py)
- [strategy/fees.py](../strategy/fees.py)

下面 Mermaid 里的方法说明，和代码里对应方法的中文注释保持一致，方便你对着图直接跳代码。

当前实现里，`livetrading/engine.py` 已经收缩成装配层：

- 配置 diff / 连接重建 / warm-up 由 `livetrading/config_applier.py` 负责
- quote / trade account 回调由 `livetrading/event_sinks.py` 负责
- 组合决策拆单和执行器分发由 `livetrading/portfolio.py` 负责
- quote/history/trade 的内建实现由各自子包注册到 `livetrading/broker_registry.py`，`livetrading/broker.py` 只保留 facade
- live pool strategy 的内建实现由 `livetrading/pool_strategies.py` 注册到 `livetrading/pool_strategy_registry.py`

下面的 Mermaid 图会把 `config_applier.py`、`event_sinks.py`、`portfolio.py` 明确展开；`ENG` 只表示 `LiveTradingEngine` 的主循环和兼容代理入口。

## 1. 启动 + 配置加载 + 运行时协作者装配

```mermaid
sequenceDiagram
    actor U as User
    participant CLI as livetrading.py
    participant ENG as livetrading/engine.py
    participant AP as config_applier.py\nRuntimeConfigApplier
    participant CFG as livetrading/config.py
    participant REG as broker_registry.py
    participant FAC as broker.py\ncreate_quote_broker_client
    participant QS as event_sinks.py\nQuoteBrokerEventSinkAdapter
    participant STORE as account_state.py\nAccountStateStore
    participant TS as event_sinks.py\nTradeAccountEventSinkAdapter
    participant FRT as futu/runtime.py\n_load_futu_api
    participant QBASE as quote_brokers/base.py\nQuoteBrokerClient / QuoteBrokerEventSink
    participant MQ as quote_brokers/mock.py\nMockRealtimeQuoteClient
    participant FQ as quote_brokers/futu.py\nFutuRealtimeQuoteClient
    participant TAF as broker.py\ncreate_trade_account_client
    participant TB as trade_account/futu.py\nFutuTradeAccountClient
    participant TM as trade_account/mock.py\nMockTradeAccountClient

    U->>CLI: python livetrading.py --quote-config ... --history-config ... --pool-config ... --trade-config ...
    CLI->>ENG: main()<br/>初始化日志并启动实盘主流程
    ENG->>CFG: load_quote_config_from_text()<br/>把实时行情配置 JSON 文本解析成 QuoteConfig
    ENG->>CFG: load_history_config_from_text()<br/>把历史 warm-up 配置 JSON 文本解析成 HistoryBrokerConfig
    ENG->>CFG: load_pool_config_from_text()<br/>把股票池配置 JSON 文本解析成 StockPoolConfig
    ENG->>CFG: load_trade_account_config_from_text()<br/>把交易账户配置 JSON 文本解析成 TradeAccountConfig
    CFG-->>ENG: QuoteConfig + HistoryBrokerConfig + StockPoolConfig + TradeAccountConfig
    ENG->>CFG: build_livetrading_config()<br/>合并 quote/history/pool/trade 配置并校验执行组合
    CFG-->>ENG: LiveTradingConfig

    ENG->>AP: apply_config()<br/>把 LiveTradingConfig 应用到运行时资源
    AP->>FAC: create_quote_broker_client()<br/>按注册表解析 realtime quote client 实现
    FAC->>REG: resolve_quote_broker_factory()
    Note over AP,QBASE: config_applier 只依赖 QuoteBrokerClient 抽象，<br/>quote client 收到的是 QuoteBrokerEventSinkAdapter
    alt realtime_broker.type == "mock"
        FAC->>MQ: instantiate MockRealtimeQuoteClient
        AP->>MQ: connect()<br/>启动本地 HTTP 服务并切换当前订阅股票池
        MQ-->>QS: on_broker_message()<br/>回报 /push 监听地址
    else realtime_broker.type == "futu"
        FAC->>FQ: instantiate FutuRealtimeQuoteClient
        AP->>FQ: connect()<br/>创建 OpenQuoteContext 并订阅 QUOTE + K_1M
        FQ->>FRT: _load_futu_api()
        FQ->>FQ: OpenQuoteContext.start()
    end

    AP->>AP: _apply_trade_account_config()<br/>按配置增删或重连 trade account client
    AP->>TAF: create_trade_account_client()<br/>按注册表解析交易账户 client 实现
    TAF->>REG: resolve_trade_account_client_factory()
    alt trade_account.broker.type == "mock"
        TAF->>TM: instantiate MockTradeAccountClient
        AP->>TM: connect()<br/>直接把本地 initial_cash / initial_positions 推给事件接收方
        TM-->>TS: on_account()<br/>初始化账户现金基线
        TS->>STORE: upsert_actual_account() + sync_active_codes() + reconcile_from_actual()
        TM-->>TS: on_positions()<br/>初始化本地持仓基线
        TS->>STORE: upsert_actual_positions() + sync_active_codes() + reconcile_from_actual()
    else trade_account.broker.type == "futu"
        TAF->>TB: instantiate FutuTradeAccountClient
        AP->>TB: connect()<br/>连接 Futu 交易上下文并立即同步账户/持仓
    end
    AP->>AP: _sync_shadow_state()<br/>裁剪过期状态并补齐 shadow / expected 状态
    AP->>STORE: prune() + sync_active_codes() + reconcile_from_actual()
    AP-->>CLI: CONFIG_APPLIED log

    Note over TB,TS: futu 分支下，connect() 之后账户/持仓会继续后台异步轮询进入 TradeAccountEventSinkAdapter
    TB-->>TS: on_account()<br/>同步账户资金快照并初始化 shadow_cash / expected_cash
    TS->>STORE: upsert_actual_account() + sync_active_codes() + reconcile_from_actual()
    TB-->>TS: on_positions()<br/>同步实际持仓并初始化 shadow_positions / expected_positions
    TS->>STORE: upsert_actual_positions() + sync_active_codes() + reconcile_from_actual()
    TS-->>CLI: ACCOUNT / POSITIONS logs
```

这一步的关键点：

- `quote_brokers/base.py` 只定义 `QuoteBrokerClient` / `QuoteBrokerEventSink` 抽象
- [livetrading/engine.py](../livetrading/engine.py) 通过这个抽象持有 realtime quote client
- 当前示例命令走的是 `mock` 分支，但工厂同时也能返回 [livetrading/quote_brokers/futu.py](../livetrading/quote_brokers/futu.py) 里的 `FutuRealtimeQuoteClient`
- 配置文件读取、broker 初始化、trade account 连接都在这一段完成
- warm-up 本身单独放到下一张图看

## 2. warm-up

```mermaid
sequenceDiagram
    participant ENG as livetrading/engine.py
    participant AP as config_applier.py\nRuntimeConfigApplier
    participant PLS as pool_strategies.py\nbuild_pool_strategy / DualMomentumPoolStrategy
    participant SREG as pool_strategy_registry.py
    participant STATE as dual_momentum_state.py\nDualMomentumDailyState
    participant REG as broker_registry.py
    participant HFAC as broker.py\ncreate_daily_history_provider
    participant HB as history_providers/*.py\nDailyHistoryProvider impl

    ENG->>AP: apply_config()
    AP->>PLS: build_pool_strategy()<br/>按注册表构建 live 股票池策略
    PLS->>SREG: resolve_pool_strategy_factory()
    AP->>PLS: required_daily_warmup_bars()<br/>返回 dual momentum 至少需要的 warm-up 日线根数
    PLS-->>AP: warmup_bars

    AP->>HFAC: create_daily_history_provider()<br/>按注册表解析 warm-up 日线 provider 实现
    HFAC->>REG: resolve_daily_history_provider_factory()
    HFAC->>HB: instantiate provider
    AP->>HB: fetch_daily_histories()<br/>为股票池拉取 warm-up 所需的日线窗口
    HB-->>AP: warmup daily histories

    AP->>PLS: bootstrap()<br/>把 warm-up 日线喂给日频状态机
    PLS->>STATE: bootstrap()<br/>用 warm-up 日线初始化每个股票的日频历史状态
    STATE->>STATE: normalize_daily_history()<br/>把不同 provider 的日线格式规整成统一输入
```

这一步的关键点：

- 策略 warm-up 仍然走 `history_broker`
- warm-up 的输出是“已完成日线窗口”，不是直接下单指令
- 账户基线怎么进入运行态，在下一张图里单独看

## 3. 账户基线进入运行态，对后续调仓的影响

```mermaid
sequenceDiagram
    participant TM as trade_account/mock.py\nMockTradeAccountClient
    participant TB as trade_account/futu.py\nFutuTradeAccountClient
    participant TS as event_sinks.py\nTradeAccountEventSinkAdapter
    participant STORE as account_state.py\nAccountStateStore

    alt trade_account.broker.type == "mock"
        TM->>TM: connect()<br/>读取 initial_cash / initial_positions
        TM-->>TS: on_account()<br/>推送本地账户现金基线
        TS->>STORE: upsert_actual_account() + sync_active_codes() + reconcile_from_actual()
        TM-->>TS: on_positions()<br/>推送本地持仓基线
        TS->>STORE: upsert_actual_positions() + sync_active_codes() + reconcile_from_actual()
    else trade_account.broker.type == "futu"
        loop polling
            TB->>TB: _poll_account()<br/>拉取账户资金快照并回调给事件接收方
            TB-->>TS: on_account()<br/>同步账户资金快照并初始化 shadow_cash
            TS->>STORE: upsert_actual_account() + sync_active_codes() + reconcile_from_actual()

            TB->>TB: _poll_positions()<br/>拉取当前持仓快照并回调给事件接收方
            TB-->>TS: on_positions()<br/>同步实际持仓并补齐 shadow_positions
            TS->>STORE: upsert_actual_positions() + sync_active_codes() + reconcile_from_actual()
        end
    end

    Note over STORE: 不管账户基线来自 mock 还是 futu，<br/>如果还没有现金 / 持仓起点，后续 rebalance 可能直接变成 REBALANCE_SKIPPED
```

这里要分开理解：

- 如果 trade account 走 `mock`，账户基线来自本地配置，不需要 Futu。
- 如果 trade account 走 `futu`，账户基线来自 Futu 同步。

真正必须成立的条件不是“必须连 Futu”，而是“系统在调仓前必须先拿到一版现金和持仓基线”。

## 4. 实时行情入口

这一节只讨论“分钟行情怎么进入实时事件入口”。

`4.1` 和 `4.2` 是两种可替换的实时行情入口，运行时按 `realtime_broker.type` 二选一：

- `type=mock` 时走 `4.1`
- `type=futu` 时走 `4.2`

它们不是说同一次启动里两个都要启用。

### 4.1 mock 接收 `/push` 并把行情送进实时事件入口

```mermaid
sequenceDiagram
    actor C as curl / external pusher
    participant QBASE as quote_brokers/base.py\nQuoteBrokerEventSink
    participant QB as quote_brokers/mock.py\nMockRealtimeQuoteClient
    participant QS as event_sinks.py\nQuoteBrokerEventSinkAdapter
    participant RST as runtime_state.py\nLiveTradingRuntimeState

    C->>QB: POST /push {code,time_key,open,close,high,low,volume}
    QB->>QB: _normalize_bar_payload()<br/>把外部 push 的 bar 归一化成内部统一字段
    QB->>QB: normalize_market_timestamp()<br/>按市场时区归一化成 market-local 时间
    QB->>QB: is_realtime_bar_allowed_for_market()<br/>按 RTH / extended 判断这根 bar 是否允许进入系统
    alt 命中当前订阅 session
        Note over QS,QBASE: mock / futu quote client 都通过 QuoteBrokerEventSinkAdapter 推事件
        QB-->>QS: on_quote()<br/>先推一条合成 QuoteUpdate 作为参考价
        QS->>RST: latest_quotes[code] = update

        QB-->>QS: on_bar()<br/>再推分钟 bar 给策略引擎
        QS->>RST: latest_bar_prices[code] = bar.close
    else 非当前订阅 session
        QB-->>QBASE: on_broker_message()<br/>记录 ignored out-of-session push
    end
```

当前这份 mock 样例配置是 `ETH`，所以美股 `2026-03-13 04:00:00` 这类盘前 bar 会通过这里的准入检查；如果你把 `order_session` 改成 `RTH`，同样的 push 会在这一步被拦下，不会再进入 `on_bar(...)`。

### 4.2 futu 订阅实盘股价并把推送送进实时事件入口

```mermaid
sequenceDiagram
    participant QB as quote_brokers/futu.py\nFutuRealtimeQuoteClient
    participant QS as event_sinks.py\nQuoteBrokerEventSinkAdapter
    participant RST as runtime_state.py\nLiveTradingRuntimeState
    participant QCTX as futu SDK\nOpenQuoteContext
    participant ADP as futu/adapters.py

    QB->>QB: connect(codes)<br/>按股票池代码建立实时行情连接
    QB->>QCTX: OpenQuoteContext(host, port)
    QB->>QCTX: set_handler(QuoteHandler / KlineHandler)
    QB->>QCTX: start()
    QB->>QCTX: subscribe(codes, [QUOTE, K_1M], subscribe_push=True, extended_time=config.subscribe_extended_time)

    loop Futu push
        QCTX-->>QB: QuoteHandler.on_recv_rsp(frame)<br/>收到实时报价 DataFrame
        QB->>ADP: iter_quote_updates(frame)<br/>把 Futu quote DataFrame 转成 QuoteUpdate
        ADP-->>QB: QuoteUpdate
        QB-->>QS: on_quote()<br/>推送最新参考价
        QS->>RST: latest_quotes[code] = update

        QCTX-->>QB: KlineHandler.on_recv_rsp(frame)<br/>收到 1 分钟 K DataFrame
        QB->>ADP: iter_kline_bars(frame)<br/>把 Futu 1m K DataFrame 转成标准 bar
        ADP-->>QB: code + bar
        QB-->>QS: on_bar()<br/>推送分钟 bar 给策略引擎
        QS->>RST: latest_bar_prices[code] = bar.close
    end
```

## 5. 分钟 bar 进入策略层，并在换日时决定是否出信号

```mermaid
sequenceDiagram
    participant QS as event_sinks.py\nQuoteBrokerEventSinkAdapter
    participant PLS as pool_strategies.py\nDualMomentumPoolStrategy
    participant STATE as dual_momentum_state.py\nDualMomentumDailyState
    participant SIG as dual_momentum.py\nbuild_dual_momentum_signal
    participant PC as portfolio.py\nPortfolioCoordinator

    QS->>PLS: on_bar()<br/>把分钟 bar 交给股票池策略
    PLS->>STATE: on_bar()<br/>消费一根分钟 bar，按市场本地时间聚合并尝试吐出已完成日线窗口

    alt market-local trade_date 未变化
        STATE-->>PLS: None
        PLS-->>QS: None
        QS-->>QS: 不触发调仓
    else 命中新 trade_date 的第一根准入 bar
        STATE-->>PLS: CompletedDailyFrames<br/>已完成日线窗口：prices / volumes / signal_time
        PLS->>SIG: build_dual_momentum_signal()<br/>基于已完成日线窗口计算 dual momentum 目标权重
        SIG-->>PLS: DualMomentumSignal<br/>策略信号结果：target_weights / target_codes / risk_on
        PLS-->>QS: PortfolioRebalanceDecision<br/>组合调仓决策：target_weights / reason
        QS->>PC: execute_portfolio_rebalance()<br/>把组合决策交给账户级执行协调器
    end
```

这里的 `trade_date` 不是直接取输入 `time_key.date()`。`DualMomentumDailyState` 会先把 bar 归一化到市场本地时区，再通过 `market_trade_date_for_timestamp(...)` 判断这根 bar 属于哪个交易日。这样像 `2026-03-13 00:30:00+00:00` 这种时间，在美股场景下会先换算成纽约时间 `2026-03-12 19:30:00`，不会被误判成 `2026-03-13` 的新交易日。

## 6. 账户级执行协调器按账户选择执行器并执行调仓

```mermaid
sequenceDiagram
    participant PC as portfolio.py\nPortfolioCoordinator
    participant RST as runtime_state.py\nLiveTradingRuntimeState
    participant STORE as account_state.py\nAccountStateStore
    participant PLAN as execution.py\nRebalancePlanner
    participant EXE as execution.py\nMockExecutor / FutuSimulateExecutor / FutuRealExecutor
    participant TAC as trade_account/futu.py\nFutuTradeAccountClient
    participant TS as event_sinks.py\nTradeAccountEventSinkAdapter
    participant RB as strategy/rebalance.py
    participant FEE as strategy/fees.py

    PC->>RST: active_prices_for_codes()<br/>收集当前可用参考价
    loop each trade_account
        PC->>STORE: ensure(account_id)<br/>拿到账户运行态
        PC->>PLAN: build_account_plan()<br/>把目标权重转换成账户级买卖 intent
        PLAN->>STORE: planning_cash / planning_positions()<br/>按 executor 选择 shadow 或 expected 视图
        PLAN->>RB: compute_portfolio_value()<br/>按规划视图估算当前组合总资产
        PLAN->>RB: build_desired_shares()<br/>把目标权重转换成目标股数并应用调仓带
        PC->>EXE: create_order_executor(...).execute_plan(plan, state)<br/>按账户 execution.executor 选择执行器

        alt executor == mock
            loop 先卖后买
                EXE->>FEE: compute_order_fees()<br/>按 fee_account 规则计算手续费
                EXE->>RB: compute_affordable_qty_with_fee()<br/>买单时反推现金可买股数
                EXE->>EXE: 更新 shadow_cash / shadow_positions 并输出 DRY_RUN_ORDER
            end
        else executor == futu_simulate / futu_real
            loop 每笔 intent
                EXE->>RB: compute_affordable_qty_with_fee()<br/>买单前按现金和手续费缩量
                EXE->>TAC: submit_order(intent)<br/>真的调用 Futu place_order(...)
                EXE->>STORE: mark_submitted()<br/>登记 pending 并乐观推进 expected 视图
                TAC-->>TS: on_order_update()<br/>结构化订单回报
                TS->>STORE: apply_order_update()
                TAC-->>TS: on_fill()<br/>结构化成交回报
                TS->>STORE: apply_fill()
            end
        end
    end
```

这里最重要的时序关系是：

1. 实时行情入口按 `realtime_broker.type` 二选一：要么是 `mock /push`，要么是 Futu `QUOTE + K_1M subscribe push`；两者在进入 `QuoteBrokerEventSinkAdapter` 之前都有“bar 准入”这一步。`mock` 用 [livetrading/market_hours.py](../livetrading/market_hours.py) 在本地按市场时区和 `RTH / extended` 过滤，Futu 则通过 `subscribe(..., extended_time=...)` 把准入语义交给 SDK。
2. 策略层只有在“market-local trade_date 变化后的第一根准入分钟 bar”到来时，才会从 `DualMomentumDailyState` 吐出已完成日线窗口。当前这份美股 mock 样例是 `ETH`，所以 `04:00` 的首根盘前 bar 就可以触发；如果配置成 `RTH`，则要等到 `09:30` 之后的首根 bar。
3. `build_dual_momentum_signal(...)` 用这份已完成日线窗口生成目标权重。
4. `QuoteBrokerEventSinkAdapter` 拿到 `PortfolioRebalanceDecision` 后，会调用 `PortfolioCoordinator`，再按账户读取 `execution.executor`，选择 `mock / futu_simulate / futu_real` 三种执行路径之一。
5. `mock` 会继续维护 `shadow_cash / shadow_positions` 并输出 `DRY_RUN_*` 日志；`futu_simulate / futu_real` 会在提交买单前先按 `expected_cash` 和手续费把数量收缩到可买范围，再走真实 `place_order(...)`，随后通过 `ORDER_PUSH / DEAL_PUSH` 按最终成交数量、均价和手续费估算纠偏，并等待真实账户快照把 `pending_orders` 清掉。

## 7. 文件职责对照

- [livetrading.py](../livetrading.py)
  - CLI 入口，只负责启动和停止 engine
- [livetrading/config.py](../livetrading/config.py)
  - 解析 quote / history / pool / trade 四份配置，拼成 `LiveTradingConfig`
- [livetrading/runtime_state.py](../livetrading/runtime_state.py)
  - 统一存放当前配置快照、quote broker、history provider、trade account clients、pool strategy 和最新价格缓存
- [livetrading/config_applier.py](../livetrading/config_applier.py)
  - 把 `LiveTradingConfig` 应用成具体运行时资源
  - 负责配置 diff、连接重建、history warm-up、strategy bootstrap、trade account client 增删重连和 shadow state 同步
- [livetrading/event_sinks.py](../livetrading/event_sinks.py)
  - 行情和账户事件接收层
  - `QuoteBrokerEventSinkAdapter` 负责更新最新价格并驱动策略 / 调仓协调器
  - `TradeAccountEventSinkAdapter` 负责把账户、持仓、订单、成交事件收口到 `AccountStateStore`
- [livetrading/portfolio.py](../livetrading/portfolio.py)
  - 组合级调仓协调层
  - 把一次 `PortfolioRebalanceDecision` 展开成多个账户计划，并把账户计划交给执行器
- [livetrading/pool_strategy_registry.py](../livetrading/pool_strategy_registry.py)
  - live pool strategy 的注册表边界
  - 配置解析和 `build_pool_strategy()` 都通过它查当前支持的策略名
- [livetrading/broker_registry.py](../livetrading/broker_registry.py)
  - quote broker / history provider / trade account client 的注册表边界
  - 内建类型由各自基础设施子包注册，配置校验也从这里读支持类型
- [livetrading/broker.py](../livetrading/broker.py)
  - facade / factory 层
  - 提供：
    - quote broker factory
    - history provider factory
    - trade account client factory
- [livetrading/execution.py](../livetrading/execution.py)
  - 调仓规划和执行器选择层
  - 提供 `RebalancePlanner`、`MockExecutor`、`FutuSimulateExecutor`、`FutuRealExecutor`
- [livetrading/account_state.py](../livetrading/account_state.py)
  - 账户运行态存储层
  - 提供 `AccountRuntimeState`、`PendingOrder`、`AccountStateStore`
- [livetrading/futu/runtime.py](../livetrading/futu/runtime.py)
  - 提供共享的 Futu SDK 装载逻辑
  - 负责 `.futu_runtime` 的运行时环境准备
- [livetrading/futu/adapters.py](../livetrading/futu/adapters.py)
  - 负责把 Futu DataFrame 转成 `QuoteUpdate` 和标准化分钟 `bar`
- [livetrading/history_providers/base.py](../livetrading/history_providers/base.py)
  - 定义 `DailyHistoryProvider` 抽象
- [livetrading/history_providers/common.py](../livetrading/history_providers/common.py)
  - history provider 的共享兼容层
  - 复用并转发 `market_hours.py` 里的市场日历、交易日和常量定义
- [livetrading/market_hours.py](../livetrading/market_hours.py)
  - 统一的市场时区 / 交易日 / RTH vs extended 准入逻辑
  - 被 history provider、mock quote broker、strategy state 共用
- [livetrading/history_providers/local.py](../livetrading/history_providers/local.py)
  - 本地日线 warm-up 实现
- [livetrading/history_providers/cached.py](../livetrading/history_providers/cached.py)
  - “本地缓存 + 远端回源” 的 warm-up 基类
- [livetrading/history_providers/polygon.py](../livetrading/history_providers/polygon.py)
  - Polygon 日线 warm-up 实现
- [livetrading/history_providers/futu.py](../livetrading/history_providers/futu.py)
  - Futu 日线 warm-up 实现
- [livetrading/quote_brokers/base.py](../livetrading/quote_brokers/base.py)
  - 定义 realtime quote 抽象边界：
    - `QuoteBrokerClient`
    - `QuoteBrokerEventSink`
- [livetrading/quote_brokers/mock.py](../livetrading/quote_brokers/mock.py)
  - mock 实时行情入口
  - 负责 `/health` / `/push`、bar 归一化、按 session 过滤、合成 quote、再推 bar
- [livetrading/quote_brokers/futu.py](../livetrading/quote_brokers/futu.py)
  - Futu 实时行情实现
  - 负责 `OpenQuoteContext`、订阅管理、`extended_time` 透传、handler 挂接
- [livetrading/trade_account/base.py](../livetrading/trade_account/base.py)
  - 定义 `TradeAccountClient` / `TradeAccountEventSink` 抽象
- [livetrading/trade_account/futu.py](../livetrading/trade_account/futu.py)
  - Futu 交易账户实现
  - 负责账户轮询、持仓轮询、`ORDER_PUSH` / `DEAL_PUSH`
- [livetrading/engine.py](../livetrading/engine.py)
  - 实盘主控器，只负责主循环、配置文件 watcher、首次加载和兼容代理方法
- [livetrading/pool_strategies.py](../livetrading/pool_strategies.py)
  - live 侧股票池策略适配层
  - 定义 `PoolLiveStrategy` 抽象，并注册内建 `dual_momentum`
- [strategy/dual_momentum_state.py](../strategy/dual_momentum_state.py)
  - 把分钟 bar 增量聚合成“已完成日线窗口”
  - `trade_date` 按市场本地时间计算，并在换日第一根准入 bar 吐出 completed window
- [strategy/dual_momentum.py](../strategy/dual_momentum.py)
  - 纯信号逻辑，输出 `target_weights`
- [strategy/rebalance.py](../strategy/rebalance.py)
  - 共享的目标股数、可买数量、调仓带计算
- [strategy/fees.py](../strategy/fees.py)
  - 共享的手续费计算

## 8. 一句话总结

这条实盘链路本质上是：

```text
quote client / trade account client / history provider
-> broker_registry.py + broker.py facade
-> engine.py + config_applier.py + runtime_state.py
-> event_sinks.py + portfolio.py
-> pool_strategy_registry.py + pool_strategies.py facade
-> pool_strategies.py
-> dual_momentum_state.py + dual_momentum.py
-> account_state.py + execution.py
-> strategy/rebalance.py + strategy/fees.py
-> DRY_RUN_ORDER / ORDER_SUBMITTED / ORDER_UPDATE / FILL / ACCOUNT / POSITIONS logs
```

## 9. 相关文档

- 如果你要看怎么启动 mock 并复现 `BUY -> SELL -> BUY`，见 [README_livetrading_mock_signal.md](../docs/README_livetrading_mock_signal.md)
- 如果你要看当前执行层结构和配置规则，见 [README_livetrading_real_order_plan.md](../docs/README_livetrading_real_order_plan.md)
