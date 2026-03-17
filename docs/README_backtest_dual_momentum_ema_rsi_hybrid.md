# Dual Momentum + EMA + RSI Hybrid（港股/美股股票池）

继续优化后，目标改为：**中等以上交易频率 + 四组回测全部回正**。

## 参数口径

```bash
# HK 两组
--initial-cash 800000
# US 两组
--initial-cash 100000

# 其余参数四组一致
--fee-account futu_alt
--lookback-days 20
--long-lookback-days 120
--long-lookback-weight 0.0
--market-filter-window 20
--daily-vol-window 20
--min-momentum-score -1.0
--rebalance-days 5
--switch-score-buffer 0.0
--min-hold-days 0
--timing-score-weight 0.2
--fast-span 20
--slow-span 120
--rsi-period 14
--entry-rsi-min 35
--entry-rsi-max 85
--exit-rsi-min 25
--stop-loss-pct 0.12
--take-profit-pct 0.2
--position-ratio 1.0
```

## 股票池

- 港股（8）：`HK.00700 HK.09988 HK.00005 HK.01810 HK.03690 HK.01211 HK.03750 HK.00981`
- 美股（8）：`US.MSFT US.NVDA US.GOOG US.TSLA US.AMZN US.AAPL US.V US.VOO`

## 4 组回测结果对比（优化后）

| market | window | trades | final_value | return_pct | max_drawdown_pct |
| --- | --- | ---: | ---: | ---: | ---: |
| HK pool (8) | 2025-01-01 ~ 2026-01-01 | 32 (BUY 16 / SELL 16) | 1180665.67 | 47.58% | -37.73% |
| HK pool (8) | 2025-03-07 ~ 2026-03-06 | 28 (BUY 14 / SELL 14) | 1232465.13 | 54.06% | -23.44% |
| US pool (8) | 2025-01-01 ~ 2026-01-01 | 24 (BUY 12 / SELL 12) | 125494.37 | 25.49% | -28.96% |
| US pool (8) | 2025-03-07 ~ 2026-03-06 | 24 (BUY 12 / SELL 12) | 146719.14 | 46.72% | -22.76% |

## 结论

- 交易频率已从此前的低频（2~8 笔）提升到中等以上（24~32 笔）。
- 四组回测收益率全部回正，满足当前目标。
- 当前主要代价是回撤抬升（尤其 HK 窗口一），后续可在不降频的前提下继续压回撤。

## 参考论文（在线）

- Antonacci, *Risk Premia Harvesting Through Dual Momentum*  
  https://www.optimalmomentum.com/research-papers/
- Moskowitz, Ooi, Pedersen, *Time Series Momentum*  
  https://www.aqr.com/insights/research/journal-article/time-series-momentum
- Moreira, Muir, *Volatility Managed Portfolios*  
  https://www.nber.org/papers/w22208
- Jegadeesh, Titman, *Returns to Buying Winners and Selling Losers*  
  https://www.jstor.org/stable/2328882
- Faber, *A Quantitative Approach to Tactical Asset Allocation*  
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461
