from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
CSV_PATH = LOG_DIR / "monitoring_runs.csv"
TXT_PATH = LOG_DIR / "DAILY_CHECK_LOG.txt"


def migrate() -> None:
    if not CSV_PATH.exists():
        return
    rows = list(csv.DictReader(CSV_PATH.open("r", encoding="utf-8-sig", newline="")))
    if not rows:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    existing = TXT_PATH.read_text(encoding="utf-8") if TXT_PATH.exists() else ""
    marker = "Migrated historical monitoring records"
    if marker in existing:
        return

    lines = [
        "=" * 88,
        marker,
        "=" * 88,
    ]
    for row in rows:
        lines.extend(
            [
                f"Run time: {row.get('run_timestamp', '')}",
                f"Command: {row.get('command', '')}",
                f"Status: {row.get('status', '')}",
                f"Place orders requested: {row.get('place_orders_requested', '')}",
                f"Dry run: {row.get('dry_run', '')}",
                "Checked indicators:",
                f"- Signal date: {row.get('signal_date', '')}",
                f"- QQQ close: {row.get('qqq_close', '')}",
                f"- QQQ RSI(14): {row.get('qqq_rsi', '')}",
                f"- VIX close: {row.get('vix_close', '')}",
                "Decision:",
                f"- Regime: {row.get('regime_name', '')}",
                f"- Buy reason: {row.get('buy_reason', '')}",
                f"- Planned actions: {row.get('actions_count', '')}",
                f"- Submitted orders: {row.get('submitted_orders_count', '')}",
                f"- Warnings: {row.get('warnings', '')}",
                f"- Error: {row.get('error', '')}",
                "",
            ]
        )
    with TXT_PATH.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


if __name__ == "__main__":
    migrate()
