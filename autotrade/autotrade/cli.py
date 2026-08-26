from __future__ import annotations

import argparse
import json
import sys

from autotrade.brokers.alpaca import AlpacaBroker
from autotrade.config import load_settings
from autotrade.monitoring import write_monitoring_record
from autotrade.notifier import build_run_summary, send_email_notification
from autotrade.state import clone_state, load_state, save_state
from autotrade.strategy import apply_submitted_orders, latest_signal_snapshot, plan_next_action


def _print(data: object) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _notify(settings: object, record: dict[str, object]) -> dict[str, object]:
    submitted_count = int(record.get("submitted_orders_count") or 0)
    if submitted_count <= 0:
        return {"enabled": settings.email_notify_enabled, "sent": False, "reason": "no_submitted_orders"}
    subject_status = record.get("status", "unknown")
    signal = record.get("signal") if isinstance(record.get("signal"), dict) else {}
    subject = f"QQQ LEAPS trade submitted: {subject_status} {signal.get('as_of_date', '')}".strip()
    return send_email_notification(settings, subject, build_run_summary(record))


def cmd_doctor() -> int:
    settings = load_settings()
    result: dict[str, object] = {
        "config": {
            "signal_symbol": settings.signal_symbol,
            "vix_symbol": settings.vix_symbol,
            "dry_run": settings.dry_run,
            "state_path": str(settings.state_path),
            "log_dir": str(settings.log_dir),
            "alpaca_has_keys": bool(settings.alpaca_api_key_id and settings.alpaca_api_secret_key),
        },
        "broker": {},
        "state": {},
    }
    state = load_state(settings.state_path, settings.strategy_version)
    result["state"] = {
        "exists": settings.state_path.exists(),
        "managed_leaps_count": len(state["managed_leaps"]),
        "pending_orders_count": len(state["pending_orders"]),
    }
    if settings.alpaca_api_key_id and settings.alpaca_api_secret_key:
        try:
            result["broker"] = AlpacaBroker(settings).healthcheck()
        except Exception as exc:  # noqa: BLE001
            result["broker"] = {"status": "error", "message": str(exc)}
    else:
        result["broker"] = {"status": "missing_credentials"}
    _print(result)
    return 0


def cmd_alpaca_account() -> int:
    settings = load_settings()
    broker = AlpacaBroker(settings)
    _print(
        {
            "account": broker.get_account(),
            "clock": broker.get_clock(),
            "positions": broker.get_positions(),
            "open_orders": broker.get_orders(status="open"),
        }
    )
    return 0


def cmd_signal() -> int:
    settings = load_settings()
    broker = AlpacaBroker(settings)
    signal = latest_signal_snapshot(broker, settings)
    _print(signal.__dict__)
    return 0


