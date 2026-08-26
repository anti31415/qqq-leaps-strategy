# Windows Task Scheduler Setup

This replaces the old Codex automations. The local task runs the script directly and appends results to:

```text
logs\DAILY_CHECK_LOG.txt
```

## 1. Confirm The Script Runs

Open PowerShell:

```powershell
cd /d "C:\Users\antiz\OneDrive\Desktop\Codex\量化研究\tianbro_qqq_leaps_strategy\autotrade"
.\run_local_monitor.bat
```

## 2. Create The 09:40 Task

Open PowerShell as the current Windows user:

```powershell
$action = New-ScheduledTaskAction -Execute "C:\Users\antiz\OneDrive\Desktop\Codex\量化研究\tianbro_qqq_leaps_strategy\autotrade\run_local_monitor.bat" -WorkingDirectory "C:\Users\antiz\OneDrive\Desktop\Codex\量化研究\tianbro_qqq_leaps_strategy\autotrade"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 9:40am
Register-ScheduledTask -TaskName "QQQ_LEAPS_Monitor_0940" -Action $action -Trigger $trigger -Description "Run QQQ LEAPS Alpaca paper strategy monitor at 09:40 ET" -Force
```

## 3. Create The 15:40 Task

```powershell
$action = New-ScheduledTaskAction -Execute "C:\Users\antiz\OneDrive\Desktop\Codex\量化研究\tianbro_qqq_leaps_strategy\autotrade\run_local_monitor.bat" -WorkingDirectory "C:\Users\antiz\OneDrive\Desktop\Codex\量化研究\tianbro_qqq_leaps_strategy\autotrade"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 3:40pm
Register-ScheduledTask -TaskName "QQQ_LEAPS_Monitor_1540" -Action $action -Trigger $trigger -Description "Run QQQ LEAPS Alpaca paper strategy monitor at 15:40 ET" -Force
```

## 4. Check Task Status

```powershell
Get-ScheduledTask -TaskName "QQQ_LEAPS_Monitor_0940","QQQ_LEAPS_Monitor_1540"
```

## 5. Stop The Tasks

```powershell
Unregister-ScheduledTask -TaskName "QQQ_LEAPS_Monitor_0940" -Confirm:$false
Unregister-ScheduledTask -TaskName "QQQ_LEAPS_Monitor_1540" -Confirm:$false
```

