from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


CSV_HEADERS = [
    "run_timestamp",
    "command",
    "status",
    "place_orders_requested",
    "dry_run",
    "signal_date",
    "qqq_close",
    "qqq_rsi",
    "vix_close",
    "regime_name",
    "buy_reason",
    "actions_count",
    "submitted_orders_count",
    "warnings_count",
    "warnings",
    "managed_leaps_count",
    "pending_orders_count",
    "entry_history_count",
    "error",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _append_csv(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in CSV_HEADERS})


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str))
        handle.write("\n")


def _append_txt(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    signal = record.get("signal") or {}
    lines = [
        "=" * 88,
        f"Run time: {record.get('run_timestamp', '')}",
        f"Command: {record.get('command', '')}",
        f"Status: {record.get('status', '')}",
        f"Place orders requested: {record.get('place_orders_requested', '')}",
        f"Dry run: {record.get('dry_run', '')}",
        "",
        "Checked indicators:",
        f"- QQQ close: {signal.get('qqq_close', record.get('qqq_close', ''))}",
        f"- QQQ RSI(14): {signal.get('qqq_rsi', record.get('qqq_rsi', ''))}",
        f"- VIX close: {signal.get('vix_close', record.get('vix_close', ''))}",
        f"- VIX expanding mean: {signal.get('vix_mean', '')}",
        f"- VIX expanding std: {signal.get('vix_std', '')}",
        f"- Sigma 1 threshold: {signal.get('sigma1_threshold', '')}",
        f"- Sigma 2 threshold: {signal.get('sigma2_threshold', '')}",
        f"- Sigma 2 count in 60 trading days: {signal.get('sigma2_count_60', '')}",
        f"- Sigma 2 count in 20 trading days: {signal.get('sigma2_count_20', '')}",
        "",
        "Decision:",
        f"- Regime: {signal.get('regime_name', record.get('regime_name', ''))}",
        f"- Buy reason: {signal.get('buy_reason', record.get('buy_reason', ''))}",
        f"- Planned actions: {record.get('actions_count', 0)}",
        f"- Submitted orders: {record.get('submitted_orders_count', 0)}",
        f"- Warnings: {record.get('warnings', [])}",
        f"- Error: {record.get('error', '')}",
        "",
    ]
    actions = record.get("actions") or []
    submitted_orders = record.get("submitted_orders") or []
    if actions:
        lines.append("Planned action details:")
        for action in actions:
            lines.append(f"- {action}")
        lines.append("")
    if submitted_orders:
        lines.append("Submitted order details:")
        for order in submitted_orders:
            lines.append(f"- {order}")
        lines.append("")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def _state_counts(state_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not state_summary:
        return {
            "managed_leaps_count": "",
            "pending_orders_count": "",
            "entry_history_count": "",
        }
    after = state_summary.get("after") if isinstance(state_summary.get("after"), dict) else state_summary
    return {
        "managed_leaps_count": after.get("managed_leaps_count", ""),
        "pending_orders_count": after.get("pending_orders_count", ""),
        "entry_history_count": after.get("entry_history_count", ""),
    }


def write_monitoring_record(
    *,
    log_dir: Path,
    command: str,
    status: str,
    place_orders_requested: bool,
    dry_run: bool,
    signal: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    actions: list[dict[str, Any]] | None = None,
    submitted_orders: list[dict[str, Any]] | None = None,
    state_summary: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    warnings = warnings or []
    actions = actions or []
    submitted_orders = submitted_orders or []
    signal = signal or {}

    timestamp = now_iso()
    state_counts = _state_counts(state_summary)
    csv_row = {
        "run_timestamp": timestamp,
        "command": command,
        "status": status,
        "place_orders_requested": str(place_orders_requested).lower(),
        "dry_run": str(dry_run).lower(),
        "signal_date": signal.get("as_of_date", ""),
        "qqq_close": signal.get("qqq_close", ""),
        "qqq_rsi": signal.get("qqq_rsi", ""),
        "vix_close": signal.get("vix_close", ""),
        "regime_name": signal.get("regime_name", ""),
        "buy_reason": signal.get("buy_reason", ""),
        "actions_count": len(actions),
        "submitted_orders_count": len(submitted_orders),
        "warnings_count": len(warnings),
        "warnings": " | ".join(warnings),
        "error": error,
        **state_counts,
    }
    json_record = {
        **csv_row,
        "signal": signal,
        "warnings": warnings,
        "actions": actions,
        "submitted_orders": submitted_orders,
        "state_summary": state_summary or {},
    }

    _append_csv(log_dir / "monitoring_runs.csv", csv_row)
    _append_jsonl(log_dir / "monitoring_runs.jsonl", json_record)
    _append_txt(log_dir / "DAILY_CHECK_LOG.txt", json_record)
    return json_record
