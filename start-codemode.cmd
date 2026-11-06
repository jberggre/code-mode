@echo off
rem CodeMode desktop - the light front end (~40 MB, no browser, no server).
rem Runs ui.py under pythonw so there is no console window.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on PATH.
  pause
  exit /b 1
)
where pythonw >nul 2>nul
if errorlevel 1 (
  start "" python "app\ui.py"
) else (
  start "" pythonw "app\ui.py"
)
