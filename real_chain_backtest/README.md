# Real EOD Option-Chain Backtest

This workflow evaluates QQQ LEAPS strategies against historical end-of-day option-chain data and validates the generated metrics, curves, trades, and data-quality reports.

## Data preparation

The raw option chain is not distributed with this repository because `QQQ_options.parquet` is about 387 MB. Obtain the `data-v1` release from `lambdaclass/options_portfolio_backtester` and place these files under `data/`:

- `QQQ_options.parquet`: 15,345,882 rows from `2011-03-23` through `2025-12-15`.
- `QQQ_underlying.parquet`.
- `VIX_History.csv` from Cboe.

Known SHA-256 for `QQQ_options.parquet`:

```text
1F831556CD87EC9D7AF43D3B47A69A829FFB2FB199CFCEF4FF55D289BADF8734
```

## Run

```powershell
python -m pip install -r requirements.txt
python profile_chain.py
python backtest_real_chain.py
python validate_outputs.py
```

The modeled window is `2020-12-16` through `2025-12-15`. These are research-grade EOD scenarios, not intraday NBBO or fill guarantees.

