# 不接真实行情，也能稳定看到一轮“先买、再卖、再买”的模拟下单日志

这份文档只做一件事：不用外部实时行情和真实交易账户，也能按固定步骤稳定看到一轮“先买、再卖、再买”的模拟下单日志。

这里先把名词说清楚：

- `DRY_RUN_ORDER` = 模拟下单日志
- 意思是：程序判断“这里应该买/卖”，并把结果打印出来
- 它不会真的向券商发单，也不会动真实账户



## 1. 这次要用哪几份配置

请使用下面四份文件：

- [config/livetrading.quote.mock.sample.json](../config/livetrading.quote.mock.sample.json)
- [config/livetrading.history.local.mock_signal.sample.json](../config/livetrading.history.local.mock_signal.sample.json)
- [config/livetrading.pool.mock_signal.sample.json](../config/livetrading.pool.mock_signal.sample.json)
- [config/livetrading.trade_account.mock.sample.json](../config/livetrading.trade_account.mock.sample.json)

其中：

- `quote` 仍然使用仓库现成的 `mock` 行情入口
- `trade_account` 仍然使用仓库现成的 `mock` 账户基线，但本样例显式配置成 `order_session=ETH`
- `history` 改成读取仓库内置的受控日线夹具目录 [config/livetrading_mock_signal_kline_day](../config/livetrading_mock_signal_kline_day)
- `pool` 改成只保留 `US.AAPL` / `US.MSFT` 两只股票，并把 dual momentum 参数缩短到可控窗口

这组专用样例的目的不是模拟实盘，而是让本文里的推送顺序可以稳定复现同样的订单日志。

## 2. 启动方式

```bash
./.venv/bin/python livetrading.py \
  --quote-config config/livetrading.quote.mock.sample.json \
  --history-config config/livetrading.history.local.mock_signal.sample.json \
  --pool-config config/livetrading.pool.mock_signal.sample.json \
  --trade-config config/livetrading.trade_account.mock.sample.json
```

启动后你应该先看到：

- `mock realtime quote broker listening at http://127.0.0.1:19111/push`
- `warm-up loaded from kline_day code=US.AAPL rows=3`
- `warm-up loaded from kline_day code=US.MSFT rows=3`
- `account=mock_primary mock account connected cash=100000.0 positions={}`

不同日志开关下，中间还可能额外看到：

- `ACCOUNT ...`
- `POSITIONS ...`
- `CONFIG_APPLIED ...`

健康检查：

```bash
curl http://127.0.0.1:19111/health
```

正常会返回：

```json
{"status": "ok", "codes": ["US.AAPL", "US.MSFT"]}
```

## 3. 为什么这组样例一定能出单

这组受控日线夹具的已完成日线是：

- `2026-03-10`：`AAPL=100`，`MSFT=100`
- `2026-03-11`：`AAPL=100`，`MSFT=100`
- `2026-03-12`：`AAPL=100`，`MSFT=120`

所以当 `2026-03-13` 的第一根分钟 bar 到来时，策略会基于“截至 `2026-03-12` 的已完成日线”判断：

- `MSFT` 比 `AAPL` 强
- 市场过滤是 risk-on
- 第一笔目标仓位应该买入 `US.MSFT`

随后，只要把 `2026-03-13` 这一天的收盘结构改成：

- `AAPL=130`
- `MSFT=110`

那么到了下一个交易日 `2026-03-16` 的第一根分钟 bar，策略就会把目标从 `US.MSFT` 切到 `US.AAPL`。

这里特地写明一下：

- `2026-03-13` 是 Friday
- `2026-03-14` / `2026-03-15` 是周末，不是交易日
- 所以第二次换日触发必须推到 `2026-03-16`

## 4. 逐步推送顺序

当前 live 策略不是“来一根分钟 bar 就立刻买卖”，而是：

- 只在`新交易日的第一根分钟 bar`触发一次调仓
- 信号依据是`上一交易日`及更早的已完成日线

