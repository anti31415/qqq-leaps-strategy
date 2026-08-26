# Backtest Results

## Method

- Historical data window: `2011-01-01` through `2026-03-31`.
- Strategy window: `2012-01-01` through `2026-03-31`.
- Underlying: QQQ.
- Entry: RSI(14) below 35 and VIX at least expanding mean plus two standard deviations.
- Pricing: Black–Scholes approximation, not a historical option-chain replay.
- Initial capital: USD 20,000; no additional contributions.
- Contract: approximately 730 DTE and target delta 0.70.

## Summary

| Metric | Value |
| --- | ---: |
| Entries | 15 |
| Closed trades | 15 |
| Winning trades | 15 |
| Win rate | 100.00% |
| Ending equity | $105,891.00 |
| Total profit | $85,891.00 |
| Capital multiple | 5.29x |
| Annualized return | 12.41% |
| Maximum drawdown | -32.97% |

These figures are model-specific historical results, not a forecast. The small sample and simplified option pricing make sensitivity analysis essential.

