"""Update checks and updating in place, from the GitHub repository's Releases.

Publishing an update: bump VERSION in appinfo.py, run build_exe.bat, then make a
new release on GitHub tagged with the version (e.g. v1.0.1) and attach the
Anon-Brain-Setup-1.0.1.exe that the build made. Everyone's app notices it.
"""

import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from . import appinfo
from .settings import data_dir

API = "https://api.github.com/repos/{repo}/releases/latest"


@dataclass
class Release:
    version: str
    notes: str
    page: str           # the release's web page
    installer: str      # download link of the setup .exe ("" if none attached)
    size: int = 0


def _parts(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4]) or (0,)


def is_newer(remote: str, local: str = appinfo.VERSION) -> bool:
    return _parts(remote) > _parts(local)


def enabled() -> bool:
    return bool(appinfo.UPDATE_REPO.strip())


def check(timeout: float = 10) -> Release | None:
    """The newest release if it's newer than this app, else None."""
    if not enabled():
        return None
    r = requests.get(API.format(repo=appinfo.UPDATE_REPO.strip()), timeout=timeout,
                     headers={"Accept": "application/vnd.github+json",
                              "User-Agent": f"AnonBrain/{appinfo.VERSION}"})
    if r.status_code == 404:        # no releases yet (or the repository is private)
        return None
    if r.status_code in (403, 429):  # GitHub's limit for checks from one network
        raise RuntimeError("GitHub is busy right now. Try again in a while.")
    r.raise_for_status()
    d = r.json()
    if d.get("draft") or d.get("prerelease"):
        return None
    version = (d.get("tag_name") or d.get("name") or "").lstrip("vV ")
    if not version or not is_newer(version):
        return None
    exe = next((a for a in d.get("assets") or []
                if a.get("name", "").lower().endswith(".exe")), None)
    return Release(version, (d.get("body") or "").strip(), d.get("html_url", ""),
                   exe["browser_download_url"] if exe else "", exe.get("size", 0) if exe else 0)


def can_install(rel: Release) -> bool:
    """Updating in place needs the installed .exe on Windows and a setup file to run."""
    return bool(rel.installer) and appinfo.frozen() and sys.platform == "win32"


def download(rel: Release, progress=lambda f: None, cancelled=lambda: False) -> Path:
    folder = data_dir() / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.exe"):          # earlier downloads
        try:
            old.unlink()
        except OSError:
            pass
    out = folder / f"Anon-Brain-Setup-{rel.version}.exe"
    part = out.with_suffix(".part")
    with requests.get(rel.installer, stream=True, timeout=30,
                      headers={"User-Agent": f"AnonBrain/{appinfo.VERSION}"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or rel.size or 0)
        got, last = 0, 0.0
        with open(part, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                if cancelled():
                    raise InterruptedError("Update cancelled.")
                f.write(chunk)
                got += len(chunk)
                if total and time.time() - last > 0.1:
                    progress(got / total)
                    last = time.time()
    if total and got < total:
        raise IOError("The download was cut short. Try again.")
    part.replace(out)
    progress(1.0)
    return out


def run_installer(path: Path):
    """Start the setup (it shows its own progress), after this app has had a moment to
    close. Settings are kept, and the setup opens the new version when it's done."""
    args = f'"{path}" /SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS'
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | \
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & start "" {args}',
                     creationflags=flags, close_fds=True)
