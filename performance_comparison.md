# Performance Comparison

## Scope

- Window: `2016-03-01` through `2026-03-31`.
- Benchmarks: Nasdaq Composite (`^IXIC`) and S&P 500 (`^GSPC`).
- CAGR is calculated from start and end values.
- Sharpe uses daily returns and a constant 3% risk-free rate.
- Volatility is annualized daily-return standard deviation.

## Results

| Asset | Cumulative return | CAGR | Sharpe | Annualized volatility | Maximum drawdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| Strategy | 415.44% | 17.66% | 0.72 | 21.71% | -32.97% |
| Nasdaq Composite | 360.39% | 16.35% | 0.67 | 21.90% | -36.40% |
| S&P 500 | 230.00% | 12.57% | 0.58 | 17.99% | -33.92% |

The strategy modestly outperformed the selected benchmarks in this modeled window, with similar volatility to the Nasdaq. This does not mean it is safer: option path risk, liquidity, slippage, and regime changes are not fully represented.

