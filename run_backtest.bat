@echo off
chcp 65001 > nul
setlocal

echo ========================================================
echo   NDX 250일선 레짐 + VIX10 + 52주 낙폭 레버리지 백테스트
echo ========================================================

if not exist ".venv\Scripts\python.exe" (
    where uv >nul 2>nul
    if %errorlevel% equ 0 (
        echo [1/2] uv를 사용하여 가상환경 및 패키지 동기화 중...
        uv sync --python 3.12
    ) else (
        echo [1/2] 가상환경(.venv) 생성 및 패키지 설치 중...
        python -m venv .venv
        ".venv\Scripts\python.exe" -m pip install --upgrade pip
        ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    )
)

echo.
echo [실행] 백테스트를 시작합니다...
".venv\Scripts\python.exe" ndx_regime_backtest.py %*

echo.
echo 실행이 완료되었습니다.
pause
