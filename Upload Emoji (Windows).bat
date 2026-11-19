@echo off
rem Double-click this file (Windows) to upload a folder of emoji to Slack.
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo This tool needs Python 3, which isn't installed yet.
  echo Opening the Python download page. Install it, then double-click this file again.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First-time setup: installing what this tool needs, about a minute...
  py -3 -m venv .venv || goto setupfail
)
".venv\Scripts\python.exe" -c "import requests, PIL" >nul 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check requests pillow || goto setupfail
)

".venv\Scripts\python.exe" upload.py %*
pause
exit /b 0

:setupfail
echo Setup failed. Check your internet connection and try again.
pause
exit /b 1
