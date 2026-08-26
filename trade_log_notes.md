# Trade Log Notes

Machine-readable trade records live in `research_outputs/` and `dte_v1_analysis/`. The approximate model uses RSI(14) below 35, a VIX two-standard-deviation filter, one new contract per ISO week, approximately two-year expiry, target delta near 0.70, age-based profit targets, and a 180-DTE forced exit.

Stable exit labels are:

- `take_profit_150_before_12m`
- `take_profit_75_12_to_15m`
- `take_profit_30_16_to_18m`
- `force_exit_180d_to_expiry`

New trade research should preserve the data date, quote convention, transaction-cost assumption, and whether the result is simulated or observed.

