@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Project Python environment is missing: .venv
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -X utf8 run_local.py %*
if errorlevel 1 pause
