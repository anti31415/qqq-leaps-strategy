from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "QQQ_options.parquet"
OUTPUT = ROOT / "outputs"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    parquet = pq.ParquetFile(DATA)
    row_count = parquet.metadata.num_rows
    null_counts = {name: 0 for name in parquet.schema_arrow.names}
    minima: dict[str, object] = {}
    maxima: dict[str, object] = {}

    for group_index in range(parquet.metadata.num_row_groups):
        group = parquet.metadata.row_group(group_index)
        for column_index, name in enumerate(parquet.schema_arrow.names):
            stats = group.column(column_index).statistics
            if stats is None:
                continue
            null_counts[name] += stats.null_count or 0
            if stats.has_min_max:
                if name not in minima or stats.min < minima[name]:
                    minima[name] = stats.min
                if name not in maxima or stats.max > maxima[name]:
                    maxima[name] = stats.max

    dataset = ds.dataset(DATA, format="parquet")
    calls = dataset.to_table(
        columns=[
            "contract_id",
            "date",
            "expiration",
            "strike",
            "bid",
            "ask",
            "mark",
            "delta",
            "implied_volatility",
            "volume",
            "open_interest",
        ],
        filter=ds.field("type") == "call",
    ).to_pandas()
    calls["dte"] = (calls["expiration"] - calls["date"]).dt.days
    midpoint = (calls["bid"] + calls["ask"]) / 2
    calls["spread_pct"] = (calls["ask"] - calls["bid"]) / midpoint.where(midpoint > 0)

    window = calls[(calls["date"] >= "2020-12-16") & (calls["date"] <= "2025-12-15")]
    base = window[
        (window["dte"] >= 610)
        & (window["dte"] <= 850)
        & (window["delta"] >= 0.65)
        & (window["delta"] <= 0.75)
    ]
    tradable = base[(base["bid"] > 0) & (base["ask"] > 0) & (base["ask"] >= base["bid"])]
    tight = tradable[tradable["spread_pct"] <= 0.10]
    dte_v1 = tight[(tight["dte"] >= 630) & (tight["dte"] <= 730)]

    invalid_quotes = window[(window["bid"] < 0) | (window["ask"] < 0) | (window["ask"] < window["bid"])]
    duplicate_rows = int(
        calls.duplicated(subset=["date", "contract_id"], keep=False).sum()
    )

    summary = {
        "source_file": str(DATA),
        "file_size_bytes": DATA.stat().st_size,
        "row_count": row_count,
        "row_group_count": parquet.metadata.num_row_groups,
        "column_count": len(parquet.schema_arrow.names),
        "columns": [
            {"name": field.name, "type": str(field.type)} for field in parquet.schema_arrow
        ],
        "date_min": str(pd.Timestamp(minima["date"]).date()),
        "date_max": str(pd.Timestamp(maxima["date"]).date()),
        "expiration_max": str(pd.Timestamp(maxima["expiration"]).date()),
        "max_dte": int(calls["dte"].max()),
        "null_counts": null_counts,
        "null_rates": {name: count / row_count for name, count in null_counts.items()},
        "duplicate_date_contract_rows": duplicate_rows,
        "invalid_quote_rows_in_backtest_window": len(invalid_quotes),
        "five_year_window": {"start": "2020-12-16", "end": "2025-12-15"},
        "five_year_trade_dates": int(window["date"].nunique()),
        "leaps_610_850_delta_065_075_rows": len(base),
        "leaps_610_850_tradable_rows": len(tradable),
        "leaps_610_850_tight_rows": len(tight),
        "leaps_610_850_tight_trade_dates": int(tight["date"].nunique()),
        "dte_v1_630_730_tight_rows": len(dte_v1),
        "dte_v1_630_730_tight_trade_dates": int(dte_v1["date"].nunique()),
        "tight_candidate_delta_abs_error_median": float((tight["delta"] - 0.70).abs().median()),
        "tight_candidate_spread_pct_median": float(tight["spread_pct"].median()),
        "tight_candidate_spread_pct_p95": float(tight["spread_pct"].quantile(0.95)),
        "quality_assessment": "usable_with_caveats",
        "material_caveats": [
            "The public GitHub release ends on 2025-12-15, so it cannot cover the current trailing five years through 2026-08-12.",
            "The upstream repository states the original options-data provenance is undocumented; treat this as research data, not an exchange-grade audit source.",
            "The dataset is end-of-day, not intraday NBBO. Bid/ask scenarios therefore model EOD executions only.",
            "Vendor Greeks and implied volatility contain extreme values outside plausible ranges; selection is restricted to call delta 0.65-0.75 and valid positive quotes.",
        ],
    }

    (OUTPUT / "chain_quality_profile.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    pd.DataFrame(
        {
            "column": list(null_counts),
            "null_count": list(null_counts.values()),
            "null_rate": [null_counts[name] / row_count for name in null_counts],
        }
    ).to_csv(OUTPUT / "chain_null_profile.csv", index=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
