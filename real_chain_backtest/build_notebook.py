from __future__ import annotations

from pathlib import Path

import nbformat as nbf


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "outputs"


def main() -> None:
    notebook = nbf.v4.new_notebook()
    notebook["metadata"]["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    notebook["cells"] = [
        nbf.v4.new_markdown_cell(
            """## tl;dr

The public QQQ EOD option chain contains 15,345,882 rows from 2011-03-23 through 2025-12-15. The exact five-year test window is 2020-12-16 through 2025-12-15. Under the conservative ask-buy/bid-sell case, DTE V1 ends at $60,421 and the deployed LEAPS/short-call strategy ends at $66,083 from $20,000. Both paths have severe drawdowns, so the result is not low risk."""
        ),
        nbf.v4.new_markdown_cell(
            """## Context & Methods

This is an inspectable companion to `profile_chain.py` and `backtest_real_chain.py`. Entries select real QQQ call rows by DTE, vendor delta, and quoted spread. Four fill assumptions move from midpoint toward the adverse side of the observed EOD spread. QQQ prices come from the same GitHub release; VIX comes from Cboe.

### Key Assumptions

- EOD bid/ask is used; intraday path and queue priority are unavailable.
- Open positions are marked at midpoint.
- The deployed strategy's short calls settle at intrinsic value on expiration.
- Missing exact-day quotes delay an otherwise triggered exit.
- The GitHub data provenance is research-grade and not exchange-audited."""
        ),
        nbf.v4.new_markdown_cell("## Data"),
        nbf.v4.new_code_cell(
            """from pathlib import Path
import json
import pandas as pd

root = Path.cwd()
profile = json.loads((root / 'outputs' / 'chain_quality_profile.json').read_text(encoding='utf-8'))
pd.DataFrame({
    'measure': ['rows', 'date_min', 'date_max', 'max_dte', 'IV_nulls', 'DTE_V1_eligible_dates'],
    'value': [profile['row_count'], profile['date_min'], profile['date_max'], profile['max_dte'],
              profile['null_counts']['implied_volatility'], profile['dte_v1_630_730_tight_trade_dates']]
})"""
        ),
        nbf.v4.new_markdown_cell("## Results"),
        nbf.v4.new_code_cell(
            """metrics = pd.read_csv(root / 'outputs' / 'real_chain_scenario_metrics.csv')
cols = ['strategy', 'scenario', 'ending_equity', 'total_return', 'cagr',
        'annualized_volatility', 'sharpe_3pct', 'max_drawdown', 'closed_trade_count']
metrics[cols].sort_values(['strategy', 'scenario']).reset_index(drop=True)"""
        ),
        nbf.v4.new_code_cell(
            """metrics.pivot(index='scenario', columns='strategy', values='ending_equity')"""
        ),
        nbf.v4.new_markdown_cell(
            """## Takeaways

- DTE V1 is less dependent on short-option execution, and its ending value falls monotonically as fills worsen.
- The deployed strategy has higher midpoint performance, but the short-call overlay makes it much more sensitive to bid/ask and missing-contract observations.
- Scenario results are path-dependent because fill prices affect available cash, entry quantity, and profit-trigger dates. Intermediate scenarios therefore need not be perfectly monotonic.
- Treat the output as a realistic EOD stress test, not proof of executable intraday performance."""
        ),
    ]
    target = ROOT / "qqq_real_chain_backtest.ipynb"
    nbf.write(notebook, target)
    print(target)


if __name__ == "__main__":
    main()
