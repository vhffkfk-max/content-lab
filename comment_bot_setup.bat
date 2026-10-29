@echo off
chcp 65001 >nul
setlocal
title 댓글 기회 봇 설치
rem 여분 PC에서 더블클릭: 파이썬 확인(없으면 설치) → 사용자 폴더로 복사 → 봇 상시 실행 등록.
rem USB에서 바로 눌러도 돼요. 봇은 USB가 아니라 %USERPROFILE%\content-lab-comment-bot 에서 돌아요.
set "SRC=%~dp0"
set "DEST=%USERPROFILE%\content-lab-comment-bot"

echo.
echo  댓글 기회 봇을 이 PC에 설치해요. 창을 닫지 말고 기다려 주세요.
echo.

call :findpy
if not defined PY (
  echo  [1/3] 파이썬이 없어서 설치해요. 몇 분 걸려요...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  call :findpy
)
if not defined PY (
  echo.
  echo  파이썬 설치에 실패했어요. python.org 에서 파이썬 3.12 를 설치한 뒤 이 파일을 다시 눌러 주세요.
  pause
  exit /b 1
)
echo  [1/3] 파이썬 확인: %PY%

echo  [2/3] 파일 복사: %DEST%
robocopy "%SRC%." "%DEST%" /E /XF .env *.bat /XD data __pycache__ /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo  파일 복사에 실패했어요.
  pause
  exit /b 1
)

if "%NOINSTALL%"=="1" (
  echo  시험 모드라 등록은 건너뛰어요.
  exit /b 0
)

echo  [3/3] 봇 등록 - Anthropic 키를 물으면 붙여 넣고 Enter. 화면에 안 보여도 정상이에요.
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\comment_bot_install.ps1" -Python "%PY%" -EnvFrom "%SRC%.env"
echo.
echo  끝났어요. 1분 안에 텔레그램에 "댓글 봇이 켜졌어요" 가 오면 성공이에요.
echo  절전은 꺼 두세요: 설정 - 시스템 - 전원 - 절전 "안 함"
pause
exit /b 0

:findpy
set "PY="
for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
if defined PY exit /b 0
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%d\python.exe" set "PY=%%d\python.exe"
exit /b 0
