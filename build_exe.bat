@echo off
rem ============================================================
rem  Builds "Anon Brain Setup.exe": a normal Windows installer
rem  (Start menu + optional desktop shortcut, uninstaller).
rem  Everything it needs is inside, FFmpeg included.
rem
rem  Run Install.bat once first. Then double-click this file.
rem  The installer ends up in the "dist" folder.
rem ============================================================
setlocal EnableExtensions
title Building Anon Brain
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo  [!] Run Install.bat first.
  pause
  exit /b 1
)
set "PY=.venv\Scripts\python.exe"

for /f "usebackq delims=" %%v in (`"%PY%" -c "from anonbrain.appinfo import VERSION; print(VERSION)"`) do set "VER=%%v"
echo.
echo  Building Anon Brain %VER%
echo.

echo  [1/4] Build tools...
"%PY%" -m pip install --quiet --upgrade pyinstaller
"%PY%" -m pip install --quiet piper-tts
if errorlevel 1 echo      (Piper voices won't be included; everything else will.)

echo  [2/4] FFmpeg...
if not exist "build_tools\ffmpeg" mkdir "build_tools\ffmpeg"
if exist "build_tools\ffmpeg\ffmpeg.exe" if exist "build_tools\ffmpeg\ffprobe.exe" goto have_ffmpeg

rem Copy the FFmpeg already on this PC (winget's links point at the real files)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='SilentlyContinue';" ^
  "foreach ($t in 'ffmpeg','ffprobe') {" ^
  "  $c = Get-Command $t; if (-not $c) { continue };" ^
  "  $p = $c.Source; $i = Get-Item $p; if ($i.LinkType -and $i.Target) { $p = @($i.Target)[0] };" ^
  "  Copy-Item $p 'build_tools\ffmpeg\' -Force;" ^
  "  Get-ChildItem (Split-Path $p) -Filter *.dll | Copy-Item -Destination 'build_tools\ffmpeg\' -Force }"
if exist "build_tools\ffmpeg\ffmpeg.exe" if exist "build_tools\ffmpeg\ffprobe.exe" goto have_ffmpeg

rem Not on this PC: download the official Windows build (about 90 MB)
echo      Downloading FFmpeg...
curl -L --fail -o "build_tools\ffmpeg.zip" "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
if errorlevel 1 goto no_ffmpeg
powershell -NoProfile -Command "Expand-Archive -Force 'build_tools\ffmpeg.zip' 'build_tools\ffmpeg_zip'; Get-ChildItem 'build_tools\ffmpeg_zip' -Recurse -Include ffmpeg.exe,ffprobe.exe | Copy-Item -Destination 'build_tools\ffmpeg\' -Force"
if not exist "build_tools\ffmpeg\ffmpeg.exe" goto no_ffmpeg
:have_ffmpeg
echo      FFmpeg will be built in.

echo  [3/4] Building the app (a few minutes)...
"%PY%" -m PyInstaller anonbrain.spec --noconfirm --clean --log-level WARN
if errorlevel 1 (
  echo  [!] The build failed. Scroll up for the error.
  pause
  exit /b 1
)

echo  [4/4] Making the installer...
set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC goto have_iscc
echo      Installing Inno Setup (free, one time)...
winget install -e --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements >nul
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC goto zip_instead
:have_iscc
"%ISCC%" /Q /DAppVersion=%VER% installer.iss
if errorlevel 1 goto zip_instead
echo.
echo  ============================================================
echo   Done!  dist\Anon-Brain-Setup-%VER%.exe
echo   Send that one file to your friends.
echo  ============================================================
explorer dist
pause
exit /b 0

:zip_instead
echo      Couldn't make the installer, making a zip instead...
powershell -NoProfile -Command "Compress-Archive -Force 'dist\Anon Brain' 'dist\Anon-Brain-%VER%.zip'"
echo.
echo  Done: dist\Anon-Brain-%VER%.zip  (unzip it and run "Anon Brain.exe")
explorer dist
pause
exit /b 0

:no_ffmpeg
echo  [!] Couldn't get FFmpeg. Install it with:  winget install ffmpeg
echo      then run this again.
pause
exit /b 1
