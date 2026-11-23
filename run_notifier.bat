@echo off
setlocal
cd /d "%~dp0"
if exist "C:\Python314\python.exe" (
    "C:\Python314\python.exe" daily_signal_notifier.py %*
) else (
    ".venv\Scripts\python.exe" daily_signal_notifier.py %*
)
