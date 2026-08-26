from __future__ import annotations

from typing import Any
from urllib.parse import quote

from autotrade.http import HttpClient


def fetch_yahoo_daily_bars(symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    client = HttpClient()
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
    response = client.request(
        "GET",
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        params={
            "interval": "1d",
            "period1": int(__import__("datetime").datetime.fromisoformat(f"{start}T00:00:00+00:00").timestamp()),
            "period2": int(__import__("datetime").datetime.fromisoformat(f"{end}T23:59:59+00:00").timestamp()),
            "includeAdjustedClose": "true",
        },
    ).data
    result = ((response or {}).get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"No Yahoo bars returned for {symbol}")
    chart = result[0]
    timestamps = chart.get("timestamp") or []
    quote_items = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
    adj_items = ((chart.get("indicators") or {}).get("adjclose") or [{}])[0]
    closes = quote_items.get("close") or []
    adj_closes = adj_items.get("adjclose") or []
    rows: list[dict[str, Any]] = []
    for index, ts in enumerate(timestamps):
        close = closes[index] if index < len(closes) else None
        adj_close = adj_closes[index] if index < len(adj_closes) else close
        if close is None:
            continue
        date_value = __import__("datetime").datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
        rows.append(
            {
                "date": date_value,
                "close": float(close),
                "adj_close": float(adj_close if adj_close is not None else close),
            }
        )
    return rows

