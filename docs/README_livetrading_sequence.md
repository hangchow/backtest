# `livetrading.py` 实盘链路时序图

这份文档针对 `livetrading` 的实盘链路，主要整理关键代码文件之间的时序关系。

下面的启动命令只是为了给时序图提供一个具体入口示例，不代表本文只讨论 `mock` 行情模式。

如果你要看“当前 dry-run 之后，如何继续补齐真实下单链路”，见 [README_livetrading_real_order_plan.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_real_order_plan.md)。

示例命令：

```bash
./.venv/bin/python livetrading.py \
  --quote-config config/livetrading.quote.mock.sample.json \
  --trade-config config/livetrading.trade_accounts.sample.json
```

下面的时序图主要聚焦这些文件之间的交互：

- [livetrading.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading.py)
- [livetrading/engine.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/engine.py)
- [livetrading/config.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/config.py)
- [livetrading/broker.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/broker.py)
- [livetrading/quote_brokers/base.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/base.py)
- [livetrading/quote_brokers/mock.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/mock.py)
- [livetrading/quote_brokers/futu.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/futu.py)
- [livetrading/pool_strategies.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/pool_strategies.py)
- [strategy/dual_momentum_state.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/dual_momentum_state.py)
- [strategy/dual_momentum.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/dual_momentum.py)
- [strategy/rebalance.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/rebalance.py)
- [strategy/fees.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/fees.py)

下面 Mermaid 里的方法说明，和代码里对应方法的中文注释保持一致，方便你对着图直接跳代码。

## 1. 启动 + 配置加载 + quote client 选择

```mermaid
sequenceDiagram
    actor U as User
    participant CLI as livetrading.py
    participant ENG as livetrading/engine.py
    participant CFG as livetrading/config.py
    participant FAC as broker.py\ncreate_quote_broker_client
    participant QBASE as quote_brokers/base.py\nQuoteBrokerClient / QuoteBrokerEventSink
    participant MQ as quote_brokers/mock.py\nMockRealtimeQuoteClient
    participant FQ as quote_brokers/futu.py\nFutuRealtimeQuoteClient
    participant TB as broker.py\nFutuTradeAccountClient

    U->>CLI: python livetrading.py --quote-config ...mock... --trade-config ...
    CLI->>ENG: main()<br/>初始化日志并启动实盘 dry-run 主流程
    ENG->>CFG: load_quote_config_from_text()<br/>把行情配置 JSON 文本解析成 QuoteConfig
    ENG->>CFG: load_trade_accounts_config_from_text()<br/>把交易账户配置 JSON 文本解析成 TradeAccountsConfig
    CFG-->>ENG: QuoteConfig + TradeAccountsConfig
    ENG->>CFG: build_livetrading_config()<br/>合并 quote/trade 配置并校验两边 market
    CFG-->>ENG: LiveTradingConfig

    ENG->>FAC: create_quote_broker_client()<br/>按配置选择 realtime quote client 实现
    Note over ENG,QBASE: engine 只依赖 QuoteBrokerClient 抽象，<br/>同时实现 QuoteBrokerEventSink 回调接口
    alt realtime_broker.type == "mock"
        FAC->>MQ: instantiate MockRealtimeQuoteClient
        ENG->>MQ: connect()<br/>启动本地 HTTP 服务并切换当前订阅股票池
        MQ-->>ENG: on_broker_message()<br/>回报 /push 监听地址
    else realtime_broker.type == "futu"
        FAC->>FQ: instantiate FutuRealtimeQuoteClient
        ENG->>FQ: connect()<br/>创建 OpenQuoteContext 并订阅 QUOTE + K_1M
        FQ->>FQ: _load_futu_api() / OpenQuoteContext.start()
    end

    ENG->>ENG: _apply_trade_accounts_config()<br/>按配置增删或重连 trade account client
    ENG->>TB: create_trade_account_client()<br/>按配置选择交易账户 client 实现
    ENG->>TB: connect()<br/>连接 Futu 交易上下文并立即同步账户/持仓
    ENG->>ENG: _sync_shadow_state()<br/>裁剪过期状态并补齐 shadow_cash / shadow_positions
    ENG-->>CLI: CONFIG_APPLIED log

    Note over TB,ENG: connect() 之后，账户/持仓是后台异步轮询进入 engine
    TB-->>ENG: on_account()<br/>同步账户资金快照并初始化 shadow_cash
    TB-->>ENG: on_positions()<br/>同步实际持仓并初始化 shadow_positions
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
    participant STATE as dual_momentum_state.py\nDualMomentumDailyState
    participant HB as broker.py\nHistoryProvider

    ENG->>PLS: build_pool_strategy()<br/>按 stock_pool.strategy.name 构建 live 股票池策略
    ENG->>PLS: required_daily_warmup_bars()<br/>返回 dual momentum 至少需要的 warm-up 日线根数
    PLS-->>ENG: warmup_bars

    ENG->>HB: create_daily_history_provider()<br/>按配置选择 warm-up 日线 provider 实现
    ENG->>HB: fetch_daily_histories()<br/>为股票池拉取 warm-up 所需的日线窗口
    HB-->>ENG: warmup daily histories

    ENG->>PLS: bootstrap()<br/>把 warm-up 日线喂给日频状态机
    PLS->>STATE: bootstrap()<br/>用 warm-up 日线初始化每个股票的日频历史状态
    STATE->>STATE: normalize_daily_history()<br/>把不同 provider 的日线格式规整成统一输入
```

这一步的关键点：

- 策略 warm-up 仍然走 `history_broker`
- warm-up 的输出是“已完成日线窗口”，不是直接下单指令
- 真正的账户资金和持仓同步在下一张图里单独看

