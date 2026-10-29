@echo off
rem Runs all of Anon Brain's checks. Add "quick" to skip the video renders:  run_tests.bat quick
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m tests %*
) else (
  python -m tests %*
)
echo.
pause
