@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo   NDX and SOX Regime Strategy Backtest
echo ========================================================

if exist "C:\Python314\python.exe" (
    "C:\Python314\python.exe" ndx_regime_backtest.py %*
) else (
    ".venv\Scripts\python.exe" ndx_regime_backtest.py %*
)

echo.
echo Done.
pause
