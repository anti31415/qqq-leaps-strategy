# QQQ LEAPS Strategy Monitoring Formulas

This document defines what each local monitoring run checks before deciding whether to buy, sell, hold, or manage the short-call overlay.

## Data Inputs

- QQQ daily bars from Alpaca stock data API.
- VIX daily close from Yahoo chart data.
- QQQ option contracts and option snapshots from Alpaca.
- Local strategy state from `state.json`.
- Alpaca paper account, positions, and open orders from Alpaca trading API.

## Indicators

### QQQ RSI(14)

The strategy uses Wilder RSI.

```text
Change_t = Close_t - Close_(t-1)
Gain_t = max(Change_t, 0)
Loss_t = max(-Change_t, 0)

AvgGain_t = (AvgGain_(t-1) * 13 + Gain_t) / 14
AvgLoss_t = (AvgLoss_(t-1) * 13 + Loss_t) / 14

RS = AvgGain_t / AvgLoss_t
RSI = 100 - 100 / (1 + RS)
```

Base buy filter:

```text
QQQ RSI(14) < 35
```

### VIX Expanding Mean And Standard Deviation

For each trading day, use all available VIX closes up to that day.

```text
VIXMean_t = average(VIX_0 ... VIX_t)
VIXStd_t = sample_standard_deviation(VIX_0 ... VIX_t)
```

Thresholds:

```text
Sigma1Threshold_t = VIXMean_t + 1 * VIXStd_t
Sigma2Threshold_t = VIXMean_t + 2 * VIXStd_t
```

### Sigma 1 Entry

```text
QQQ RSI(14) < 35
AND Sigma2Threshold_t > VIX_t >= Sigma1Threshold_t
AND no Sigma 1 entry already recorded in the same ISO week
```

Action:

```text
Buy 1 QQQ LEAPS call
```

### Sigma 2 First Entry

Define a Sigma 2 signal day:

```text
QQQ RSI(14) < 35
AND VIX_t >= Sigma2Threshold_t
```

First Sigma 2 entry:

```text
Sigma2Count60_t = count(Sigma 2 signal days from t-59 through t)
Sigma2Count60_t == 1
```

Action:

```text
Buy 1 QQQ LEAPS call
```

### Sigma 2 Repeat Entry

```text
Sigma2Count20_t = count(Sigma 2 signal days from t-19 through t)
Sigma2Count20_t >= 2
```

Action:

```text
Buy 2 QQQ LEAPS calls
If buying power is insufficient for 2 but sufficient for 1, buy 1.
```

### LEAPS Contract Selection

Target:

```text
Underlying = QQQ
Type = Call
Target DTE ~= 730 calendar days
Target Delta ~= 0.70
```

Selection sort:

```text
min(abs(delta - 0.70))
then min(abs(DTE - 730))
then lower strike
```

### Short Call Overlay

For every locally managed open LEAPS position with no active short call:

```text
Short call DTE ~= 30 calendar days
Short call strike >= QQQ close * 1.10
Quantity = managed LEAPS quantity
```

Selection sort:

```text
min(abs(DTE - 30))
then min(abs(strike - QQQ close * 1.10))
then lower strike
```

### Exit Rules

Net position value:

```text
NetValue = LEAPS current mid price * 100 * quantity
         + realized short call cash
         - active short call liability
```

Profit percentage:

```text
PnlPct = (NetValue - EntryCost) / EntryCost
```

Sigma 1 exit:

```text
Holding age < 12 months: sell if PnlPct >= 120%
Holding age 12-15 months: sell if PnlPct >= 60%
Holding age 16-18 months: sell if PnlPct >= 30%
Days to LEAPS expiry <= 180: force exit
```

Sigma 2 exit:

```text
Holding age < 12 months: sell if PnlPct >= 150%
Holding age 12-15 months: sell if PnlPct >= 80%
Holding age 16-18 months: sell if PnlPct >= 30%
Days to LEAPS expiry <= 180: force exit
```

If an active short call exists when a LEAPS exit is triggered, the script first plans a buy-to-close short call order, then a sell-to-close LEAPS order.

