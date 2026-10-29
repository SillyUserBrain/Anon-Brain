@echo off
title Anon Brain setup
cd /d "%~dp0"
echo.
echo  =============================
echo    Setting up Anon Brain
echo  =============================
echo.

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo  [!] FFmpeg was not found. Install it by running:  winget install ffmpeg
  echo      then close this window and run Install.bat again.
  pause
  exit /b 1
)

echo  Creating the app environment...
py -3.12 -m venv .venv 2>nul || py -m venv .venv
if errorlevel 1 (
  echo  [!] Could not find Python. Install Python 3.12 from python.org first.
  pause
  exit /b 1
)

echo  Installing libraries (a few minutes the first time)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo  [!] Something went wrong installing libraries. Scroll up for the error.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" tools\make_shortcut.py
echo.
echo  All set! Open Anon Brain from the desktop shortcut or "Anon Brain.bat".
echo.
pause
