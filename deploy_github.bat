@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo   NDX Strategy - GitHub Auto Deploy
echo ========================================================
echo.

if not exist ".git" (
    echo [1/4] Initializing Git repository...
    git init
    git branch -M main
)

echo [2/4] Staging and committing files...
git add .
git commit -m "feat: update NDX regime strategy and mobile dashboard"

set "REPO_URL=https://github.com/JaeKwon5/ndx-strategy.git"
echo.
echo [3/4] Setting remote origin to %REPO_URL%...
git remote remove origin >nul 2>nul
git remote add origin %REPO_URL%

echo.
echo [4/4] Pushing to GitHub... (Please approve login window if prompted)
git push -u origin main

echo.
echo ========================================================
echo   Upload Complete!
echo   URL: https://github.com/JaeKwon5/ndx-strategy
echo ========================================================
pause