## 3. 账户同步对后续调仓的影响

```mermaid
sequenceDiagram
    participant TB as broker.py\nFutuTradeAccountClient
    participant ENG as livetrading/engine.py

    loop polling
        TB->>TB: _poll_account()<br/>拉取账户资金快照并回调给事件接收方
        TB-->>ENG: on_account()<br/>同步账户资金快照并初始化 shadow_cash
        ENG->>ENG: state.actual_account = snapshot
        ENG->>ENG: if shadow_cash is None -> shadow_cash = available_funds

        TB->>TB: _poll_positions()<br/>拉取当前持仓快照并回调给事件接收方
        TB-->>ENG: on_positions()<br/>同步实际持仓并补齐 shadow_positions
        ENG->>ENG: state.actual_positions = positions
        ENG->>ENG: 初始化 shadow_positions
    end

    Note over ENG: 如果没有 available_funds / positions，<br/>后续 rebalance 可能直接变成 REBALANCE_SKIPPED
```

这就是为什么现在即使行情改成 mock，仍然需要交易账户侧先同步到资金和持仓。

## 4. mock 推送分钟 K -> 策略出信号 -> dry-run 调仓

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

### 4.2 分钟 bar 进入策略层，并在换日时决定是否出信号

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

### 4.3 引擎按账户执行 dry-run 调仓

```mermaid
sequenceDiagram
    participant ENG as livetrading/engine.py
    participant RB as rebalance.py
    participant FEE as fees.py

    ENG->>ENG: _execute_portfolio_rebalance_dry_run()<br/>对每个交易账户执行一轮组合级 dry-run 调仓
    ENG->>RB: compute_portfolio_value()<br/>按现金加持仓市值估算当前组合总资产
    ENG->>RB: build_desired_shares()<br/>把目标权重转换成目标股数并应用调仓带

    loop 先卖
        ENG->>FEE: compute_order_fees()<br/>按 fee_account 规则计算单笔订单总手续费和拆分明细
        FEE-->>ENG: fee_total
        ENG->>ENG: 更新 shadow_cash / shadow_positions
        ENG-->>ENG: DRY_RUN_ORDER SELL log
    end

    loop 再买
        ENG->>RB: compute_affordable_qty_with_fee()<br/>在考虑手续费后反推出当前现金最多能买多少股
        RB->>FEE: compute_order_fees()<br/>按 fee_account 规则计算单笔订单总手续费和拆分明细
        FEE-->>RB: fee_total
        RB-->>ENG: affordable_qty + fee_total
        ENG->>ENG: 更新 shadow_cash / shadow_positions
        ENG-->>ENG: DRY_RUN_ORDER BUY log
    end
```

这里最重要的时序关系是：

1. `mock` 收到 `/push` 后，会先发 `on_quote`，再发 `on_bar`。
2. 策略层只有在“新交易日第一根分钟 bar”到来时，才会从 `DualMomentumDailyState` 吐出已完成日线窗口。
3. `build_dual_momentum_signal(...)` 用这份已完成日线窗口生成目标权重。
4. 引擎拿到 `PortfolioRebalanceDecision` 后，按账户逐个执行 dry-run。
5. dry-run 执行顺序是先卖后买，并且买入数量会显式考虑手续费和剩余现金。

## 5. 文件职责对照

- [livetrading.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading.py)
  - CLI 入口，只负责启动和停止 engine
- [livetrading/config.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/config.py)
  - 解析 quote / trade 两份配置，拼成 `LiveTradingConfig`
- [livetrading/broker.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/broker.py)
  - 提供：
    - quote broker factory
    - history provider
    - trade account client
- [livetrading/quote_brokers/base.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/base.py)
  - 定义 realtime quote 抽象边界：
    - `QuoteBrokerClient`
    - `QuoteBrokerEventSink`
- [livetrading/quote_brokers/mock.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/mock.py)
  - mock 实时行情入口
  - 负责 `/health` / `/push`、bar 归一化、合成 quote、再推 bar
- [livetrading/quote_brokers/futu.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/futu.py)
  - Futu 实时行情实现
  - 负责 `OpenQuoteContext`、实时 quote push、分钟 K push
- [livetrading/engine.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/engine.py)
  - 把行情、账户、策略、dry-run 执行串起来
- [livetrading/pool_strategies.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/pool_strategies.py)
  - live 侧股票池策略适配层
- [strategy/dual_momentum_state.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/dual_momentum_state.py)
  - 把分钟 bar 增量聚合成“已完成日线窗口”
- [strategy/dual_momentum.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/dual_momentum.py)
  - 纯信号逻辑，输出 `target_weights`
- [strategy/rebalance.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/rebalance.py)
  - 执行层的目标股数、可买数量、调仓带
- [strategy/fees.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/fees.py)
  - 手续费计算

## 6. 一句话总结

这条以 `mock` quote 为主线的实盘链路，本质上是：

```text
HTTP push 的分钟 bar
-> quote_brokers/mock.py
-> quote_brokers/base.py 的 QuoteBrokerEventSink 回调边界
-> engine.py
-> pool_strategies.py
-> dual_momentum_state.py
-> dual_momentum.py
-> rebalance.py + fees.py
-> engine.py 输出 DRY_RUN_ORDER
```

## 7. 相关文档

这份文档现在只保留“运行时序”和“文件职责”。

为了避免和其他文档重复，重构分析已经独立出去：

- 如果你要看怎么启动 mock 并复现 `BUY -> SELL -> BUY`，见 [README_livetrading_mock_signal.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_mock_signal.md)
- 如果你要看当前模块边界、已完成拆分和后续重构顺序，见 [README_livetrading_mock_refactor.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_mock_refactor.md)
