"""Creates an 'Anon Brain' shortcut on the Windows desktop (run by Install.bat)."""

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
pythonw = root / ".venv" / "Scripts" / "pythonw.exe"


def ps_quote(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


script = f"""
$desktop = [Environment]::GetFolderPath('Desktop')
$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'Anon Brain.lnk'))
$s.TargetPath = {ps_quote(pythonw)}
$s.Arguments = {ps_quote('"' + str(root / 'app.py') + '"')}
$s.WorkingDirectory = {ps_quote(root)}
$s.IconLocation = {ps_quote(root / 'assets' / 'icon.ico')}
$s.Save()
"""

if sys.platform == "win32":
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script])
    print(" Desktop shortcut created." if r.returncode == 0 else " (Couldn't make a shortcut; use Anon Brain.bat)")
