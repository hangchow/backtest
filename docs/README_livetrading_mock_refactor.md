# livetrading mock 重构说明

这份文档只讨论 `livetrading` 的 mock 行情链路如何拆分和继续重构。

- 如果你要看“怎么启动、怎么推 bar、怎么稳定打出 `DRY_RUN_ORDER`”，看 [README_livetrading_mock_signal.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_mock_signal.md)
- 如果你要看“当前运行时序和文件职责”，看 [README_livetrading_sequence.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_sequence.md)
- 如果你要看“如何从 dry-run 演进到真实下单”，看 [README_livetrading_real_order_plan.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_real_order_plan.md)

## 1. 当前状态

当前代码状态已经不是最初只拆 quote 的阶段，而是基础模块边界已经基本拆开了：

- [livetrading/quote_brokers/base.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/base.py)
  - 放 quote 侧抽象：
    - `QuoteBrokerClient`
    - `QuoteBrokerEventSink`
- [livetrading/quote_brokers/mock.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/mock.py)
  - 放 `MockRealtimeQuoteClient`
  - 已经不再和 history provider / trade client 写在同一文件里
- [livetrading/history_providers/base.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/history_providers/base.py)
  - 放 `DailyHistoryProvider` 抽象
- [livetrading/trade_accounts/base.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/trade_accounts/base.py)
  - 放 `TradeAccountClient` / `TradeAccountEventSink` 抽象
- [livetrading/broker.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/broker.py)
  - 现在只保留各子域 factory
- [livetrading/engine.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/engine.py)
  - 仍然通过 `create_quote_broker_client(...)` 注入 quote client
  - 不直接感知 mock 实现文件怎么拆
- [livetrading/execution.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/execution.py)
  - 已经承接 dry-run 执行逻辑
  - 放 `TradeAccountState` 和 `DryRunRebalanceExecutor`

也就是说：

- `broker.py -> quote_brokers/ + history_providers/ + trade_accounts/` 这一步已经落地
- 当前应该讨论的是“下一步怎么继续细拆”，不是再重复写第一阶段的迁移设想

## 2. 目前保留不变的兼容边界

当前拆分后，下面这些外部行为仍然应该保持不变：

- `LiveTradingEngine` 继续依赖 `create_quote_broker_client(...)`
- mock HTTP API 继续兼容：
  - `GET /health`
  - `POST /push`
  - 单条 `{code, time_key, ...}`
  - 批量 `{"bars": [...]}`
- push 顺序继续是：
  - 先 `on_quote()`
  - 再 `on_bar()`
- 运行时仍然通过 `livetrading.broker` 上的 factory 选择具体实现：

```python
from livetrading.broker import create_quote_broker_client
from livetrading.quote_brokers.base import QuoteBrokerClient
from livetrading.quote_brokers.mock import MockRealtimeQuoteClient
```

也就是说，这一轮保留的是运行行为兼容，不再额外承诺 `broker.py` 对具体实现类做兼容导出。

## 3. 当前还值得继续拆的地方

### 3.1 `quote_brokers/mock.py` 内部职责仍然偏多

虽然 `MockRealtimeQuoteClient` 已经从 `broker.py` 独立出来，但这个类里仍然同时承担了：

- HTTP server 生命周期
- `/health` / `/push` 协议处理
- payload 校验和归一化
- 订阅代码过滤
- 合成 `QuoteUpdate`
- 推送分钟 `bar`

这说明第一阶段只是把 mock 从大文件里搬出来了，还没有完成 mock 模块内部的细拆。

下一步更合理的方向是：

- 保留 `MockRealtimeQuoteClient` 作为 orchestration 外观
- 把 HTTP handler / payload normalizer / event emitter 拆成内部 helper 或相邻模块
- 优先做行为不变的拆分，不要一边拆一边改协议

### 3.2 `engine.py` 的 `apply_config()` 仍然是 runtime coordinator

[livetrading/engine.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/engine.py) 里的 `apply_config()` 目前同时处理：

- quote broker 重连
- history provider 重建
- strategy 重建
- warm-up 拉取与 bootstrap
- trade account client 生命周期
- shadow state 同步

这说明 `apply_config()` 已经不只是“应用配置”，而是在做整段 runtime 组装。

