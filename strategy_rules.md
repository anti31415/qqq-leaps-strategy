# Strategy Rules

## Thesis

Buy long-dated QQQ call options only during severe oversold conditions, scale entries conservatively, and exit using age-dependent profit targets or a time-to-expiry stop.

## Entry

- Underlying: QQQ only.
- Signal: daily RSI(14) below 35.
- Volatility filter: VIX at or above its expanding historical mean plus two standard deviations.
- Frequency: at most one contract per ISO week in the approximate model.
- Contract: approximately two years to expiry, with target delta near 0.70.
- Starting capital: USD 20,000 with no additional contributions.

## Exit

- Holding period below 12 months: take profit at 150%.
- Holding period from 12 to 15 months: take profit at 75%.
- Holding period from 16 to 18 months: take profit at 30%.
- Force exit when 180 days or less remain to expiry.

## Modeling assumptions

The approximate backtest uses Yahoo Finance daily prices, a 252-day realized-volatility estimate scaled by 1.2 and bounded between 15% and 75%, a 3% risk-free rate, a 730-day expiry approximation, and Black–Scholes pricing. The covered-call overlay is studied separately and is not part of the base model.

## Risks

The design is capital-efficient and waits for stressed conditions. Its weaknesses are path dependency, large option drawdowns, clustered losses during prolonged bear markets, model risk, tax friction, and execution uncertainty.

