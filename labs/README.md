# labs

这个目录放实验性质的脚本，不属于当前正式交付的策略实现。

当前内容：

- `backtest_three_minute_momentum.py`
  - 最早的三分钟连涨买入 / 连跌卖出实验
- `search_better_strategy.py`
  - 用来批量搜索简单策略和参数组合的研究脚本
  - 支持单标的（`--data-dir`）和股票池（`--codes`）两种模式
  - 当前会一起扫描以下策略族：
    - EMA 金叉死叉
    - RSI 反转
    - 通道突破
    - Bollinger Band 均值回归
    - MACD 趋势跟随

正式策略脚本仍然放在 `scripts/`：

- `backtest_rsi_reversion.py`
- `backtest_ema_cross.py`
- `backtest_ema_rsi_combo.py`
- `backtest_ema_rsi_bull_range.py`
