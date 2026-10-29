@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Anon Brain is not set up yet. Run Install.bat first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" app.py
