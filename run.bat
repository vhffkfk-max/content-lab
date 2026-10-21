@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
python collect.py
python analyze.py
python export_site.py
echo.
echo 사이트에 반영하려면 Claude에게 "연구소 사이트 갱신해줘" 라고 말하세요.
pause
