@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"C:\Users\antiz\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m autotrade.cli plan --place-orders

