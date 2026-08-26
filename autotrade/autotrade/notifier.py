from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from autotrade.config import Settings


def build_run_summary(record: dict[str, Any]) -> str:
    signal = record.get("signal") or {}
    actions = record.get("actions") or []
    submitted_orders = record.get("submitted_orders") or []
    lines = [
        "QQQ LEAPS paper trading action submitted",
        "",
        f"Status: {record.get('status', '')}",
        f"Run time: {record.get('run_timestamp', '')}",
        f"Signal date: {signal.get('as_of_date', record.get('signal_date', ''))}",
        f"QQQ close: {signal.get('qqq_close', record.get('qqq_close', ''))}",
        f"QQQ RSI(14): {signal.get('qqq_rsi', record.get('qqq_rsi', ''))}",
        f"VIX close: {signal.get('vix_close', record.get('vix_close', ''))}",
        f"VIX expanding mean: {signal.get('vix_mean', '')}",
        f"VIX expanding std: {signal.get('vix_std', '')}",
        f"Sigma 1 threshold: {signal.get('sigma1_threshold', '')}",
        f"Sigma 2 threshold: {signal.get('sigma2_threshold', '')}",
        f"Sigma 2 count in 60 trading days: {signal.get('sigma2_count_60', '')}",
        f"Sigma 2 count in 20 trading days: {signal.get('sigma2_count_20', '')}",
        f"Regime: {signal.get('regime_name', record.get('regime_name', ''))}",
        f"Buy reason: {signal.get('buy_reason', record.get('buy_reason', ''))}",
        f"Actions planned: {record.get('actions_count', 0)}",
        f"Orders submitted: {record.get('submitted_orders_count', 0)}",
        f"Warnings: {record.get('warnings', [])}",
        f"Error: {record.get('error', '')}",
    ]
    if actions:
        lines.extend(["", "Planned actions:"])
        for action in actions:
            lines.append(str(action))
    if submitted_orders:
        lines.extend(["", "Submitted orders:"])
        for order in submitted_orders:
            lines.append(str(order))
    return "\n".join(lines)


def send_email_notification(settings: Settings, subject: str, body: str) -> dict[str, Any]:
    if not settings.email_notify_enabled:
        return {"enabled": False, "sent": False, "reason": "email_notify_disabled"}
    missing = [
        name
        for name, value in {
            "SMTP_HOST": settings.smtp_host,
            "SMTP_USERNAME": settings.smtp_username,
            "SMTP_PASSWORD": settings.smtp_password,
            "SMTP_FROM": settings.smtp_from,
            "SMTP_TO": settings.smtp_to,
        }.items()
        if not value
    ]
    if missing:
        return {"enabled": True, "sent": False, "reason": f"missing_config: {', '.join(missing)}"}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = settings.smtp_to
    message.set_content(body)

    try:
        if settings.smtp_security == "ssl":
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                if settings.smtp_security == "starttls":
                    smtp.starttls()
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "sent": False, "reason": f"send_failed: {exc}"}

    return {"enabled": True, "sent": True, "reason": "sent"}
