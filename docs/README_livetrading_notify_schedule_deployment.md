# livetrading 定时通知模式部署说明

这份文档对应已经实现的 `schedule_us + notify` 部署模式。

这套模式的语义是：

- 不订阅实时 `QUOTE`
- 不订阅实时 `K_1M`
- 不连接 Futu 账户
- 在每个美股交易日 `09:30 America/New_York` 触发一次
- 启动时不抢先做 warm-up
- 只有触发时才强制刷新 warm-up 日线
- 运行股票池策略并通知“当前股票池推荐买谁”或 `CASH`

## 1. 适用范围

当前最适合：

- `dual_momentum`
- 只想收到人工提醒，不想自动下单
- 不需要系统告诉你“卖出哪个旧持仓”

当前不适合：

- 需要账户持仓差异提醒
- 需要建议股数
- 需要 SMTP over SSL(465)；当前实现是标准 SMTP + STARTTLS

## 2. 需要的配置文件

建议直接使用这几个样例：

- quote: [config/livetrading.quote.schedule_us.sample.json](/Users/sean/workspace/backtest-feature-livetrading-startup/config/livetrading.quote.schedule_us.sample.json)
- history: [config/livetrading.history.local.sample.json](/Users/sean/workspace/backtest-feature-livetrading-startup/config/livetrading.history.local.sample.json) 或 [config/livetrading.history.polygon.sample.json](/Users/sean/workspace/backtest-feature-livetrading-startup/config/livetrading.history.polygon.sample.json)
- pool: [config/livetrading.pool.sample.json](/Users/sean/workspace/backtest-feature-livetrading-startup/config/livetrading.pool.sample.json)
- trade/notify: [config/livetrading.trade_account.notify.sample.json](/Users/sean/workspace/backtest-feature-livetrading-startup/config/livetrading.trade_account.notify.sample.json)

建议把 `quote / history / pool / trade` 四份文件拆开维护，不要把 `history_broker` 再塞回 `quote` 里。

## 3. 最小修改项

你至少需要改这几处：

- [config/livetrading.pool.sample.json](/Users/sean/workspace/backtest-feature-livetrading-startup/config/livetrading.pool.sample.json)
  - 改成你自己的股票池和 `dual_momentum` 参数
- [config/livetrading.trade_account.notify.sample.json](/Users/sean/workspace/backtest-feature-livetrading-startup/config/livetrading.trade_account.notify.sample.json)
  - 改 `notification.email.smtp_host`
  - 改 `notification.email.smtp_port`
  - 改 `notification.email.username`
  - 改 `notification.email.from`
  - 改 `notification.email.to`
  - 改 `notification.email.subject_prefix`

如果你不想发邮件，只想打印日志：

- 把 `notification.email.enabled` 改成 `false`

## 4. 邮件密码配置

最省事的写法是直接在配置里写：

```json
"password": "your-smtp-password"
```

如果你更在意把密码和配置文件分开，再改成环境变量写法：

```json
"password_env": "LIVETRADING_NOTIFY_EMAIL_PASSWORD"
```

启动前先设置：

```bash
export LIVETRADING_NOTIFY_EMAIL_PASSWORD='your-smtp-password'
```

两种方式二选一即可。

如果 SMTP 不需要认证：

- 可以不写 `username`
- 也可以不写 `password`
- 也可以不写 `password_env`

## 5. 启动命令

```bash
./.venv/bin/python -m livetrading \
  --quote-config config/livetrading.quote.schedule_us.sample.json \
  --history-config config/livetrading.history.local.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_account.notify.sample.json
```

如果你想临时改成开盘前触发，例如美东 `09:20`：

```bash
./.venv/bin/python -m livetrading \
  --quote-config config/livetrading.quote.schedule_us.sample.json \
  --history-config config/livetrading.history.local.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_account.notify.sample.json \
  --schedule-trigger-time 09:20
```

如果你想从 Polygon 拉 warm-up：

```bash
./.venv/bin/python -m livetrading \
  --quote-config config/livetrading.quote.schedule_us.sample.json \
  --history-config config/livetrading.history.polygon.sample.json \
  --pool-config config/livetrading.pool.sample.json \
  --trade-config config/livetrading.trade_account.notify.sample.json
```

## 6. 启动后应该看到什么

启动后通常会先看到：

- `CONFIG_APPLIED`
- `SCHEDULE_BROKER_CONNECTED`

如果当前不是美股交易日开盘时段，启动后不会立刻去拉 warm-up 日线。

到美东 `09:30` 左右应该再看到：

- `SCHEDULE_TRIGGER`
- `NOTIFY_SIGNAL`

如果邮件打开并发送成功，还会看到：

- `NOTIFY_EMAIL_SENT`

如果 SMTP 失败，会看到：

- `NOTIFY_EMAIL_FAILED`

## 7. dual_momentum 的 warm-up

`dual_momentum` 需要的 warm-up 根数取决于参数。

如果你使用仓库当前样例参数：

- `lookback_days=90`
- `long_lookback_days=180`
- `long_lookback_weight=0.25`
- `market_filter_window=120`
- `volatility_window=20`
- `volume_window=20`

那么需要：

- `186` 个交易日的日线 warm-up

如果你修改了参数，系统会自动按策略参数重新计算所需 warm-up 根数。

## 8. 邮件内容

邮件正文默认使用中文，包含这些信息：

- 策略名
- 信号时间
- 已完成交易日
- 当前股票池
- 推荐目标
- 备选候选
- 风险状态
- 原因

典型例子：

- 推荐目标：`US.MSFT`
- 推荐目标：`US.AAPL、US.MSFT`
- 推荐目标：`CASH`

## 9. 当前限制

- 这套模式只通知“当前股票池推荐买谁”，不读取账户持仓
- 当前不做跨重启去重；如果你在同一个交易日 `09:30` 后重启，并且 `catch_up_missed_session=true`，可能会再次提醒
- 当前邮件发送只实现了标准 SMTP + STARTTLS
- 当前 `notify` 模式要求 `trade_account.broker.type=mock`，这是配置兼容占位，不会真的连接 mock 券商之外的任何服务

## 10. 推荐部署方式

建议把它作为单独进程部署，不要和原来的 realtime quote / real order 进程混跑。

推荐做法：

- 一个进程跑原有 `futu/mock` 实时模式
- 另一个进程单独跑 `schedule_us + notify`

这样职责最清楚，也避免两种模式互相影响。
