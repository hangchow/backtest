# livetrading 定时通知模式方案

这份文档描述一个新的部署模式方案，目标是：

- 保留当前已有的 `futu` / `mock` realtime quote 模式，不改现有订阅链路
- 新增一种“按美股开盘时间定时发现交易机会并通知人类”的模式
- 新模式下不连接 Futu，不读取账户持仓
- 新模式下只打印日志并发送邮件提醒

本文描述的是未来方案，不代表当前代码已经实现。

## 1. 目标

希望新增一套新的组合：

- `realtime_broker.type = schedule_us`
- `execution.executor = notify`

这套组合的语义是：

- realtime 侧不依赖实时 `QUOTE` 或实时 `K_1M`
- 系统按美股交易日历，在每个交易日 `09:30 America/New_York` 触发一次
- 触发时重新读取 history warm-up，拿到“上一交易日已完成日线”
- 策略基于这批 completed daily window 计算组合目标
- 系统只发通知，不调用 `place_order(...)`
- 系统不知道实际账户持仓，只通知“当前股票池里推荐买哪个”或“今天建议 `CASH`”

## 2. 非目标

这套模式不做下面这些事情：

- 不替换当前 `futu` / `mock` realtime quote broker
- 不替换当前 `mock` / `futu_simulate` / `futu_real` 执行器
- 不在 `notify` 模式下自动提交任何订单
- 不要求实时分钟 bar 订阅
- 不要求实时 quote 订阅
- 不尝试推导“该卖谁”
- 不尝试推导“建议买多少股”

## 3. dual_momentum 是否支持

支持。

`dual_momentum` 本身输出的是组合目标，而不是账户级订单。它天然会给出：

- `target_codes`
- `target_weights`
- `candidate_codes`
- `market_is_risk_on`

所以即使没有账户持仓，系统也仍然可以通知：

- 今天推荐买 `US.MSFT`
- 今天推荐买 `US.AAPL, US.MSFT`
- 今天不建议买入，保持 `CASH`

也就是说，这个模式对 `dual_momentum` 来说是自洽的，因为它只回答：

- 在当前配置的股票池里，今天最值得买的目标是什么

它不回答：

- 我现在持有什么
- 我应该卖掉什么
- 我应该买多少股

## 4. 新模式的职责拆分

### 4.1 `realtime_broker.type = schedule_us`

职责只有一个：

- 在美股交易日 `09:30 America/New_York` 触发一次策略评估

它不负责：

- 订阅 quote
- 订阅 bar
- 读取账户
- 发送邮件

### 4.2 `execution.executor = notify`

职责只有一个：

- 把策略目标翻译成对人类可读的提醒

它负责：

- 打印结构化日志
- 发送邮件

它不负责：

- 下单
- 计算股数
- 管理 `pending_orders`
- 维护账户影子状态

## 5. 新模式的运行流程

整体流程建议如下：

1. 进程启动
2. 读取配置
3. 按当前方式初始化 history provider
4. 初始化 `schedule_us` trigger broker
5. 到达下一个 `09:30 America/New_York`
6. 强制 refresh warm-up 日线
7. 用 refreshed warm-up 构建 completed daily window
8. 运行 `dual_momentum`
9. 拿到组合目标 `target_weights`
10. 记录结构化日志
11. 发送提醒邮件
12. 可选：记录“该交易日已提醒”状态；如果实现复杂，第一阶段可以先不做去重

这个模式里不需要：

- 账户同步
- 持仓快照
- 实时行情

## 6. 建议的数据语义

`notify` 模式的核心产物不再是“订单计划”，而是“选股建议”。

建议新增一个统一结构，例如：

```python
NotifyRecommendation(
    signal_time=...,
    completed_trade_date=...,
    strategy_name="dual_momentum",
    target_codes=("US.MSFT",),
    target_weights={"US.MSFT": 1.0},
    candidate_codes=("US.MSFT", "US.AAPL"),
    market_is_risk_on=True,
    summary="recommended target is US.MSFT",
    metadata={...},
)
```

如果风险关闭，则：

```python
NotifyRecommendation(
    signal_time=...,
    completed_trade_date=...,
    strategy_name="dual_momentum",
    target_codes=(),
    target_weights={},
    candidate_codes=("US.MSFT",),
    market_is_risk_on=False,
    summary="recommended target is CASH",
    metadata={...},
)
```

