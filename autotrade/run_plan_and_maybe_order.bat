@echo off
cd /d "%~dp0"
set DRY_RUN=false
"C:\Users\antiz\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m autotrade.cli plan --place-orders
echo.
pause

