# Email Notification Setup

Email is optional and disabled by default. Configure SMTP values in a local, ignored `.env` file and use an app password where the provider requires one.

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

The `test-email` command sends a test only when email is enabled. Routine no-action and preview checks do not send mail; a notification is sent after a submitted paper order. Never commit SMTP credentials or recipient data.

