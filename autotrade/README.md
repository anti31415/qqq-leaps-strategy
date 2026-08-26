# QQQ LEAPS Alpaca Paper Autotrade

This folder deploys the latest QQQ LEAPS strategy to Alpaca paper trading.

What this version does:

- evaluates the latest completed daily bar
- computes `QQQ RSI(14) < 35`
- computes expanding `VIX mean / std`
- applies the rolling-window VIX regime logic:
  - `mean + 1σ <= VIX < mean + 2σ`: max 1 LEAPS buy per week
  - first `VIX >= mean + 2σ` signal in the last 60 trading days: buy 1 LEAPS
  - second or later `VIX >= mean + 2σ` signal in the last 20 trading days: buy 2 LEAPS, or 1 if buying power only covers one
- selects an approximately 2-year QQQ call with delta nearest `0.70`
- tracks each LEAPS position in `state.json`
- applies the same take-profit / force-exit rules used in the latest backtest
- while a managed LEAPS is open, previews or submits a short OTM call overlay

Important operational note:

- Alpaca paper options are enabled by default according to Alpaca's official options trading docs.
- Long call purchases are a level 2 options trade.
- Selling a short call against a long LEAPS is broker-validation sensitive in practice. Alpaca's public docs clearly describe level 1 covered calls against shares and level 3 multi-leg spreads; a diagonal overlay may still be rejected depending on the paper account's options permissions and broker-side validation. This project will surface that response if Alpaca rejects the short-call order.

## Quick start

1. Copy `.env.example` to `.env`
2. Fill in your Alpaca paper credentials
3. Run:

```powershell
& 'C:\Users\antiz\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m autotrade.cli doctor
```

## Commands

```powershell
# Check config, Alpaca connectivity, account level, and state file location
python -m autotrade.cli doctor

# Show Alpaca account / clock / open positions / open orders
python -m autotrade.cli alpaca-account

# Evaluate the latest completed daily signal
python -m autotrade.cli signal

# Preview all actions for today
python -m autotrade.cli plan

# Submit today's planned orders if DRY_RUN=false
python -m autotrade.cli plan --place-orders

# Inspect local managed state
python -m autotrade.cli state
```

## Monitoring logs

Every `plan` run writes durable logs:

- `logs/monitoring_runs.csv` for quick spreadsheet review
- `logs/monitoring_runs.jsonl` for full signal/action/order details
- `logs/DAILY_CHECK_LOG.txt` as the single append-only human-readable daily checklist

The log records both preview runs and live paper-order runs. Failed plan runs are logged with `status=error` and the exception message.

For the local scheduled workflow, run:

```powershell
.\run_local_monitor.bat
```

Windows Task Scheduler setup is documented in `WINDOWS_TASK_SETUP.md`.

Indicator formulas are documented in `INDICATOR_FORMULAS.md`.

Email notification is handled locally by SMTP settings in `.env`. It is disabled by default:

```text
EMAIL_NOTIFY_ENABLED=false
```

Set it to `true` only after filling `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, and `SMTP_TO`.

The scheduled monitor sends email only when a real Alpaca paper order is submitted. Routine no-action checks only write logs.

Detailed email setup and the test command are documented in `EMAIL_SETUP.md`.

## State file

`state.json` tracks:

- managed LEAPS entries
- linked short call overlays
- pending orders submitted by this engine
- entry history used for the sigma1 weekly limit

If you start with an empty paper account, the state file should stay fully in sync.

If you manually trade the same Alpaca paper account outside this tool, the planner will flag unmanaged option positions and avoid making blind assumptions.