更稳妥的后续拆法是先把内部责任拆成更小的私有步骤，再决定要不要升级成独立服务对象。

### 3.3 dry-run 执行器已经独立出来，但还没有继续细分

[livetrading/execution.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/execution.py) 现在已经承接了 dry-run 执行层：

- 输入：
  - `PortfolioRebalanceDecision`
  - `TradeAccountConfig`
  - `TradeAccountState`
  - 参考价缓存
- 处理：
  - `compute_portfolio_value(...)`
  - `build_desired_shares(...)`
  - `compute_order_fees(...)`
  - `compute_affordable_qty_with_fee(...)`
- 输出：
  - 更新 shadow state
  - 打 `DRY_RUN_REBALANCE` / `DRY_RUN_ORDER`

`engine.py` 现在只负责收集参考价并委托 `DryRunRebalanceExecutor` 执行，所以这一步已经落地。后续如果继续演进到真实下单，下一步更像是把 `execution.py` 再拆成 planner / executor / state store，而不是再把 dry-run 从 `engine.py` 挪一次。

### 3.4 账户实际状态和影子状态还混在一起

当前账户侧至少有两类状态：

- 实际账户状态
  - `actual_account`
  - `actual_positions`
- dry-run 影子状态
  - `shadow_cash`
  - `shadow_positions`

这些状态现在集中在 `TradeAccountState` 和 `engine.py` 的同步逻辑里。只要后面再引入 mock trade account 或更复杂的执行路径，这部分就会继续膨胀。

后续可以考虑单独抽：

- `AccountStateStore`
  - 负责 actual/shadow 的初始化、裁剪和同步规则

### 3.5 策略层暂时不是优先矛盾

现阶段策略侧边界反而比较清楚：

- [livetrading/pool_strategies.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/pool_strategies.py)
  - live 侧适配层
- [strategy/dual_momentum_state.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/dual_momentum_state.py)
  - 分钟 bar 聚合成已完成日线窗口
- [strategy/dual_momentum.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/dual_momentum.py)
  - 纯信号计算
- [strategy/rebalance.py](/Users/sean/workspace/backtest-feature-livetrading-startup/strategy/rebalance.py)
  - 执行层计算

除非你要改策略语义本身，否则现在先动 `strategy/*.py` 的收益不如继续收缩实盘接线层。

## 4. 推荐的下一步顺序

建议按下面顺序推进，风险最低：

1. 先细拆 [livetrading/quote_brokers/mock.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/quote_brokers/mock.py)
   - 目标是把 server / payload / emitter 分开
   - 但不改 factory 和 HTTP 协议
2. 再抽账户状态存储
   - 给 mock trade account 或更复杂执行路径铺路
3. 继续把 [livetrading/execution.py](/Users/sean/workspace/backtest-feature-livetrading-startup/livetrading/execution.py) 细拆成 planner / executor
   - 为真实下单链路复用同一套规划结果做准备
4. 最后再继续拆 `apply_config()`
   - 这一步更像 runtime coordinator 整理
   - 适合放在前面几步稳定以后

## 5. 非目标

这条重构线当前不应该顺手去改的内容：

- 不改策略语义
- 不改 quote 配置 schema
- 不改 mock HTTP API
- 不在重构阶段引入新的第三方依赖

## 6. 测试重点

后续如果继续拆，建议先补这些测试再动：

- `quote_brokers/mock.py` 单元测试
  - `connect()`
  - `update_symbols()`
  - `push_bar()` / `push_bars()`
  - `/health`
  - `close()`
- `engine` 集成测试
  - `realtime_broker.type == "mock"` 仍走原 factory
  - push bar 后仍能触发 `on_quote()` / `on_bar()`
- `execution.py` 单元测试
  - `DryRunRebalanceExecutor`
  - `TradeAccountState` 的状态推进
- `trade_accounts/futu.py` 生命周期测试
  - `close()`
  - reconnect 时不会在持锁状态下 join poll thread

## 7. 一句话结论

当前最准确的结论不是“mock 还没拆”，而是：

```text
基础拆分已经完成：
broker.py -> quote_brokers/ + history_providers/ + trade_accounts/
engine.py -> execution.py

下一阶段更应该做：
细拆 mock.py 内部职责
-> 抽 account state store
-> 细拆 execution.py
-> 再瘦身 engine.apply_config()
```
