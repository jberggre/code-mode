@echo off
rem Optional browser front end. A Chromium tab costs far more RAM than the
rem desktop window, so use this for convenience, not for model headroom.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on PATH.
  pause
  exit /b 1
)
python app\server.py
pause
