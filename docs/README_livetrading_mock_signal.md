# 实时行情 Mock 稳定复现 `DRY_RUN_ORDER`

这份文档只解决一件事：在不依赖外部实时行情和真实交易账户的情况下，稳定复现 `BUY -> SELL -> BUY` 的 `DRY_RUN_ORDER` 日志。

先说最重要的一句：

- 直接使用 [config/livetrading.pool.sample.json](../config/livetrading.pool.sample.json) 和现有 `.kline_day/`，只能保证程序能启动。
- 它**不能**保证一定打出 `DRY_RUN_ORDER`。
- 如果你只是从文档里复制命令想立刻复现买卖单，请使用本文下面这组**专用样例配置和专用本地日线夹具**。

如果你要看运行链路，见 [README_livetrading_sequence.md](../docs/README_livetrading_sequence.md)。
如果你要看当前执行层怎么分成 `mock / futu_simulate / futu_real`，见 [README_livetrading_real_order_plan.md](../docs/README_livetrading_real_order_plan.md)。

## 1. 这次要用哪几份配置

请使用下面四份文件：

- [config/livetrading.quote.mock.sample.json](../config/livetrading.quote.mock.sample.json)
- [config/livetrading.history.local.mock_signal.sample.json](../config/livetrading.history.local.mock_signal.sample.json)
- [config/livetrading.pool.mock_signal.sample.json](../config/livetrading.pool.mock_signal.sample.json)
- [config/livetrading.trade_account.mock.sample.json](../config/livetrading.trade_account.mock.sample.json)

其中：

- `quote` 仍然使用仓库现成的 `mock` 行情入口
- `trade_account` 仍然使用仓库现成的 `mock` 账户基线
- `history` 改成读取仓库内置的受控日线夹具目录 [livetrading_mock_signal_kline_day](./livetrading_mock_signal_kline_day)
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

健康检查：

```bash
curl http://127.0.0.1:19111/health
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

那么到了 `2026-03-14` 的第一根分钟 bar，策略就会把目标从 `US.MSFT` 切到 `US.AAPL`。

## 4. 逐步推送顺序

当前 live 策略不是“来一根分钟 bar 就立刻买卖”，而是：

- 只在`新交易日的第一根分钟 bar`触发一次调仓
- 信号依据是`上一交易日`及更早的已完成日线

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
    "time_key": "2026-03-13 09:30:00",
    "close": 130.0,
    "volume": 5000
  }'
```

这里的关键不是推了 `AAPL` 本身，而是交易日从 `2026-03-12` 切到了 `2026-03-13`。

此时应该出现：

```text
INFO DRY_RUN_REBALANCE account_id=mock_primary signal_time=2026-03-13 09:30:00 reason=dual_momentum rebalance using completed daily data through 2026-03-12 (targets=US.MSFT) target_weights={'US.MSFT': 1.0}
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

### 4.4 再推下一交易日第一根 bar，触发 SELL + BUY

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

此时应该出现：

```text
INFO DRY_RUN_REBALANCE account_id=mock_primary signal_time=2026-03-14 09:30:00 reason=dual_momentum rebalance using completed daily data through 2026-03-13 (targets=US.AAPL) target_weights={'US.AAPL': 1.0}
INFO DRY_RUN_ORDER account_id=mock_primary action=SELL code=US.MSFT ...
INFO DRY_RUN_ORDER account_id=mock_primary action=BUY code=US.AAPL ...
```

## 5. 如果你改回默认样例配置，为什么结果会不一样

如果你改回下面这组文件：

- [config/livetrading.history.local.sample.json](../config/livetrading.history.local.sample.json)
- [config/livetrading.pool.sample.json](../config/livetrading.pool.sample.json)

那么日志很可能和本文不同，这是预期行为，不是程序坏了。

原因有三点：

- 默认 `pool.sample` 使用 5 只股票和更长的参数窗口，不是本文这组可控的双股票短窗口。
- 默认 `history.local.sample` 会读取你当前工作区里的 `.kline_day/`，不会自动生成本文假设的受控日线。
- dual momentum 还有市场过滤；即使有候选股票，只要市场过滤变成 risk-off，结果也会是 `target_weights={}`，日志里表现为 `(targets=CASH)`。

也就是说：

- `sample` 配置适合验证“程序是否能启动、mock 链路是否通”
- `mock_signal` 专用配置适合验证“是否能稳定打出 dry-run 买卖单”

## 6. 常见问题

- 现象：只有 `DRY_RUN_REBALANCE`，没有 `DRY_RUN_ORDER`
  - 先确认你用的是本文这组 `mock_signal` 专用配置，而不是默认 `pool.sample`
  - 再确认你是否先执行了“4.1 先给目标股票补参考价”
- 现象：同一天推很多 bar，只有第一次触发调仓
  - 这是正常行为；策略只在新的交易日第一次进入时触发一次
- 现象：日志里出现 `(targets=CASH)` 和 `target_weights={}`
  - 这表示策略最终切到了现金，常见原因是你没有使用本文的受控历史数据，或者你切回了默认样例配置

## 7. 最重要的一句

如果你的目标是“从文档直接复制命令，然后稳定看到 `DRY_RUN_ORDER`”，请不要使用默认的 `pool.sample` 和默认 `.kline_day/`。

请直接使用本文这组：

- [config/livetrading.quote.mock.sample.json](../config/livetrading.quote.mock.sample.json)
- [config/livetrading.history.local.mock_signal.sample.json](../config/livetrading.history.local.mock_signal.sample.json)
- [config/livetrading.pool.mock_signal.sample.json](../config/livetrading.pool.mock_signal.sample.json)
- [config/livetrading.trade_account.mock.sample.json](../config/livetrading.trade_account.mock.sample.json)

这组配置和仓库内置的受控日线夹具是配套的，目的就是让本文的推送顺序可以直接复现出买卖单日志。