补充一条当前实现细节：

- `mock` 行情入口现在也会按市场时区和 quote 订阅时段过滤 bar
- 本文这组样例通过 `trade_account.execution.order_session=ETH` 派生出 extended-time 订阅
- 所以像 `2026-03-13 04:00:00` 和 `2026-03-16 04:00:00` 这样的盘前 push 会被接收
- 它们都可以作为各自交易日第一根进入策略的分钟 bar
- 但周末时间例如 `2026-03-14 04:00:00` 会在 `mock` broker 入口先被拒绝

因此必须按下面顺序推送。

### 4.1 先给目标股票补参考价

```bash
curl -X POST http://127.0.0.1:19111/push \
  -H 'Content-Type: application/json' \
  -d '{
    "bars": [
      {"code": "US.AAPL", "time_key": "2026-03-12 15:59:00", "close": 100.0, "volume": 1000},
      {"code": "US.MSFT", "time_key": "2026-03-12 15:59:00", "close": 120.0, "volume": 1000}
    ]
  }'
```

这一步只更新参考价，不触发调仓。

### 4.2 推下一交易日第一根 bar，触发第一次 BUY

```bash
curl -X POST http://127.0.0.1:19111/push \
  -H 'Content-Type: application/json' \
  -d '{
    "code": "US.AAPL",
    "time_key": "2026-03-13 04:00:00",
    "close": 130.0,
    "volume": 5000
  }'
```

这里的关键不是推了 `AAPL` 本身，而是交易日从 `2026-03-12` 切到了 `2026-03-13`。

此时应该出现：

```text
INFO DRY_RUN_REBALANCE account_id=mock_primary signal_time=2026-03-13 04:00:00 reason=dual_momentum rebalance using completed daily data through 2026-03-12 (targets=US.MSFT) target_weights={'US.MSFT': 1.0}
INFO DRY_RUN_ORDER account_id=mock_primary action=BUY code=US.MSFT ...
```

### 4.3 改写 `2026-03-13` 这一天的最终收盘结构

```bash
curl -X POST http://127.0.0.1:19111/push \
  -H 'Content-Type: application/json' \
  -d '{
    "code": "US.MSFT",
    "time_key": "2026-03-13 15:59:00",
    "close": 110.0,
    "volume": 5000
  }'
```

推完后，日内状态会变成：

- `AAPL` 当天 close 仍然是 `130.0`
- `MSFT` 当天 close 变成 `110.0`

### 4.4 再推下一个交易日第一根 bar，触发 SELL + BUY

```bash
curl -X POST http://127.0.0.1:19111/push \
  -H 'Content-Type: application/json' \
  -d '{
    "code": "US.AAPL",
    "time_key": "2026-03-16 04:00:00",
    "close": 131.0,
    "volume": 6000
  }'
```

此时应该出现：

```text
INFO DRY_RUN_REBALANCE account_id=mock_primary signal_time=2026-03-16 04:00:00 reason=dual_momentum rebalance using completed daily data through 2026-03-13 (targets=US.AAPL) target_weights={'US.AAPL': 1.0}
INFO DRY_RUN_ORDER account_id=mock_primary action=SELL code=US.MSFT ...
INFO DRY_RUN_ORDER account_id=mock_primary action=BUY code=US.AAPL ...
```


## 5. 背后代码调用链详细解读

这一节专门解释：你照着本文第4章节推送股票报价时，程序内部到底经过了哪些代码。

### 5.1 启动阶段：四份配置如何变成运行中的 mock 系统

入口很短：

- [livetrading.py](../livetrading.py)
- [livetrading/cli.py](../livetrading/cli.py)

真正的装配发生在：

- [livetrading/engine.py](../livetrading/engine.py)
- [livetrading/config_applier.py](../livetrading/config_applier.py)

启动顺序可以概括成下面几步：

