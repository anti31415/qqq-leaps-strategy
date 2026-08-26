# Windows Task Scheduler Setup

The local monitor can run on trading days at 09:40 and 15:40 Eastern Time. It should remain in preview mode until paper-account permissions and emergency shutdown procedures are tested.

Run the local monitor once with:

```powershell
.\run_local_monitor.bat
```

The scheduled tasks are named `QQQ_LEAPS_Monitor_0940` and `QQQ_LEAPS_Monitor_1540`. Runtime logs belong in the ignored local `logs/` directory.

