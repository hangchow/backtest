# `backtest_dual_momentum.py` / `strategy/dual_momentum.py` 代码导读

这份文档不是“怎么跑命令”的说明，而是面向读代码时的结构化解读。

- 使用说明和回测结果看 [README_backtest_dual_momentum.md](./README_backtest_dual_momentum.md)
- 本文重点看两层职责：
  - [backtest/backtest_dual_momentum.py](../backtest/backtest_dual_momentum.py)：CLI、读盘、组合撮合、费用、报表
  - [strategy/dual_momentum.py](../strategy/dual_momentum.py)：参数定义、信号计算、warm-up 需求、目标权重输出

## 先看整体分层

这两个文件是故意拆开的，原因很明确：

- `strategy/dual_momentum.py` 只负责“给定一段日线历史，此时此刻应该持有哪些标的、每个标的目标权重是多少”
- `backtest/backtest_dual_momentum.py` 负责“这些目标权重在回测账户里怎么落地成买卖、现金、手续费、权益曲线和最终报表”

换句话说：

- `strategy` 层回答的是“想持有什么”
- `backtest` 层回答的是“实际买成了多少、花了多少手续费、最后赚了多少”

这样拆开的好处是：

- 实盘和回测可以共用同一套 signal 逻辑
- 参数校验不会在不同入口各写一份
- 以后改“选股逻辑”和改“回测撮合逻辑”时，影响范围更清楚

## 代码执行路径

单次命令的大致执行顺序是：

1. `main()`
2. `parse_args()`
3. `load_daily_data()`
4. `run_backtest()`
5. `strategy.build_dual_momentum_signal_history()`
6. 回测日循环里根据 signal 做卖出、买入、记权益
7. `render_single_strategy_report()` 输出表格

如果只想快速抓主线，看下面几个函数就够了：

- [parse_args](../backtest/backtest_dual_momentum.py)
- [load_daily_data](../backtest/backtest_dual_momentum.py)
- [run_backtest](../backtest/backtest_dual_momentum.py)
- [DualMomentumParams](../strategy/dual_momentum.py)
- [build_dual_momentum_signal_history](../strategy/dual_momentum.py)

## `strategy/dual_momentum.py` 负责什么

这个文件是“纯策略层”。输入是 `prices` / `volumes` 两张按交易日对齐的表，输出是某一天或整段历史上的 `DualMomentumSignal`。

### 1. 默认参数和参数对象

文件顶部先定义一组默认值：

- `DEFAULT_LOOKBACK_DAYS = 90`
- `DEFAULT_LONG_LOOKBACK_DAYS = 180`
- `DEFAULT_LONG_LOOKBACK_WEIGHT = 0.25`
- `DEFAULT_TOP_N = 1`
- `DEFAULT_VOLUME_WINDOW = 20`
- `DEFAULT_MIN_VOLUME_RATIO = 1.3`
- `DEFAULT_MARKET_FILTER_WINDOW = 120`
- `DEFAULT_VOLATILITY_WINDOW = 20`
- `DEFAULT_TARGET_ANNUAL_VOL = 0.30`
- `DEFAULT_MAX_GROSS_EXPOSURE = 1.0`

这些参数被收口到 `DualMomentumParams` 里。这个 dataclass 的作用不是“好看”，而是让回测和实盘真正共享一份参数定义。

`DualMomentumParams` 里有三个关键方法：

- `from_mapping()`
  - 处理配置文件里字符串数值的类型收敛
- `validate()`
  - 统一参数校验口径
- `required_warmup_bars()`
  - 告诉上层最少要准备多少根日线

这里一个很关键的设计点是：

- `rebalance_band_pct` 不在 `DualMomentumParams` 里

原因是它不属于“信号层参数”，而属于“执行层参数”。signal 只决定目标权重，band 是回测/交易账户实际调仓时的执行摩擦控制。

### 2. `DualMomentumSignal` 是什么

`DualMomentumSignal` 是策略层吐给上层的一张“决策结果”：

- `completed_trade_date`
- `target_codes`
- `target_weights`
- `gross_exposure`
- `market_is_risk_on`
- `candidate_codes`