1. `LiveTradingEngine.run()` 读取四份 JSON 配置。
2. `RuntimeConfigApplier._apply_realtime_config()` 创建 [livetrading/quote_brokers/mock.py](../livetrading/quote_brokers/mock.py) 里的 `MockRealtimeQuoteClient`，所以你会看到：
   - `mock realtime quote broker listening at http://127.0.0.1:19111/push`
3. `RuntimeConfigApplier._apply_history_provider()` 创建 [livetrading/history_providers/local.py](../livetrading/history_providers/local.py) 里的 `LocalDataDailyHistoryProvider`。
4. `RuntimeConfigApplier._prepare_strategy_context()` 调用这个 provider，从：
   - [config/livetrading.history.local.mock_signal.sample.json](../config/livetrading.history.local.mock_signal.sample.json)
   - [config/livetrading_mock_signal_kline_day](../config/livetrading_mock_signal_kline_day)
   读取 warm-up 日线。
5. `RuntimeConfigApplier._apply_trade_account_config()` 创建 `MockTradeAccountClient` 并调用 `connect()`，把 [config/livetrading.trade_account.mock.sample.json](../config/livetrading.trade_account.mock.sample.json) 里的初始现金和初始持仓推给引擎，所以你会看到：
   - `ACCOUNT ...`
   - `POSITIONS ...`
   - `account=mock_primary mock account connected cash=100000.0 positions={}`
6. `RuntimeConfigApplier._commit_strategy_context()` 调用 [livetrading/pool_strategies.py](../livetrading/pool_strategies.py) 里的 `DualMomentumPoolStrategy.bootstrap()`。
7. `DualMomentumPoolStrategy.bootstrap()` 再把 warm-up 日线喂给 [strategy/dual_momentum_state.py](../strategy/dual_momentum_state.py) 里的 `DualMomentumDailyState.bootstrap()`。

这个阶段最关键的状态是：

- `DualMomentumDailyState` 会把 warm-up 最后一日记成“当前交易日基线”
- 对本文样例，这个基线就是 `2026-03-12`
- 所以后面第一次收到 `2026-03-13 04:00:00` 时，状态机会认定“换日了”

### 5.2 你执行 `curl /push` 时，代码如何流动

`/push` 的 HTTP 入口在：

- [livetrading/quote_brokers/mock.py](../livetrading/quote_brokers/mock.py)

实际调用顺序是：

1. `MockRealtimeQuoteClient._build_server()` 里构建出来的 HTTP handler 接住 `POST /push`
2. `push_bars()` 解析单条或批量 `bars`
3. `push_bar()` 先把 payload 归一化成统一 bar 结构
4. `push_bar()` 先回调 `QuoteBrokerEventSinkAdapter.on_quote(...)`，把最新行情写进 `latest_quotes`
5. `push_bar()` 再回调 `QuoteBrokerEventSinkAdapter.on_bar(...)`
6. `QuoteBrokerEventSinkAdapter.on_bar()` 把 `close` 写进运行时参考价缓存 `latest_bar_prices`
7. `QuoteBrokerEventSinkAdapter.on_bar()` 调用 `pool_strategy.on_bar(...)`
8. `DualMomentumPoolStrategy.on_bar()` 把分钟 bar 继续交给 `DualMomentumDailyState.on_bar(...)`
9. 如果 `pool_strategy.on_bar(...)` 产出了 `PortfolioRebalanceDecision`，`QuoteBrokerEventSinkAdapter.on_bar()` 会继续调用 `PortfolioCoordinator.execute_portfolio_rebalance(...)`
10. `PortfolioCoordinator.execute_portfolio_rebalance(...)` 会先从 `LiveTradingRuntimeState` 收集运行时参考价，再把组合目标交给 `RebalancePlanner` 和对应执行器，最终决定是否打印 `DRY_RUN_ORDER`

这里有一个很容易忽略的点：

