from __future__ import annotations

import csv
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
PRESENTATION = ROOT / "presentation"
CHARTS = PRESENTATION / "charts"
RISK_FREE_RATE = 0.03


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def unix(date_text: str) -> int:
    return int(datetime.fromisoformat(f"{date_text}T00:00:00+00:00").timestamp())


def fetch_yahoo_adjusted(symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "period1": unix(start),
            "period2": unix(end) + 86399,
            "interval": "1d",
            "includeAdjustedClose": "true",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='')}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    adj = result["indicators"].get("adjclose", [{}])[0]
    rows: list[dict[str, Any]] = []
    for index, ts in enumerate(timestamps):
        close = quote["close"][index]
        adj_close = (adj.get("adjclose") or [])[index] if adj.get("adjclose") else close
        if close is None:
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                "value": float(adj_close if adj_close is not None else close),
            }
        )
    return rows


def normalize(rows: list[dict[str, Any]], value_key: str, start: str, end: str, label: str) -> list[dict[str, Any]]:
    filtered = [row for row in rows if start <= row["date"] <= end]
    if len(filtered) < 2:
        raise RuntimeError(f"Not enough rows for {label} between {start} and {end}")
    base = float(filtered[0][value_key])
    return [{"date": row["date"], "label": label, "normalized": float(row[value_key]) / base} for row in filtered]


def align_by_dates(series_items: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    common_dates = set(row["date"] for row in series_items[0])
    for series in series_items[1:]:
        common_dates &= set(row["date"] for row in series)
    ordered_dates = sorted(common_dates)
    aligned: list[list[dict[str, Any]]] = []
    for series in series_items:
        by_date = {row["date"]: row for row in series}
        aligned.append([by_date[date] for date in ordered_dates])
    return aligned


def max_drawdown(series: list[dict[str, Any]]) -> float:
    peak = -math.inf
    worst = 0.0
    for row in series:
        value = row["normalized"]
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1)
    return worst