可以把它理解成：

- 候选股票先排出来
- 再看大盘是否 risk-on
- 如果 risk-on，候选股票变成实际目标持仓
- 同时再给一个总风险暴露比例 `gross_exposure`

所以它不是简单的“买哪个”，而是已经把：

- 选股
- 市场过滤
- 波动率缩放

三步都合在一起了。

### 3. 参数校验

`validate_dual_momentum_params()` 统一检查：

- lookback 必须大于 0
- `long_lookback_weight` 必须在 `[0, 1]`
- `top_n > 0`
- `volume_window` / `min_volume_ratio` 复用 volume 模块的校验
- `market_filter_window > 0`
- `volatility_window > 1`
- `target_annual_vol > 0`
- `max_gross_exposure >= 1`

这里最后一条很重要：

- 策略不允许把 `max_gross_exposure` 设成小于 `1`

也就是说，策略层认为：

- `target_annual_vol` 用来“缩”
- `max_gross_exposure` 用来“封顶”

不是用它来做低于 100% 的额外折扣。

### 4. warm-up 需求怎么算

有两个函数：

- `required_dual_momentum_signal_bars()`
- `required_dual_momentum_warmup_bars()`

它们的区别是：

- `signal_bars` 是“理论上最少几根 bar 才能算出信号”
- `warmup_bars` 是“实际建议准备多少根 bar 给上层用”

`required_dual_momentum_signal_bars()` 取所有窗口的最大值：

- 短周期动量
- 长周期动量
- 大盘均线窗口
- 波动率窗口
- 成交量窗口

`required_dual_momentum_warmup_bars()` 则是在这个基础上再留一点余量：

- `return max(signal_bars, 30) + 5`

这是个很实用的保守做法，避免刚好踩边界时因为缺一天数据就出不来信号。

### 5. 选股和放量加分

`select_target_codes()` 很简单：

- 先丢掉 `NaN`
- 再丢掉非正动量
- 剩下的按动量从大到小排
- 取前 `top_n`

重点是它只保留正动量标的，所以这个策略天然允许“空仓”，不会为了凑持仓数硬买负动量股票。

`compute_volume_boost()` 则是一个软加分器：

- 不是成交量不达标就禁买
- 而是成交量够强时，把动量分数乘一个 boost

具体规则：

- 相对量先截到 `MAX_VOLUME_BOOST_RATIO = 1.5`
- 未达阈值时 boost = 1
- 达阈值后 boost = `volume_ratio / min_volume_ratio`

所以它表达的是：

- 放量是确认项
- 但不是硬门槛
- 而且加分有上限，避免极端天量把排序拉歪

### 6. 单点信号和整段信号

这个文件同时提供：

- `build_dual_momentum_signal()`
- `build_dual_momentum_signal_history()`

前者只是一个薄封装：

- 直接调用后者
- 取最后一条 signal

真正核心逻辑都在 `build_dual_momentum_signal_history()`。

### 7. `build_dual_momentum_signal_history()` 的核心逻辑

这就是整个 dual momentum 的信号引擎。

它做的事情可以按顺序拆成 7 步：

1. 参数收敛和校验
2. 检查 `prices` / `volumes` 的 index 和 columns 完全一致
3. 预先计算所有中间量
4. 对每个交易日判断是否已满足 warm-up
5. 计算候选股票
6. 计算市场 risk-on / risk-off
7. 生成 `DualMomentumSignal`

具体中间量有：

- `relative_volume`
  - 每只股票各自按 `volume_window` 算相对量
- `short_momentum`
  - `prices / prices.shift(lookback_days) - 1`
- `long_momentum`
  - `prices / prices.shift(long_lookback_days) - 1`
- `blended_momentum`
  - 短动量和长动量按权重混合
- `weighted_momentum`
  - 只保留正动量，再乘上 `volume_boost`

这里有一个很重要的细节：

- `weighted_momentum = blended_momentum.where(blended_momentum > 0) * volume_boost`

意思是：

- 先把非正动量变成空值
- 再做成交量加分

所以成交量再大，也不能把一个负动量股票“洗白”成候选股票。

### 8. 大盘风险过滤

