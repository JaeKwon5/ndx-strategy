@echo off
setlocal
cd /d "%~dp0"
if exist "C:\Python314\python.exe" (
    "C:\Python314\python.exe" web_dashboard.py %*
) else (
    ".venv\Scripts\python.exe" web_dashboard.py %*
)
