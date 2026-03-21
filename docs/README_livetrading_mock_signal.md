# 实时行情 Mock 触发买卖点说明

这份文档说明如何在 `FutuOpenD` 没有美股实时行情订阅的情况下，用仓库里已经支持的 `mock` 实时行情入口，手工推送分钟 K 线，并让 `livetrading` 打出 `DRY_RUN_ORDER` 的买卖日志。

文档边界：

- 本文只负责“怎么运行 mock、怎么推 bar、怎么复现 BUY / SELL”
- 如果你要看运行链路，见 [README_livetrading_sequence.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_sequence.md)
- 如果你要看代码拆分和后续重构，见 [README_livetrading_mock_refactor.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_mock_refactor.md)
- 如果你要看补齐真实下单的设计方案，见 [README_livetrading_real_order_plan.md](/Users/sean/workspace/backtest-feature-livetrading-startup/docs/README_livetrading_real_order_plan.md)

适用场景：

- `realtime_broker` 不能再走 `127.0.0.1:11111` 的 Futu 美股实时订阅。
- 你仍然希望保留当前 `dual_momentum` 的实盘 dry-run 流程。
- 你希望通过手工构造分钟 K，验证信号、调仓和 dry-run 下单日志。

## 1. 先理解触发条件

当前实时策略不是“来一根分钟 bar 就立刻买卖”，而是：

- 策略名：`dual_momentum`
- 触发时机：`新交易日的第一根分钟 bar`
- 信号依据：`上一交易日` 及更早的已完成日线

也就是说：

- 同一天内连续推很多分钟 bar，通常不会重复触发调仓。
- 真正触发信号的是“日期切换”这一刻。
- 如果你想稳定触发买点/卖点，不能只随便推一条 `09:30`，还要让“上一交易日的收盘结构”满足策略选股条件。

## 2. 运行前提

### 2.1 行情配置改成 mock

用仓库里的样例配置：

- [config/livetrading.quote.mock.sample.json](/Users/sean/workspace/backtest-feature-livetrading-startup/config/livetrading.quote.mock.sample.json)

核心字段是：

```json
{
  "realtime_broker": {
    "type": "mock",
    "host": "127.0.0.1",
    "port": 19111,
    "market": "US",
    "extended_time": false
  }
}
```

`history_broker` 建议显式配成 `polygon`，因为策略 warm-up 用的是日线，不是实时推送；如果你想强制走 OpenD 日线，也可以改成 `futu`。

### 2.2 账户侧必须已经有资金和持仓状态

要看到 `DRY_RUN_ORDER`，引擎里必须先有：

- `available_funds` / `shadow_cash`
- `positions` / `shadow_positions`

否则只会出现：

```text
REBALANCE_SKIPPED ... reason=no_portfolio_value
```

如果你用真实 Futu 交易账户配置，启动后先确认日志里已经出现账户/持仓同步。如果没有这些状态，策略即使出信号，也不会打出 dry-run 下单。

### 2.3 目标股票必须先有参考价

引擎下 dry-run 单时，需要每个目标股票都有最新参考价。参考价来自：

- 最新 `quote`
- 或最新分钟 `bar.close`

所以在真正触发调仓前，最好先给股票池里的目标股票各推一条 bar，确保它们都有价格。

## 3. 启动方式

```bash
./.venv/bin/python livetrading.py \
  --quote-config config/livetrading.quote.mock.sample.json \
  --trade-config config/livetrading.trade_accounts.sample.json
```

启动后，`mock` 行情入口会监听：

```text
http://127.0.0.1:19111/push
```

健康检查：

```bash
curl http://127.0.0.1:19111/health
```

## 4. 手工推送格式

单条 bar：

```bash
curl -X POST http://127.0.0.1:19111/push \
  -H 'Content-Type: application/json' \
  -d '{
    "code": "US.AAPL",
    "time_key": "2026-03-13 09:30:00",
    "open": 130.0,
    "close": 130.0,
    "high": 130.0,
    "low": 130.0,
    "volume": 5000
  }'
```

批量 bar：

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

`mock` 收到后会做两件事：

- 先合成一条 `quote`
- 再推对应的分钟 `bar`

这样既能更新参考价，也能驱动策略状态机。

## 5. 怎样稳定触发 BUY / SELL

这是关键。

为了稳定复现，必须满足两层条件：

1. `上一交易日` 的已完成日线结果，要让策略确实想调仓。
2. `当前交易日第一根分钟 bar` 要把这个调仓信号触发出来。

### 5.1 当前策略的最小可控思路

仓库当前默认 live 策略是 `dual_momentum`。如果你想用最少的股票验证，建议只保留两只：

- `US.AAPL`
- `US.MSFT`

并使用类似下面这组参数：

```json
{
  "lookback_days": 1,
  "long_lookback_days": 2,
  "long_lookback_weight": 0.0,
  "top_n": 1,
  "volume_window": 1,
  "min_volume_ratio": 1.0,
  "market_filter_window": 2,
  "volatility_window": 2,
  "target_annual_vol": 999.0,
  "max_gross_exposure": 1.0,
  "rebalance_band_pct": 0.0
}
```

这组参数的目的不是实盘最优，而是让“受控触发”更直接：

- 只看 1 天相对强弱
- 只持有最强的 1 只
- 不让调仓带把小变化吞掉

### 5.2 受控验证时的日线前提

要精确复现买卖，最好保证 warm-up 日线是可控的。

我验证时使用的受控日线逻辑是：