风险过滤很朴素：

- `pool_close = prices.mean(axis=1)`

也就是直接拿股票池等权平均收盘价当市场代理。

然后：

- `pool_ma = pool_close.rolling(market_filter_window).mean()`
- 当前 `pool_close >= pool_ma` 才算 `market_is_risk_on`

这说明它不是用外部指数做过滤，而是用“股票池自身的等权均值”做过滤。

优点：

- 不依赖额外 benchmark 数据

代价：

- 风险过滤结果会受股票池构成影响

### 9. 波动率缩放

这套实现还有一层组合风险控制：

- 先算 `pool_close.pct_change()`
- 再做滚动标准差
- 再乘 `sqrt(252)` 年化
- 用 `target_annual_vol / annualized_vol` 得到缩放倍数

关键点：

- 这个倍数被 `clip(upper=1.0)`

也就是说默认只做“降杠杆/降风险”，不会因为波动太低而自动放大到超过 1。

最终：

- `gross_exposure = target_vol_multiplier * max_gross_exposure`

所以如果：

- `target_vol_multiplier = 1`
- `max_gross_exposure = 1.2`

那目标总名义仓位可以到 `120%`。

### 10. 每个交易日最终输出什么

进入主循环后，每天会先判断：

- 是否已满足 `required_bars`

不满足就输出 `None`。

满足后再：

- 根据 `weighted_momentum` 选 `candidate_codes`
- 根据 `pool_close >= pool_ma` 决定是否 risk-on
- risk-on 时才真的生成 `target_codes`
- 按 `gross_exposure / len(target_codes)` 等权分配

所以 signal 层最终是一个非常明确的 contract：

- 要么给空仓
- 要么给一组标的和等权目标

它不关心交易费用、现金不足、最小交易单位这些执行问题。

## `backtest/backtest_dual_momentum.py` 负责什么

这个文件是“策略信号如何在回测账户里落地”的部分。

### 1. `parse_args()` 做了三件事

第一件事是从 `strategy_config` 先解析配置文件默认值。

这一步的作用是：

- 命令行不传参数时，可以直接继承 JSON 配置里的值
- 命令行显式传参时，再覆盖配置文件默认值

第二件事是把 dual momentum 的信号层参数和执行层参数一起暴露出来。

信号层参数包括：

- `lookback-days`
- `long-lookback-days`
- `long-lookback-weight`
- `top-n`
- `volume-window`
- `min-volume-ratio`
- `market-filter-window`
- `volatility-window`
- `target-annual-vol`
- `max-gross-exposure`

执行层参数主要是：

- `rebalance-band-pct`
- `fee-account`
- `security-type`
- `market`

第三件事是保留 `--eval-start/--eval-end`。

这两个参数只影响“记分窗口”，不影响前面的 warm-up 数据参与信号计算。

### 2. `load_daily_data()` 的职责

这个函数做的是纯读盘：

- 遍历 `kline_day/<code>/` 下的所有 CSV
- 读取 `time_key/close/volume`
- 按时间排序
- 去重
- 拼成两张宽表：
  - `prices`
  - `volumes`

最后输出的形状是：

- index = 交易日
- columns = 股票代码

这正好是 `strategy/dual_momentum.py` 需要的输入格式。

这里顺手还做了一个统计：

- 如果传了 `FilesystemLoadTracker`
- 就累计文件加载耗时、文件数、load operations

所以你在 CLI 输出里看到的：

- `Filesystem load time`
- `Files loaded`
- `Load operations`

就是从这里来的。

### 3. `run_backtest()` 是真正的账户模拟

这是回测主循环，也是最值得细看的地方。

它大致分成 6 块：

1. 参数对象化和校验
2. eval window 解析
3. 预计算整段 signal history
4. 每日调仓循环
5. 权益曲线与回撤统计
6. summary/trades 输出

### 4. 为什么这里又组装 `DualMomentumParams`

虽然 CLI 已经拿到了单独参数，但 `run_backtest()` 里还是重新组装了一次：

- `strategy_params = DualMomentumParams(...)`

原因是：

- 回测入口继续保留旧函数签名，兼容已有调用方
- 但内部全部收口到 strategy 层的统一参数对象

