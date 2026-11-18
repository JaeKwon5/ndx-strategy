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
git diff --staged --quiet || git commit -m "feat: update NDX regime strategy & mobile dashboard"

set REPO_URL=https://github.com/JaeKwon5/ndx-strategy.git
echo.
echo [3/4] 원격 저장소(%REPO_URL%) 연결 중...
git remote remove origin >nul 2>nul
git remote add origin %REPO_URL%

echo [4/4] GitHub로 업로드(Push) 중... (로그인 창이 뜨면 승인해 주세요)
git push -u origin main

echo.
echo ========================================================
echo   업로드가 완료되었습니다!
echo   이제 GitHub 웹사이트의 [Settings] -> [Pages]에서
echo   Source를 [GitHub Actions]로 변경해 주세요.
echo ========================================================
pause