- 执行层会通过 `LiveTradingRuntimeState.resolve_reference_price()` 优先读 `latest_quotes`，缺失时再回退到 `latest_bar_prices`
- `DualMomentumDailyState` 维护的是“策略层已完成日线窗口”
- 这两套状态都会被同一次 `push` 更新，但用途不同
- 但在进入这两套状态之前，`mock` broker 还会先按市场时区和 session 规则做一次准入判断

### 5.3 为什么 `2026-03-12 15:59` 不出单，而 `2026-03-13 04:00` 会出单

关键逻辑在：

- [strategy/dual_momentum_state.py](../strategy/dual_momentum_state.py)
- [livetrading/quote_brokers/mock.py](../livetrading/quote_brokers/mock.py)
- [livetrading/market_hours.py](../livetrading/market_hours.py)

要分两层看：

第一层是 `mock` 行情入口的 session 准入：

- 当前这组样例配置派生出来的是 extended-time 订阅
- 所以 `04:00` 盘前 bar 会进入引擎
- 它就是这一天第一根会被接收的 bar

第二层是状态机内部的 `trade_date` 归属：

- 不再直接取原始 `timestamp.date()`
- 而是先按市场时区换算，再得到市场本地 `trade_date`
- 这样像 `2026-03-13 00:30:00+00:00` 这种时间，换算到纽约其实还是 `2026-03-12 19:30:00`
- 状态机不会把它误判成 `2026-03-13` 的新交易日

`DualMomentumDailyState.on_bar()` 的顺序不是“先更新 bar，再算信号”，而是：

1. 先看这根分钟 bar 的 `trade_date` 有没有跨到新交易日
2. 如果跨日，先把 `< 当前 trade_date` 的所有日线拼成 `CompletedDailyFrames`
3. 然后才把这根 bar 合并进当天日线

因此：

- 你推 `2026-03-12 15:59` 时，`trade_date` 仍然是 `2026-03-12`
- 它只会更新当天聚合中的 `close/volume`
- 不会触发 `CompletedDailyFrames`
- 所以不会出调仓信号

但当你推 `2026-03-13 04:00` 时：

- `trade_date` 从 `2026-03-12` 跳到了 `2026-03-13`
- 状态机会先吐出“截至 `2026-03-12` 的已完成日线窗口”
- 这份窗口随后被拿去算 signal
- `2026-03-13 04:00` 这根 bar 本身不会进入这次 signal 的日线窗口

这就是本文一直强调的那句：

- live 策略是在“新交易日第一根分钟 bar 到来时”
- 使用“上一交易日及更早的已完成日线”
- 计算一次调仓

### 5.4 `mock_signal` 这组参数在本例中是什么意思

策略配置在：

- [config/livetrading.pool.mock_signal.sample.json](../config/livetrading.pool.mock_signal.sample.json)
- [strategy/dual_momentum.py](../strategy/dual_momentum.py)

在本文样例里，最关键的参数是：

- `lookback_days=1`
  - 只比较最近两个已完成交易日的涨跌幅
- `long_lookback_days=2`
  - 保留长周期字段，但因为 `long_lookback_weight=0.0`，这次样例里实际上不参与打分
- `top_n=1`
  - 只保留最强的一只股票
- `volume_window=1`
  - 当天成交量只和前一天比
- `min_volume_ratio=1.0`
  - 不额外抬高放量门槛，避免样例里因为成交量过滤把信号吃掉
- `market_filter_window=2`
  - 用最近两天的股票池均值和两日均线做 risk-on / risk-off 判断
- `rebalance_band_pct=0.0`
  - 不设置调仓带，只要目标变了就立即调仓
- `target_annual_vol=999.0`
  - 基本等于关闭波动率缩仓，让 `gross_exposure` 保持在 `1.0`

所以在 `2026-03-13 04:00` 这次计算里，本质上就是：

- 用 `2026-03-11 -> 2026-03-12` 的变化看谁更强
- `MSFT` 从 `100 -> 120`
- `AAPL` 从 `100 -> 100`
- 因而选出 `US.MSFT`

### 5.5 为什么 4.1 必须先给 `AAPL/MSFT` 补参考价