这是个典型的“外部兼容，内部收敛”的改法。

### 5. 为什么 `rebalance_band_pct` 不进 `DualMomentumParams`

在回测里它被单独包装成：

- `RebalancePolicy(band_pct=rebalance_band_pct)`

这是因为它确实不是 signal 逻辑的一部分，而是执行层的调仓摩擦控制。

signal 层只说：

- 目标权重应该是多少

执行层再决定：

- 当前持仓和目标持仓差多少时才值得真的交易

### 6. eval window 的处理方式

这段很重要，容易误读。

`resolve_eval_window()` 返回：

- `eval_mask`
- `warmup_start_time`
- `start_time`
- `end_time`

然后代码会：

- 先用全样本 `prices/volumes` 预计算 `precomputed_signals`
- 再只在 `eval_start_date ~ eval_end_date` 之间记交易和收益

所以这里的语义是：

- 窗口前数据可以用来预热指标
- 但不会算进回测成绩

### 7. 为什么要先整段预计算 `precomputed_signals`

这行是关键：

- `precomputed_signals = build_dual_momentum_signal_history(...)`

好处有两个：

- 避免在每日循环里重复算滚动窗口
- 保证每个交易日使用的 signal 都是基于“截至当日”的统一历史口径

也就是说，回测主循环不是每天临时重新拼指标，而是先把整段 signal history 算好，再逐日读取。

### 8. 每个交易日循环到底做什么

主循环的顺序非常重要：

1. 先取当日有价格的股票 `tradable_row`
2. 更新 `last_prices`
3. 读取当天已经预计算好的 `signal`
4. 如果还没进入 eval window，就跳过记账
5. 根据目标权重计算 `desired_shares`
6. 先卖
7. 再买
8. 记录当天权益

这里有几个关键实现细节。

#### 8.1 `tradable_row = close_row.dropna()`

这表示：

- 某只股票当天停牌或缺失数据，就不参与当日交易

所以这个回测允许：

- 股票池整体继续运行
- 单个标的某天不可交易

#### 8.2 signal 允许空仓

这段：

- `target_weights = signal.target_weights if signal is not None else {}`

意味着：

- warm-up 不够时，目标仓位为空
- 风险过滤不通过时，目标仓位也为空

后面的执行层自然就会把仓位往 0 调。

#### 8.3 目标股数怎么来

目标权重不是直接拿来下单，而是先转成目标股数：

- `build_desired_shares(...)`

输入包括：

- 当前持仓
- 目标权重
- 当日价格
- 当前组合净值
- `RebalancePolicy`

所以真正控制“是否需要调仓”的，是 `build_desired_shares()` + `RebalancePolicy`，不是 signal 层。

#### 8.4 为什么先卖后买

代码明确采用：

- 先卖
- 再买

原因也写在注释里：

- 先释放现金
- 更接近常见回测撮合顺序

这是一个非常合理的账户模拟假设。

#### 8.5 买入时为什么有 `remaining_gross_capacity`

这段是 dual momentum 回测的一个核心执行细节：

- 先算当前已持仓名义金额
- 再算剩余总仓位额度
- 然后 `available_cash = cash + remaining_gross_capacity`

它表达的是：

- 当策略允许 `max_gross_exposure > 1` 时
- 账户可以在受控范围内使用额外名义仓位
- 但仍然不能无限放大

也就是说，这里不是严格的“纯现金账户”，而是一个带总仓位上限的简化保证金模型。

#### 8.6 手续费在哪里扣

卖出：

- `cash += sell_qty * price - fee_total`

买入：

- `cash -= affordable_qty * price + fee_total`

这里费用口径统一复用 `compute_order_fees()` 和 `compute_affordable_qty_with_fee()`，所以：

- 先考虑费用
- 再决定真实能买多少

不会出现“先算得起，扣完手续费又超资金”的问题。

### 9. 权益曲线和 summary 怎么生成

每日循环结束后，代码把：

- `cash`
- 当前持仓按 `last_prices` 估值

相加得到当天权益。

然后：

- `cummax()` 生成滚动高点
- 算 `drawdown_pct`