## 7. 提醒语义建议

### 7.1 基础版

第一阶段不依赖实时 quote，也不计算建议股数，只给出方向性提醒。

例如：

- 推荐买入：`US.MSFT`
- 备选候选：`US.MSFT`, `US.AAPL`
- 风险状态：`risk_on`

或者：

- 推荐买入：`US.AAPL`, `US.MSFT`
- 风险状态：`risk_on`

或者：

- 推荐目标：`CASH`
- 风险状态：`risk_off`

## 8. 配置草案

### 8.1 quote 配置

建议新增一种 realtime broker：

```json
{
  "realtime_broker": {
    "type": "schedule_us",
    "trigger_time": "09:30",
    "timezone": "America/New_York",
    "market_calendar": "XNYS",
    "catch_up_missed_session": true
  }
}
```

建议字段说明：

- `type`
  - 固定为 `schedule_us`
- `trigger_time`
  - 触发时间，第一版固定 `09:30`
- `timezone`
  - 第一版固定 `America/New_York`
- `market_calendar`
  - 第一版固定 `XNYS`
- `catch_up_missed_session`
  - 如果进程在 `09:30` 后重启，是否允许对当日尚未发送的提醒做一次补发

### 8.2 notify 配置

如果想尽量少改现有 CLI，可以继续保留 `trade-config` 文件，但其语义不再是“交易账户”，而只是“通知执行配置”。

第一阶段可以先沿用 `trade_account.execution.executor = notify` 这个入口，再单独加一段邮件配置：

```json
{
  "trade_account": {
    "account_id": "notify_only",
    "broker": {
      "type": "mock",
      "host": "mock",
      "port": 1
    },
    "execution": {
      "executor": "notify"
    },
    "notification": {
      "email": {
        "enabled": true,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "username": "bot@example.com",
        "password": "your-smtp-password",
        "from": "bot@example.com",
        "to": ["you@example.com"],
        "subject_prefix": "[dual_momentum]"
      }
    }
  }
}
```

这里的 `broker` 只是兼容当前配置装配路径的占位，不表示真的要连接券商。

如果后续愿意调整配置体系，更干净的方案是：

- `notify` 模式下完全不需要 `trade_account`
- 把邮件配置移到独立的 `notify` 配置段

## 9. 邮件内容建议

邮件内容建议按“今天推荐买谁”组织，而不是按内部模型字段直出。
发送给用户的邮件正文建议使用中文。

建议至少包含：

- `signal_time`
- `completed_trade_date`
- `strategy_name`
- `market regime` 或 `risk_on/risk_off`
- 当前股票池
- `target_codes`
- `candidate_codes`
- 人话摘要

一个示例：

```text
Subject: [dual_momentum] 2026-03-16 选股提醒

信号时间：2026-03-16 09:30:00 America/New_York
已完成交易日：2026-03-13
策略：dual_momentum

当前股票池：
- US.AAPL
- US.MSFT

推荐目标：
- US.MSFT

候选标的：
- US.MSFT
- US.AAPL

摘要：
当前股票池中，推荐目标为 US.MSFT。
```

风险关闭时示例：

```text
Subject: [dual_momentum] 2026-03-17 选股提醒

信号时间：2026-03-17 09:30:00 America/New_York
已完成交易日：2026-03-16
策略：dual_momentum

推荐目标：
- CASH

摘要：
当前股票池没有满足 risk-on 条件的目标，建议保持 CASH。
```

## 10. 日志建议

除邮件外，还应打印结构化日志，便于后续排障和归档。

建议增加类似日志：

```text
NOTIFY_SIGNAL signal_time=2026-03-16 09:30:00 completed_trade_date=2026-03-13 strategy=dual_momentum pool=US.AAPL,US.MSFT target_codes=US.MSFT candidate_codes=US.MSFT,US.AAPL market_is_risk_on=true
```

邮件发送成功或失败也应单独打日志：

- `NOTIFY_EMAIL_SENT`
- `NOTIFY_EMAIL_FAILED`

## 11. 建议的代码落点

如果后续落地，建议主要涉及这些地方：

- `livetrading/config.py`
  - 新增 `schedule_us` 配置解析
  - 新增 `executor = notify` 配置校验
  - 为 `notify` 模式放宽对真实 trade account 的依赖
  - 新增 `notification.email` 配置解析
