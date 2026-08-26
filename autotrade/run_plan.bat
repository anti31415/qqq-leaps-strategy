@echo off
cd /d "%~dp0"
"C:\Users\antiz\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m autotrade.cli plan
echo.
pause