最终 summary 里会放：

- warm-up / eval 时间
- 所有策略参数
- 买卖次数
- 总手续费
- 期末现金
- 期末持仓
- `final_value`
- `total_return_pct`
- `max_drawdown_pct`

所以 summary 不只是拿来打印，也是一份完整的回测元数据载体。

### 10. `main()` 怎么把这些部件串起来

`main()` 的流程很线性：

1. 解析参数
2. 校验股票代码和 market 一致性
3. 读日线数据
4. 解析 eval window
5. 跑回测
6. 用 `render_single_strategy_report()` 输出统一表格
7. 可选打印全部 trades

CLI 末尾多出来的覆盖表：

- `Daily data coverage`

是通过 `observations_by_code_from_frame(prices)` 生成的，它展示的是：

- 评估窗口内起止
- 完整数据集起止
- 两段范围各自是否缺失

## 这个实现到底在交易什么逻辑

如果把实现压缩成人话，可以概括成：

1. 用短周期和长周期收益率混合成动量分数
2. 只有正动量股票才进入候选池
3. 放量股票会被加分
4. 只拿分数最高的前 `N` 个
5. 股票池等权均值站上长期均线时才允许持仓
6. 如果股票池波动太高，就缩小总风险暴露
7. 执行层把目标权重落地成“先卖后买”的实际交易
8. 交易时考虑手续费、剩余现金和总仓位上限

## 读代码时最容易误解的点

### 1. 这不是“纯论文版 dual momentum”

这里混入了几个实务化改造：

- 成交量加分
- 市场均线风险过滤
- 波动率目标缩放
- 执行层调仓带宽

所以它更像“dual momentum 风格的本地策略实现”，不是论文复刻版。

### 2. 风险过滤不是看指数

它看的是：

- 当前股票池自身的等权平均价格

不是：

- SPY
- HSI
- 其他 benchmark

这会直接影响策略行为。

### 3. `top_n` 是选股层参数，不等于一定会持有 `N` 只

因为还要再经过：

- 正动量筛选
- risk-on 判断

所以最终可能：

- 持有 0 只
- 持有少于 `top_n` 只

### 4. `max_gross_exposure` 不是总会生效

因为前面还有：

- `target_vol_multiplier.clip(upper=1.0)`

如果波动太高，`gross_exposure` 会先被缩小，最后可能远低于 `max_gross_exposure`。

### 5. `eval-start` 不会阻止窗口前数据参与 signal 计算

它只控制：

- 何时开始记交易成绩

不会控制：

- 何时开始计算滚动动量、均线和波动率

## 如果你想继续改这套策略，优先看哪里

按改动类型分：

- 改参数定义和 warm-up 需求
  - 看 [strategy/dual_momentum.py](../strategy/dual_momentum.py)
- 改选股逻辑、risk filter、vol scaling
  - 看 [strategy/dual_momentum.py](../strategy/dual_momentum.py)
- 改手续费、撮合顺序、调仓带宽、仓位落地
  - 看 [backtest/backtest_dual_momentum.py](../backtest/backtest_dual_momentum.py)
- 改 CLI 和报表输出
  - 看 [backtest/backtest_dual_momentum.py](../backtest/backtest_dual_momentum.py)

最常见的几个落点是：

- 想把股票池 risk filter 改成指数 filter
  - 改 `build_dual_momentum_signal_history()`
- 想把 volume boost 改成硬过滤
  - 改 `compute_volume_boost()` 或 `select_target_codes()` 前的输入构造
- 想降低换手
  - 优先看 `rebalance_band_pct`
- 想让仓位更激进
  - 看 `target_annual_vol` 和 `max_gross_exposure`
- 想让窗口更短更敏感
  - 看 `lookback_days` / `market_filter_window`

## 一句话总结

这套实现的核心思想是：

- `strategy/dual_momentum.py` 负责把“股票池日线历史”转换成“目标持仓权重”
- `backtest/backtest_dual_momentum.py` 负责把“目标权重”转换成“真实交易、费用、现金、权益曲线和报表”

读代码时只要抓住这个边界，整条链路就不会乱。