- `livetrading/quote_brokers/base.py`
  - 为“定时触发 broker”保留统一接口
- 新增 `livetrading/quote_brokers/schedule.py`
  - 实现 `ScheduleUsTriggerClient`
- `livetrading/config_applier.py`
  - 支持新的 realtime broker 生命周期
- `livetrading/event_sinks.py`
  - 承接 schedule trigger 事件
- `livetrading/pool_strategies.py`
  - 直接复用现有 `dual_momentum` 目标输出
- 新增 `livetrading/notifications/email.py`
  - 负责 SMTP 邮件发送

## 12. 和现有模式的关系

这套新模式必须是增量扩展，不应破坏当前三种执行模式：

- `mock`
- `futu_simulate`
- `futu_real`

也不应破坏当前两种 realtime 模式：

- `realtime_broker.type = futu`
- `realtime_broker.type = mock`

推荐的策略是：

- 只新增，不重写
- 当前默认行为保持不变
- 只有明确配置成 `schedule_us + notify` 时，才走新路径

## 13. 风险点

### 13.1 定时触发不等于历史数据一定可用

`09:30` 时，history provider 必须已经能稳定提供上一个交易日的 completed daily bar。  
如果某个 provider 在这个时刻还拿不到最新 completed daily data，提醒可能滞后或失败。

### 13.2 没有持仓信息，就不能给出账户级建议

这个模式里系统不知道你实际持有什么，所以它不能可靠地说：

- 该卖谁
- 该换仓到谁
- 该买多少股

这不是 bug，而是这个模式的设计边界。

### 13.3 同日重复提醒

如果：

- 进程重启
- schedule broker 重连
- 配置热更新

都可能导致同一交易日重复触发。  
如果去重实现比较麻烦，第一阶段可以接受重复提醒。

也就是说，这一版方案默认优先保证：

- 能按时触发
- 能正确算出 `dual_momentum` 目标
- 能把结果发出去

而不是优先保证“同日绝不重复提醒”。

## 14. 去重建议

去重可以作为后续优化项，而不是第一阶段必须项。

如果后续要做，建议以 `(strategy_name, current_trade_date)` 作为通知去重键。

可选目标：

- 同一交易日成功发送后，不再重复发送
- 重启后仍能识别当天是否已经发送过

如果实现这套状态记录会明显拖慢落地，第一阶段可以直接不做，由用户接受可能出现的重复邮件。

## 15. 第一阶段最小可落地范围

建议第一阶段只做这些：

1. 新增 `realtime_broker.type = schedule_us`
2. 新增 `execution.executor = notify`
3. 不连接 Futu，不同步账户，不读取持仓
4. 每个美股交易日 `09:30 America/New_York` 触发一次
5. 触发时 refresh history warm-up
6. 计算 `dual_momentum`
7. 输出 `target_codes` / `candidate_codes` / `target_weights`
8. 打日志
9. 发邮件
10. 不自动下单
11. 第一阶段可不做重复提醒去重

不要在第一阶段引入：

- snapshot quote 定价
- 建议股数
- 账户同步
- 多市场支持
- 多账户单进程支持

## 16. 待确认问题

这部分建议在真正开工前先定死。

1. `notify` 模式下是否允许完全不传真实账户配置？
2. 如果现有 CLI 仍要求 `trade-config`，是否接受用 `mock broker` 作为占位？
3. 如果 history warm-up 拿不到最新 completed daily，是否允许延迟重试？
4. 是否需要 `catch_up_missed_session`？
5. 邮件里是否展示 `candidate_codes`？
6. 第一阶段是否完全不展示“建议买卖股数”？
7. `top_n > 1` 时是否允许直接推荐多只股票？
8. 是否完全接受同日可能重复提醒？

## 17. 推荐结论

推荐把这套能力定义为：

- 一个新的定时 trigger broker：`schedule_us`
- 一个新的人工提醒 executor：`notify`
- 不连接 Futu，不读取持仓
- 不做自动下单

它解决的是：

- 不依赖实时行情订阅
- 仍然能基于上一个交易日 completed daily data 发现信号
- 能告诉人类“今天在当前股票池里推荐买谁”
- 风险关闭时能明确告诉人类“今天建议 `CASH`”

这个方向和 `dual_momentum` 的目标输出天然兼容，也不会破坏现有 `mock / futu_simulate / futu_real` 路径。