def cmd_plan(place_orders: bool) -> int:
    settings = load_settings()
    broker = AlpacaBroker(settings)
    state = load_state(settings.state_path, settings.strategy_version)
    try:
        plan = plan_next_action(broker, settings, state)
    except Exception as exc:  # noqa: BLE001
        record = write_monitoring_record(
            log_dir=settings.log_dir,
            command="plan",
            status="error",
            place_orders_requested=place_orders,
            dry_run=settings.dry_run,
            error=str(exc),
        )
        _notify(settings, record)
        raise

    if not place_orders or settings.dry_run:
        actions = [action.__dict__ for action in plan.actions]
        record = write_monitoring_record(
            log_dir=settings.log_dir,
            command="plan",
            status="preview",
            place_orders_requested=place_orders,
            dry_run=settings.dry_run,
            signal=plan.signal,
            warnings=plan.warnings,
            actions=actions,
            state_summary=plan.state_summary,
        )
        email_result = _notify(settings, record)
        _print(
            {
                "signal": plan.signal,
                "warnings": plan.warnings,
                "unmanaged_positions": plan.unmanaged_positions,
                "open_orders": plan.open_orders,
                "actions": actions,
                "state_summary": plan.state_summary,
                "place_orders_requested": place_orders,
                "dry_run": settings.dry_run,
                "monitoring_log": {
                    "csv": str(settings.log_dir / "monitoring_runs.csv"),
                    "jsonl": str(settings.log_dir / "monitoring_runs.jsonl"),
                    "txt": str(settings.log_dir / "DAILY_CHECK_LOG.txt"),
                },
                "email_notification": email_result,
                "note": "No orders sent. Set DRY_RUN=false in .env and pass --place-orders to submit.",
            }
        )
        return 0

    submitted: list[tuple[object, dict[str, object]]] = []
    working_state = clone_state(state)
    try:
        for action in plan.actions:
            if not action.order_preview:
                continue
            response = broker.submit_order(action.order_preview)
            submitted.append((action, response))
        apply_submitted_orders(working_state, submitted, signal_date=plan.signal["as_of_date"])
        save_state(settings.state_path, working_state)
        submitted_orders = [{"action": action.__dict__, "response": response} for action, response in submitted]
        state_summary = {
            "before": plan.state_summary,
            "after": {
                "managed_leaps_count": len(working_state["managed_leaps"]),
                "pending_orders_count": len(working_state["pending_orders"]),
                "entry_history_count": len(working_state["entry_history"]),
            },
        }
        record = write_monitoring_record(
            log_dir=settings.log_dir,
            command="plan",
            status="submitted" if submitted_orders else "no_action",
            place_orders_requested=place_orders,
            dry_run=settings.dry_run,
            signal=plan.signal,
            warnings=plan.warnings,
            actions=[action.__dict__ for action in plan.actions],
            submitted_orders=submitted_orders,
            state_summary=state_summary,
        )
        email_result = _notify(settings, record)
        _print(
            {
                "signal": plan.signal,
                "warnings": plan.warnings,
                "submitted_orders": submitted_orders,
                "state_summary": state_summary,
                "monitoring_log": {
                    "csv": str(settings.log_dir / "monitoring_runs.csv"),
                    "jsonl": str(settings.log_dir / "monitoring_runs.jsonl"),
                    "txt": str(settings.log_dir / "DAILY_CHECK_LOG.txt"),
                },
                "email_notification": email_result,
            }
        )
    except Exception as exc:  # noqa: BLE001
        submitted_orders = [{"action": action.__dict__, "response": response} for action, response in submitted]
        record = write_monitoring_record(
            log_dir=settings.log_dir,
            command="plan",
            status="error",
            place_orders_requested=place_orders,
            dry_run=settings.dry_run,
            signal=plan.signal,
            warnings=plan.warnings,
            actions=[action.__dict__ for action in plan.actions],
            submitted_orders=submitted_orders,
            state_summary=plan.state_summary,
            error=str(exc),
        )
        _notify(settings, record)
        raise
    return 0


def cmd_state() -> int:
    settings = load_settings()
    state = load_state(settings.state_path, settings.strategy_version)
    _print(state)
    return 0


def cmd_test_email() -> int:
    settings = load_settings()
    result = send_email_notification(
        settings,
        "QQQ LEAPS monitor test email",
        "This is a local SMTP test from the QQQ LEAPS monitor script.",
    )
    _print(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autotrade CLI for the QQQ LEAPS strategy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check local config, state, and Alpaca paper connectivity")
    subparsers.add_parser("alpaca-account", help="Show Alpaca paper account, clock, positions, and open orders")
    subparsers.add_parser("signal", help="Evaluate the latest completed daily signal")
    plan = subparsers.add_parser("plan", help="Preview or submit today's strategy actions")
    plan.add_argument("--place-orders", action="store_true", help="Submit planned orders if DRY_RUN=false")
    subparsers.add_parser("state", help="Show the local strategy state file")
    subparsers.add_parser("test-email", help="Send a test email using the local SMTP settings")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        return cmd_doctor()
    if args.command == "alpaca-account":
        return cmd_alpaca_account()
    if args.command == "signal":
        return cmd_signal()
    if args.command == "plan":
        return cmd_plan(place_orders=args.place_orders)
    if args.command == "state":
        return cmd_state()
    if args.command == "test-email":
        return cmd_test_email()
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