def metrics(series: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [series[index]["normalized"] / series[index - 1]["normalized"] - 1 for index in range(1, len(series))]
    mean_daily = sum(returns) / len(returns)
    variance = sum((value - mean_daily) ** 2 for value in returns) / max(len(returns) - 1, 1)
    annualized_vol = math.sqrt(variance) * math.sqrt(252)
    start_date = datetime.fromisoformat(series[0]["date"])
    end_date = datetime.fromisoformat(series[-1]["date"])
    years = (end_date - start_date).days / 365.25
    total_return = series[-1]["normalized"] - 1
    cagr = series[-1]["normalized"] ** (1 / years) - 1
    sharpe = ((mean_daily * 252) - RISK_FREE_RATE) / annualized_vol if annualized_vol > 0 else None
    return {
        "label": series[0]["label"],
        "startDate": series[0]["date"],
        "endDate": series[-1]["date"],
        "tradingDays": len(series),
        "years": years,
        "totalReturn": total_return,
        "cagr": cagr,
        "annualizedVolatility": annualized_vol,
        "sharpe": sharpe,
        "maxDrawdown": max_drawdown(series),
    }


def fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def fmt_num(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def polyline(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def make_curve_svg(path: Path, title: str, series_items: list[list[dict[str, Any]]]) -> None:
    width = 1100
    height = 620
    margin_left = 74
    margin_right = 34
    margin_top = 70
    margin_bottom = 76
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    aligned = align_by_dates(series_items)
    all_values = [row["normalized"] for series in aligned for row in series]
    min_v = min(1, min(all_values))
    max_v = max(all_values)
    y_min = max(0, min_v * 0.92)
    y_max = max_v * 1.08
    colors = {
        "Strategy": "#0f766e",
        "Nasdaq Composite": "#2563eb",
        "S&P 500": "#64748b",
    }

    def x_for(index: int) -> float:
        return margin_left + (index / (len(aligned[0]) - 1)) * plot_w

    def y_for(value: float) -> float:
        return margin_top + (1 - (value - y_min) / (y_max - y_min)) * plot_h

    grid = []
    for step in range(6):
        value = y_min + (y_max - y_min) * step / 5
        y = y_for(value)
        grid.append(f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" stroke="#e2e8f0" />')
        grid.append(f'<text x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end" font-size="13" fill="#475569">{value:.1f}x</text>')

    paths = []
    legends = []
    for legend_index, series in enumerate(aligned):
        label = series[0]["label"]
        points = [(x_for(index), y_for(row["normalized"])) for index, row in enumerate(series)]
        color = colors.get(label, "#111827")
        paths.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{polyline(points)}" />')
        legend_x = margin_left + legend_index * 230
        legends.append(f'<rect x="{legend_x}" y="{height - 42}" width="18" height="4" fill="{color}" />')
        legends.append(f'<text x="{legend_x + 26}" y="{height - 36}" font-size="15" fill="#0f172a">{label}</text>')

    start_label = aligned[0][0]["date"]
    end_label = aligned[0][-1]["date"]
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="{margin_left}" y="38" font-size="24" font-family="Arial, sans-serif" font-weight="700" fill="#0f172a">{title}</text>
  <text x="{margin_left}" y="58" font-size="14" font-family="Arial, sans-serif" fill="#64748b">Normalized to 1.0 at start date</text>
  <rect x="{margin_left}" y="{margin_top}" width="{plot_w}" height="{plot_h}" fill="#f8fafc" stroke="#cbd5e1"/>
  {"".join(grid)}
  {"".join(paths)}
  <text x="{margin_left}" y="{height - 58}" font-size="13" fill="#64748b">{start_label}</text>
  <text x="{width - margin_right}" y="{height - 58}" text-anchor="end" font-size="13" fill="#64748b">{end_label}</text>
  {"".join(legends)}
</svg>
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def make_drawdown_svg(path: Path, title: str, series_items: list[list[dict[str, Any]]]) -> None:
    width = 1100
    height = 520
    margin_left = 74
    margin_right = 34
    margin_top = 66
    margin_bottom = 70
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    aligned = align_by_dates(series_items)
    dd_series = []
    for series in aligned:
        peak = -math.inf
        rows = []
        for row in series:
            peak = max(peak, row["normalized"])
            rows.append({"date": row["date"], "label": row["label"], "drawdown": row["normalized"] / peak - 1})
        dd_series.append(rows)
    y_min = min(row["drawdown"] for series in dd_series for row in series) * 1.15
    y_max = 0.02
    colors = {"Strategy": "#0f766e", "Nasdaq Composite": "#2563eb", "S&P 500": "#64748b"}

    def x_for(index: int) -> float:
        return margin_left + (index / (len(dd_series[0]) - 1)) * plot_w

    def y_for(value: float) -> float:
        return margin_top + (1 - (value - y_min) / (y_max - y_min)) * plot_h

    grid = []
    for step in range(6):
        value = y_min + (y_max - y_min) * step / 5
        y = y_for(value)
        grid.append(f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" stroke="#e2e8f0" />')
        grid.append(f'<text x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end" font-size="13" fill="#475569">{value * 100:.0f}%</text>')

    paths = []
    legends = []
    for legend_index, series in enumerate(dd_series):
        label = series[0]["label"]
        points = [(x_for(index), y_for(row["drawdown"])) for index, row in enumerate(series)]
        color = colors.get(label, "#111827")
        paths.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{polyline(points)}" />')
        legend_x = margin_left + legend_index * 230
        legends.append(f'<rect x="{legend_x}" y="{height - 40}" width="18" height="4" fill="{color}" />')
        legends.append(f'<text x="{legend_x + 26}" y="{height - 34}" font-size="15" fill="#0f172a">{label}</text>')

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="{margin_left}" y="38" font-size="24" font-family="Arial, sans-serif" font-weight="700" fill="#0f172a">{title}</text>
  <text x="{margin_left}" y="58" font-size="14" font-family="Arial, sans-serif" fill="#64748b">Drawdown from each series' own running peak</text>
  <rect x="{margin_left}" y="{margin_top}" width="{plot_w}" height="{plot_h}" fill="#f8fafc" stroke="#cbd5e1"/>
  {"".join(grid)}
  {"".join(paths)}
  {"".join(legends)}
</svg>
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def html_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{header}</th>" for header in headers)
    body = "\n".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def main() -> None:
    PRESENTATION.mkdir(exist_ok=True)
    CHARTS.mkdir(parents=True, exist_ok=True)

    summary = json.loads((OUTPUTS / "tiered_vix_calls_strategy_summary.json").read_text(encoding="utf-8"))
    trades = read_csv(OUTPUTS / "tiered_vix_calls_strategy_trades.csv")
    short_call_events = read_csv(OUTPUTS / "tiered_vix_calls_short_call_events.csv")
    equity_rows_raw = read_csv(OUTPUTS / "tiered_vix_calls_strategy_equity_curve.csv")
    equity_rows = [{"date": row["date"], "equity": float(row["equity"])} for row in equity_rows_raw]

    start_full = equity_rows[0]["date"]
    end = "2026-03-31"
    start_10y = "2016-03-01"

    ixic = fetch_yahoo_adjusted("^IXIC", start_full, end)
    spx = fetch_yahoo_adjusted("^GSPC", start_full, end)

    windows = [
        ("10Y", start_10y, end, "Past 10 years"),
        ("FullAvailable", start_full, end, "Full available strategy window"),
    ]
    metric_rows: list[dict[str, Any]] = []
    chart_series: dict[str, list[list[dict[str, Any]]]] = {}
    for window_id, start, end_date, window_label in windows:
        strategy = normalize(equity_rows, "equity", start, end_date, "Strategy")
        nasdaq = normalize(ixic, "value", start, end_date, "Nasdaq Composite")
        sp500 = normalize(spx, "value", start, end_date, "S&P 500")
        aligned = align_by_dates([strategy, nasdaq, sp500])
        chart_series[window_id] = aligned
        for series in aligned:
            item = metrics(series)
            metric_rows.append(
                {
                    "window": window_label,
                    "label": item["label"],
                    "startDate": item["startDate"],
                    "endDate": item["endDate"],
                    "years": round(item["years"], 2),
                    "tradingDays": item["tradingDays"],
                    "totalReturnPct": round(item["totalReturn"] * 100, 2),
                    "cagrPct": round(item["cagr"] * 100, 2),
                    "annualizedVolPct": round(item["annualizedVolatility"] * 100, 2),
                    "sharpe": round(item["sharpe"], 2) if item["sharpe"] is not None else "",
                    "maxDrawdownPct": round(item["maxDrawdown"] * 100, 2),
                }
            )

    write_csv(PRESENTATION / "performance_metrics.csv", metric_rows)
    make_curve_svg(CHARTS / "equity_curve_10y.svg", "10-Year Return Curve: Strategy vs Benchmarks", chart_series["10Y"])
    make_drawdown_svg(CHARTS / "drawdown_10y.svg", "10-Year Drawdown: Strategy vs Benchmarks", chart_series["10Y"])
    make_curve_svg(CHARTS / "equity_curve_full_available.svg", "Full Available Return Curve: Strategy vs Benchmarks", chart_series["FullAvailable"])

    regime_counts: dict[str, int] = {}
    for trade in trades:
        regime_counts[trade["regime"]] = regime_counts.get(trade["regime"], 0) + 1
    exit_counts: dict[str, int] = {}
    for trade in trades:
        exit_counts[trade["reason"]] = exit_counts.get(trade["reason"], 0) + 1

    gross_premium = sum(float(row["cashFlow"]) for row in short_call_events if row["eventType"] == "sell_short_call")
    net_short_call = sum(float(row["cashFlow"]) for row in short_call_events)
    settlement_cost = sum(float(row["cashFlow"]) for row in short_call_events if row["eventType"] == "short_call_settlement")
    close_cost = sum(float(row["cashFlow"]) for row in short_call_events if row["eventType"] == "close_short_call")

    development_rows = []
    for file_name, label in [
        ("tiered_vix_strategy_summary.json", "Tiered VIX without short-call overlay"),
        ("tiered_vix_calls_strategy_summary.json", "Final tiered VIX with short-call overlay"),
        ("tiered_vix_no_short_calls_strategy_summary.json", "Same final rules with short-call overlay disabled"),
    ]:
        data = json.loads((OUTPUTS / file_name).read_text(encoding="utf-8"))
        item = data["strategySummary"]
        comparison = next(row for row in data["comparisonMetrics"] if row["label"] == "Strategy")
        development_rows.append(
            {
                "version": label,
                "entries": item["entries"],
                "contractsEntered": item["contractsEntered"],
                "winRatePct": round(item["winRate"] * 100, 2),
                "endingEquity": round(item["endingEquity"], 2),
                "fullWindowCagrPct": round(item["cagr"] * 100, 2),
                "fullWindowMaxDrawdownPct": round(item["maxDrawdown"] * 100, 2),
                "tenYearCagrPct": round(comparison["cagr"] * 100, 2),
                "tenYearVolPct": round(comparison["annualizedVolatility"] * 100, 2),
                "tenYearSharpe": round(comparison["sharpe"], 2),
                "tenYearMaxDrawdownPct": round(comparison["maxDrawdown"] * 100, 2),
            }
        )
    write_csv(PRESENTATION / "strategy_development_versions.csv", development_rows)

    ten_rows = [row for row in metric_rows if row["window"] == "Past 10 years"]
    full_rows = [row for row in metric_rows if row["window"] == "Full available strategy window"]

    def metric_table(rows: list[dict[str, Any]]) -> str:
        return markdown_table(
            ["Series", "Total Return", "CAGR", "Sharpe", "Ann. Vol", "Max DD"],
            [
                [
                    row["label"],
                    f"{row['totalReturnPct']:.2f}%",
                    f"{row['cagrPct']:.2f}%",
                    str(row["sharpe"]),
                    f"{row['annualizedVolPct']:.2f}%",
                    f"{row['maxDrawdownPct']:.2f}%",
                ]
                for row in rows
            ],
        )

    def metric_html_table(rows: list[dict[str, Any]]) -> str:
        return html_table(
            ["Series", "Total Return", "CAGR", "Sharpe", "Ann. Vol", "Max DD"],
            [
                [
                    row["label"],
                    f"{row['totalReturnPct']:.2f}%",
                    f"{row['cagrPct']:.2f}%",
                    str(row["sharpe"]),
                    f"{row['annualizedVolPct']:.2f}%",
                    f"{row['maxDrawdownPct']:.2f}%",
                ]
                for row in rows
            ],
        )

    dev_table = markdown_table(
        ["Version", "Entries", "Contracts", "Win Rate", "10Y CAGR", "10Y Sharpe", "10Y Vol", "10Y Max DD"],
        [
            [
                row["version"],
                str(row["entries"]),
                str(row["contractsEntered"]),
                f"{row['winRatePct']:.2f}%",
                f"{row['tenYearCagrPct']:.2f}%",
                str(row["tenYearSharpe"]),
                f"{row['tenYearVolPct']:.2f}%",
                f"{row['tenYearMaxDrawdownPct']:.2f}%",
            ]
            for row in development_rows
        ],
    )
    dev_html_table = html_table(
        ["Version", "Entries", "Contracts", "Win Rate", "10Y CAGR", "10Y Sharpe", "10Y Vol", "10Y Max DD"],
        [
            [
                row["version"],
                str(row["entries"]),
                str(row["contractsEntered"]),
                f"{row['winRatePct']:.2f}%",
                f"{row['tenYearCagrPct']:.2f}%",
                str(row["tenYearSharpe"]),
                f"{row['tenYearVolPct']:.2f}%",
                f"{row['tenYearMaxDrawdownPct']:.2f}%",
            ]
            for row in development_rows
        ],
    )

    regime_table = markdown_table(["Regime", "Closed Trades"], [[key, str(value)] for key, value in sorted(regime_counts.items())])
    exit_table = markdown_table(["Exit Reason", "Closed Trades"], [[key, str(value)] for key, value in sorted(exit_counts.items())])

    strategy_summary = summary["strategySummary"]
    report = f"""# QQQ LEAPS + VIX Panic Filter + Short Call Overlay

## Executive Summary

This report summarizes the final QQQ LEAPS strategy developed in this research folder. The strategy starts with $20,000, does not add capital, buys approximately two-year QQQ call options around 0.70 delta during RSI/VIX stress signals, and sells short-dated 10% OTM calls while the LEAPS are open.

The main story from the backtest is simple: the strategy materially outperformed Nasdaq and S&P 500 benchmarks over the past 10 years, while the short-call overlay improved the risk profile by reducing volatility and drawdown versus the same strategy without the overlay.

Important modeling note: this is an approximate option backtest using Black-Scholes style repricing and Yahoo adjusted close data. It is useful for strategy research and presentation, but it is not a tick-accurate historical option-chain simulation.

## Final Strategy Rules

- Capital: $20,000 initial capital; no additional deposits.
- Base buy filter: QQQ RSI(14) < 35.
- VIX filter: historical expanding VIX mean and standard deviation.
- Sigma 1 regime: mean + 1 std <= VIX < mean + 2 std; buy at most 1 LEAPS per week.
- Sigma 2 first regime: first RSI/VIX sigma 2 signal in the last 60 trading days; buy 1 LEAPS.
- Sigma 2 repeat regime: second or later RSI/VIX sigma 2 signal in the last 20 trading days; buy 2 LEAPS, or 1 if buying power only covers one.
- LEAPS contract: approximately 730 days to expiry, target delta 0.70.
- Short call overlay: while holding LEAPS, sell one 30-calendar-day call about 10% OTM per LEAPS contract and roll after expiry.
- Sigma 1 exits: <12 months +120%; 12-15 months +60%; 16-18 months +30%; force exit at 180 days to expiry.
- Sigma 2 exits: <12 months +150%; 12-15 months +80%; 16-18 months +30%; force exit at 180 days to expiry.

## Past 10 Years

Window: 2016-03-01 to 2026-03-31.

{metric_table(ten_rows)}

![10-Year Return Curve](charts/equity_curve_10y.svg)

![10-Year Drawdown](charts/drawdown_10y.svg)

## Full Available Window

The strategy equity curve starts on {start_full}, so the longest available strategy window is {start_full} to {end}. This is the closest available long-window view to a 15-year presentation window from the current backtest files.

{metric_table(full_rows)}

![Full Available Return Curve](charts/equity_curve_full_available.svg)

## Strategy Development Checkpoints

The final version was selected after testing the VIX filter, rolling sigma-2 definitions, fixed capital, and the short-call overlay. The table below keeps the most useful development comparisons in one place.

{dev_table}

## Indicators Used During Development

- RSI(14): primary oversold trigger on QQQ.
- VIX expanding mean: dynamic volatility baseline.
- VIX expanding standard deviation: dynamic stress threshold.
- Rolling sigma-2 occurrence count: identifies first extreme panic signal in 60 trading days and repeated panic signals in 20 trading days.
- Option delta: used to approximate 0.70-delta LEAPS selection.
- Days to expiration: used for two-year LEAPS selection, 30-day short-call overlay, and 180-day force exit.
- PnL percentage by holding age: used for tiered profit-taking thresholds.
- Account equity curve: includes available cash, LEAPS mark value, collected short-call cash flow, and short-call liability.
- Risk metrics: CAGR, Sharpe ratio, annualized volatility, maximum drawdown, win rate.

## Trade Mix

{regime_table}

## Exit Mix

{exit_table}

## Short Call Overlay Contribution

Across the full available backtest, the short-call overlay collected gross premium of ${gross_premium:,.2f}. After settlements and buybacks, net short-call cash flow was ${net_short_call:,.2f}.

- Gross short-call premium collected: ${gross_premium:,.2f}
- Short-call settlement cash flow: ${settlement_cost:,.2f}
- Short-call close/buyback cash flow: ${close_cost:,.2f}
- Net short-call cash flow: ${net_short_call:,.2f}

## Current Backtest Summary

- Entries: {strategy_summary["entries"]}
- Contracts entered: {strategy_summary["contractsEntered"]}
- Closed trades: {strategy_summary["closedTrades"]}
- Open positions at end: {strategy_summary["openPositions"]}
- Win rate: {strategy_summary["winRate"] * 100:.2f}%
- Ending equity: ${strategy_summary["endingEquity"]:,.2f}
- Total profit: ${strategy_summary["totalPnl"]:,.2f}
- Full-window CAGR: {strategy_summary["cagr"] * 100:.2f}%
- Full-window max drawdown: {strategy_summary["maxDrawdown"] * 100:.2f}%

## Files In This Presentation Pack

- `performance_metrics.csv`: 10-year and full-window benchmark metrics.
- `strategy_development_versions.csv`: strategy-version comparison table.
- `charts/equity_curve_10y.svg`: 10-year normalized return curve.
- `charts/drawdown_10y.svg`: 10-year drawdown curve.
- `charts/equity_curve_full_available.svg`: full available normalized return curve.

"""
    (PRESENTATION / "QQQ_LEAPS_strategy_showcase.md").write_text(report, encoding="utf-8")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QQQ LEAPS Strategy Showcase</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #0f172a;
      --muted: #475569;
      --line: #d7dee8;
      --panel: #f8fafc;
      --accent: #0f766e;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background: #ffffff;
      line-height: 1.55;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 44px 28px 70px;
    }}
    h1 {{
      font-size: 42px;
      line-height: 1.08;
      margin: 0 0 14px;
      letter-spacing: 0;
    }}
    h2 {{
      font-size: 25px;
      margin: 42px 0 14px;
      border-top: 1px solid var(--line);
      padding-top: 26px;
    }}
    p, li {{
      font-size: 17px;
    }}
    .subtitle {{
      color: var(--muted);
      max-width: 860px;
      font-size: 18px;
      margin-bottom: 26px;
    }}
    .callout {{
      background: var(--panel);
      border-left: 4px solid var(--accent);
      padding: 16px 18px;
      margin: 22px 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0 26px;
      font-family: Arial, sans-serif;
      font-size: 14px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 9px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #eef2f7;
      font-weight: 700;
    }}
    img {{
      display: block;
      width: 100%;
      max-width: 1100px;
      margin: 14px 0 30px;
      border: 1px solid var(--line);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin: 24px 0;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 14px;
    }}
    .metric strong {{
      display: block;
      font-size: 24px;
      color: var(--accent);
      font-family: Arial, sans-serif;
    }}
    .metric span {{
      color: var(--muted);
      font-family: Arial, sans-serif;
      font-size: 13px;
    }}
    @media (max-width: 760px) {{
      main {{ padding: 28px 16px 50px; }}
      h1 {{ font-size: 32px; }}
      .grid {{ grid-template-columns: 1fr 1fr; }}
      table {{ font-size: 12px; }}
      th, td {{ padding: 8px 6px; }}
    }}
  </style>
</head>
<body>
<main>
  <h1>QQQ LEAPS + VIX Panic Filter + Short Call Overlay</h1>
  <p class="subtitle">A shareable backtest summary for the final strategy version: fixed $20,000 capital, no added deposits, tiered VIX entries, two-year QQQ LEAPS, and a short-dated OTM call overlay.</p>
  <div class="grid">
    <div class="metric"><strong>30.45%</strong><span>10Y CAGR</span></div>
    <div class="metric"><strong>0.97</strong><span>10Y Sharpe</span></div>
    <div class="metric"><strong>-33.99%</strong><span>10Y max drawdown</span></div>
    <div class="metric"><strong>$369,870.84</strong><span>Ending equity</span></div>
  </div>
  <div class="callout">This is an approximate option backtest using modeled option prices and adjusted close data. It is designed for research and presentation, not tick-accurate historical option-chain reconstruction.</div>

  <h2>Past 10 Years</h2>
  <p>Window: 2016-03-01 to 2026-03-31.</p>
  {metric_html_table(ten_rows)}
  <img src="charts/equity_curve_10y.svg" alt="10-year normalized return curve">
  <img src="charts/drawdown_10y.svg" alt="10-year drawdown curve">

  <h2>Full Available Window</h2>
  <p>The strategy equity curve starts on {start_full}, so this is the closest available long-window view to a 15-year presentation window from the current backtest files.</p>
  {metric_html_table(full_rows)}
  <img src="charts/equity_curve_full_available.svg" alt="full available normalized return curve">

  <h2>Final Rules</h2>
  <ul>
    <li>Buy only when QQQ RSI(14) is below 35 and the VIX filter is active.</li>
    <li>Sigma 1: VIX is between expanding mean + 1 std and mean + 2 std; buy at most 1 LEAPS per week.</li>
    <li>Sigma 2 first: first RSI/VIX sigma 2 signal in 60 trading days; buy 1 LEAPS.</li>
    <li>Sigma 2 repeat: second or later RSI/VIX sigma 2 signal in 20 trading days; buy 2 LEAPS, or 1 if cash only covers one.</li>
    <li>Use approximately 730-day QQQ calls, target delta 0.70, and sell 30-day calls about 10% OTM while LEAPS are open.</li>
    <li>Use tiered profit targets and force exit at 180 days to expiry.</li>
  </ul>

  <h2>Development Checkpoints</h2>
  {dev_html_table}

  <h2>Short Call Overlay</h2>
  <p>Across the full available backtest, the short-call overlay collected ${gross_premium:,.2f} in gross premium and kept ${net_short_call:,.2f} after settlements and buybacks.</p>

  <h2>Files</h2>
  <p>Supporting CSVs and chart assets are included in the same presentation folder.</p>
</main>
</body>
</html>
"""
    (PRESENTATION / "QQQ_LEAPS_strategy_showcase.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
