@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

echo ========================================================
echo   GitHub 자동 배포 초기 설정 도우미
echo ========================================================
echo.

if not exist ".git" (
    echo [1/4] 로컬 Git 저장소를 초기화합니다...
    git init
    git branch -M main
)

echo [2/4] 프로젝트 파일을 스테이징 및 커밋합니다 (.venv 및 .env는 자동 제외)...
git add .
git commit -m "feat: initial NDX regime strategy & mobile dashboard"

echo.
set /p REPO_URL="GitHub 저장소 주소(예: https://github.com/아이디/ndx-strategy.git)를 붙여넣고 Enter를 누르세요: "

if "%REPO_URL%"=="" (
    echo [취소] 저장소 주소가 입력되지 않았습니다.
    pause
    exit /b 1
)

echo.
echo [3/4] 원격 저장소(origin) 연결 중...
git remote remove origin >nul 2>nul
git remote add origin %REPO_URL%

echo [4/4] GitHub로 업로드(Push) 중...
git push -u origin main

echo.
echo ========================================================
echo   업로드가 완료되었습니다!
echo   이제 GitHub 웹사이트의 [Settings] -> [Pages]에서
echo   Source를 [GitHub Actions]로 변경해 주세요.
echo ========================================================
pause