- 截至 `2026-03-12`
- `US.AAPL` 最近两天收盘：`100 -> 100`
- `US.MSFT` 最近两天收盘：`100 -> 120`

这样在 `2026-03-13` 开盘第一根分钟 bar 到来时，策略会认为：

- `MSFT` 比 `AAPL` 更强
- 目标仓位应该切到 `US.MSFT`

然后再让 `2026-03-13` 这一天的“日线收盘结构”变成：

- `US.AAPL`：`100 -> 130`
- `US.MSFT`：`120 -> 110`

这样到 `2026-03-14` 开盘第一根分钟 bar 到来时，策略会反过来认为：

- `AAPL` 更强
- 目标仓位应该从 `US.MSFT` 切到 `US.AAPL`

## 6. 一套实际可复现的推送顺序

下面这组请求，是我已经实际验证过能打出 `BUY -> SELL -> BUY` dry-run 日志的一组顺序。

注意：这组顺序默认你已经满足了上面的“受控日线前提”。如果你仍然直接使用真实 Futu 日线 warm-up，那么最终信号方向会受到真实历史数据影响，不保证和下面完全一样。

### 6.1 先给股票池补参考价

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

作用：

- 让引擎里 `AAPL` / `MSFT` 都先有价格
- 还不会触发调仓，因为还没有切到新交易日

### 6.2 推新交易日第一根 bar，触发第一次 BUY

```bash
curl -X POST http://127.0.0.1:19111/push \
  -H 'Content-Type: application/json' \
  -d '{
    "code": "US.AAPL",
    "time_key": "2026-03-13 09:30:00",
    "close": 130.0,
    "volume": 5000
  }'
```

这里的关键不是推了 `AAPL` 本身，而是：

- 时间从 `2026-03-12` 切到了 `2026-03-13`
- 状态机开始用“截至 `2026-03-12` 的已完成日线”计算信号

在上面的受控前提下，此时会打出类似：

```text
DRY_RUN_REBALANCE ... (targets=US.MSFT)
DRY_RUN_ORDER ... action=BUY code=US.MSFT ...
```

### 6.3 改写当天的日线结构

为了让下一次开盘切仓到 `AAPL`，需要把 `2026-03-13` 这一天的最终收盘结构改成“`AAPL` 强、`MSFT` 弱”。

最少只需要补一条 `MSFT` 的收盘 bar：

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

这时日内状态会变成：

- `AAPL` 当天 close 仍然是 `130.0`
- `MSFT` 当天 close 变成 `110.0`

### 6.4 再推下一交易日第一根 bar，触发 SELL + BUY

```bash
curl -X POST http://127.0.0.1:19111/push \
  -H 'Content-Type: application/json' \
  -d '{
    "code": "US.AAPL",
    "time_key": "2026-03-14 09:30:00",
    "close": 131.0,
    "volume": 6000
  }'
```

此时会用“截至 `2026-03-13` 的已完成日线”重新计算，日志里会出现：

```text
DRY_RUN_REBALANCE ... (targets=US.AAPL)
DRY_RUN_ORDER ... action=SELL code=US.MSFT ...
DRY_RUN_ORDER ... action=BUY code=US.AAPL ...
```

## 7. 我实际验证到的日志样例

下面是我实际跑出来的关键日志：

```text
INFO DRY_RUN_REBALANCE account_id=sim_primary signal_time=2026-03-13 09:30:00 reason=dual_momentum rebalance using completed daily data through 2026-03-12 (targets=US.MSFT) target_weights={'US.MSFT': 1.0}
INFO DRY_RUN_ORDER account_id=sim_primary action=BUY code=US.MSFT qty=83 price=120.0000 signal_time=2026-03-13 09:30:00 ...

INFO DRY_RUN_REBALANCE account_id=sim_primary signal_time=2026-03-14 09:30:00 reason=dual_momentum rebalance using completed daily data through 2026-03-13 (targets=US.AAPL) target_weights={'US.AAPL': 1.0}
INFO DRY_RUN_ORDER account_id=sim_primary action=SELL code=US.MSFT qty=83 price=110.0000 signal_time=2026-03-14 09:30:00 ...
INFO DRY_RUN_ORDER account_id=sim_primary action=BUY code=US.AAPL qty=69 price=131.0000 signal_time=2026-03-14 09:30:00 ...
```

## 8. 为什么你照着推了却没下单

常见原因只有几类：

- 没有账户资金状态
  - 现象：`REBALANCE_SKIPPED ... reason=no_portfolio_value`
- 目标股票没有参考价
  - 现象：有 `DRY_RUN_REBALANCE`，但没有对应股票的 `DRY_RUN_ORDER`
- 推送时间没有跨交易日
  - 现象：同一天推很多 bar，都不出新调仓
- 实际 warm-up 日线不是受控的
  - 现象：日志有调仓，但目标不是你预期的那只股票
- 市场过滤变成 risk-off
  - 现象：`DRY_RUN_REBALANCE` 的 `target_weights={}`，策略切到现金

## 9. 最重要的一句

如果你只是想“证明整条链路能打出买卖单日志”，那就要把问题拆成两层：

- `realtime_broker` 用 `mock` 解决实时订阅问题
- `history_broker` / warm-up 日线要尽量可控，否则买卖方向仍会受真实历史数据影响

也就是说：

- `mock` 负责“把实时事件送进来”
- `受控日线` 负责“保证策略一定想买/卖你指定的股票”

只靠随便推几根分钟 K，通常不够稳定复现买卖点。