这一点不是策略层要求的，而是执行层要求的。

相关代码在：

- [livetrading/runtime_state.py](../livetrading/runtime_state.py)
- [livetrading/portfolio.py](../livetrading/portfolio.py)
- [livetrading/execution.py](../livetrading/execution.py)

执行层下单时，`RebalancePlanner.build_account_plan()` 需要把“目标权重”换算成“目标股数”。这一步必须知道每只股票的当前参考价。

而这些参考价只来自运行时收到过的：

- `latest_quotes`
- `latest_bar_prices`

不会回头去 warm-up 日线里取。

所以如果你没有先执行 4.1：

- 策略层仍然可能已经判断出“应该买 `US.MSFT`”
- 但执行层手里没有 `US.MSFT` 的最新参考价
- `RebalancePlanner` 就无法把 `1.0` 的目标权重换成具体买多少股
- 结果就可能只有 `DRY_RUN_REBALANCE`，没有后续 `DRY_RUN_ORDER`

这也是为什么 4.1 要一次把：

- `US.AAPL 2026-03-12 15:59`
- `US.MSFT 2026-03-12 15:59`

两只股票的参考价都补上。

### 5.6 为什么第二天会出现 `SELL MSFT + BUY AAPL`

相关代码路径是：

- [strategy/dual_momentum_state.py](../strategy/dual_momentum_state.py)
- [strategy/dual_momentum.py](../strategy/dual_momentum.py)
- [livetrading/portfolio.py](../livetrading/portfolio.py)
- [livetrading/execution.py](../livetrading/execution.py)

当你执行 4.3 时：

- `US.MSFT 2026-03-13 15:59 close=110`

这会改写 `MSFT` 这一天在状态机里的最终 `close`

而 `AAPL` 这一天因为之前已经推过：

- `US.AAPL 2026-03-13 04:00 close=130`

如果你不再给 `AAPL` 推新的当日 bar，那么状态机里 `AAPL` 这一天的最终 `close` 就还是 `130`

到了 4.4 再推 `2026-03-16 04:00` 时：

1. 状态机发现进入 `2026-03-16`
2. 吐出截至 `2026-03-13` 的已完成日线窗口
3. `build_dual_momentum_signal()` 用 `2026-03-12 -> 2026-03-13` 的变化重新排名
4. 现在 `AAPL=130`，`MSFT=110`，最强标的切到 `US.AAPL`
5. `PortfolioCoordinator.execute_portfolio_rebalance()` 开始规划账户级调仓
6. `RebalancePlanner.build_account_plan()` 看到 mock 账户的 `shadow_positions` 里已经持有前一天买入的 `US.MSFT`
7. 因为目标从 `MSFT` 切成了 `AAPL`，于是生成：
   - `SELL US.MSFT`
   - `BUY US.AAPL`
8. `MockExecutor.execute_plan()` 按“先卖后买”的顺序推进本地 `shadow_cash / shadow_positions`
9. 最终打印两条 `DRY_RUN_ORDER`

### 5.7 如果你要直接跟代码一起读，建议按这个顺序打开文件

1. [docs/README_livetrading_mock_signal.md](../docs/README_livetrading_mock_signal.md)
2. [livetrading/quote_brokers/mock.py](../livetrading/quote_brokers/mock.py)
3. [livetrading/event_sinks.py](../livetrading/event_sinks.py)
4. [strategy/dual_momentum_state.py](../strategy/dual_momentum_state.py)
5. [livetrading/pool_strategies.py](../livetrading/pool_strategies.py)
6. [strategy/dual_momentum.py](../strategy/dual_momentum.py)
7. [livetrading/portfolio.py](../livetrading/portfolio.py)
8. [livetrading/execution.py](../livetrading/execution.py)

按这个顺序读，基本就能把本文里的：

- 为什么第一天买 `MSFT`
- 为什么第二天卖 `MSFT` 再买 `AAPL`
- 为什么必须先补参考价

三件事一次看明白。
