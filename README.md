# QQQ LEAPS Strategy Research

An open research project for a rules-based QQQ LEAPS strategy. It contains a paper-trading scaffold, approximate Black–Scholes backtests, and a reproducible EOD option-chain study.

## Contents

- `strategy_rules.md` — strategy thesis and explicit assumptions.
- `backtest_results.md` — approximate backtest methodology and results.
- `performance_comparison.md` — benchmark comparison.
- `trade_log_notes.md` — trade-level research notes.
- `autotrade/` — Alpaca paper-trading scaffold; preview mode is the default.
- `research_outputs/` — generated curves, summaries, and trade records.
- `dte_v1_analysis/` — DTE V1 versus deployed-version comparisons.
- `real_chain_backtest/` — EOD option-chain backtest and validation workflow.

## Reproducibility

The approximate model uses QQQ daily data, VIX filters, Black–Scholes pricing, a fixed initial balance, and explicit take-profit rules. The real-chain study covers `2020-12-16` through `2025-12-15` and uses EOD bid/ask scenarios. It is not intraday NBBO data and does not guarantee executable fills.

The original option-chain file is intentionally excluded because it is about 387 MB. Acquisition instructions and its SHA-256 checksum are documented in `real_chain_backtest/README.md`.

## Quick start

```powershell
node backtest_tianbro_qqq_leaps.js
python -m pip install -r real_chain_backtest/requirements.txt
python real_chain_backtest/profile_chain.py
python real_chain_backtest/backtest_real_chain.py
python real_chain_backtest/validate_outputs.py
```

## Contribution

Please include the data date, parameters, execution assumptions, command used, and validation output with every research change. See `CONTRIBUTING.md`.

## Risk notice

This repository is for education and research only. Options can expire worthless and may cause substantial losses. Nothing here is investment, tax, or trading advice.

