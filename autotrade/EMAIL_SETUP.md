# Email Notification Setup

The monitor can send email locally after real paper orders are submitted. Email is optional and disabled by default.

Configuration lives in `.env`:

```text
EMAIL_NOTIFY_ENABLED=false
SMTP_HOST=
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_TO=
```

## Gmail

Use an app password, not your normal Google account password.

```text
EMAIL_NOTIFY_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your_gmail_address@gmail.com
SMTP_PASSWORD=your_google_app_password
SMTP_FROM=your_gmail_address@gmail.com
SMTP_TO=destination@example.com
```

Alternative Gmail SSL mode:

```text
SMTP_PORT=465
SMTP_SECURITY=ssl
```

## Outlook / Microsoft 365

```text
EMAIL_NOTIFY_ENABLED=true
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your_outlook_or_m365_address
SMTP_PASSWORD=your_password_or_app_password
SMTP_FROM=your_outlook_or_m365_address
SMTP_TO=destination@example.com
```

## Test

Run from this folder:

```powershell
cd /d "C:\Users\antiz\OneDrive\Desktop\Codex\量化研究\tianbro_qqq_leaps_strategy\autotrade"
"C:\Users\antiz\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m autotrade.cli test-email
```

Expected success:

```json
{
  "enabled": true,
  "sent": true,
  "reason": "sent"
}
```

Automatic monitor behavior:

- No email is sent for ordinary no-action checks.
- No email is sent for preview checks.
- An email is sent only when Alpaca returns one or more submitted paper orders.
- The email includes the action, order response, signal values, RSI/VIX thresholds, and the reason for the trade.

`test-email` always sends a test message when email is enabled, so you can verify SMTP separately.

If email sending fails, the monitor still runs trading logic and records the email error in command output. Email failure does not block strategy execution.
