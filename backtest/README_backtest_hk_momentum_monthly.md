# `backtest_hk_momentum_monthly.py` 回测说明（港股/美股，双时间窗口）

本文档给出 `backtest/backtest_hk_momentum_monthly.py` 的四组回测结果：
- 市场：港股股票池、美股股票池（各 8 只）
- 时间窗口：
  - `2025-01-01` ~ `2026-01-01`
  - `2025-03-07` ~ `2026-03-06`

## 股票池

### 港股（8只）
- `HK.00700`
- `HK.09988`
- `HK.00005`
- `HK.01810`
- `HK.03690`
- `HK.01211`
- `HK.03750`
- `HK.00981`

### 美股（8只）
- `US.AAPL`
- `US.MSFT`
- `US.GOOG`
- `US.AMZN`
- `US.NVDA`
- `US.TSLA`
- `US.V`
- `US.VOO`

## 参数选择

参数采用“在当前口径下的网格搜索结果”作为较优参数（按两个窗口平均收益挑选）：

- 港股参数：
  - `lookback_days=20`
  - `top_n=2`
  - `rebalance_band_pct=0.01`
  - `initial_cash=800000`
- 美股参数：
  - `lookback_days=10`
  - `top_n=1`
  - `rebalance_band_pct=0.01`
  - `initial_cash=100000`

其余参数使用脚本默认值与统一费用口径（`--fee-account futu_alt`）。

## 四组回测结果对比

| 市场 | 时间窗口 | 初始资金 | lookback | top_n | rebalance_band_pct | 收益率 | 最大回撤(MDD) | 交易次数 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| HK | 2025-01-01 ~ 2026-01-01 | 800000 | 20 | 2 | 0.01 | **126.77%** | -28.48% | 158 |
| HK | 2025-03-07 ~ 2026-03-06 | 800000 | 20 | 2 | 0.01 | **23.20%** | -28.49% | 128 |
| US | 2025-01-01 ~ 2026-01-01 | 100000 | 10 | 1 | 0.01 | **43.29%** | -35.35% | 19 |
| US | 2025-03-07 ~ 2026-03-06 | 100000 | 10 | 1 | 0.01 | **68.03%** | -21.51% | 21 |

## 复现实验命令

### HK（窗口1）
```bash
python3 backtest/backtest_hk_momentum_monthly.py \
  --codes HK.00700 HK.09988 HK.00005 HK.01810 HK.03690 HK.01211 HK.03750 HK.00981 \
  --initial-cash 800000 \
  --fee-account futu_alt \
  --lookback-days 20 \
  --top-n 2 \
  --rebalance-band-pct 0.01 \
  --eval-start 2025-01-01 \
  --eval-end 2026-01-01 \
  --compare-baseline 0
```

### HK（窗口2）
```bash
python3 backtest/backtest_hk_momentum_monthly.py \
  --codes HK.00700 HK.09988 HK.00005 HK.01810 HK.03690 HK.01211 HK.03750 HK.00981 \
  --initial-cash 800000 \
  --fee-account futu_alt \
  --lookback-days 20 \
  --top-n 2 \
  --rebalance-band-pct 0.01 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --compare-baseline 0
```

### US（窗口1）
```bash
python3 backtest/backtest_hk_momentum_monthly.py \
  --codes US.AAPL US.MSFT US.GOOG US.AMZN US.NVDA US.TSLA US.V US.VOO \
  --initial-cash 100000 \
  --fee-account futu_alt \
  --lookback-days 10 \
  --top-n 1 \
  --rebalance-band-pct 0.01 \
  --eval-start 2025-01-01 \
  --eval-end 2026-01-01 \
  --compare-baseline 0
```

### US（窗口2）
```bash
python3 backtest/backtest_hk_momentum_monthly.py \
  --codes US.AAPL US.MSFT US.GOOG US.AMZN US.NVDA US.TSLA US.V US.VOO \
  --initial-cash 100000 \
  --fee-account futu_alt \
  --lookback-days 10 \
  --top-n 1 \
  --rebalance-band-pct 0.01 \
  --eval-start 2025-03-07 \
  --eval-end 2026-03-06 \
  --compare-baseline 0
```
