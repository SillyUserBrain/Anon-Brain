"""Version, where the app lives, bundled tools, logging and crash reports."""

import logging
import logging.handlers
import os
import platform
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path

VERSION = "1.0.0"
NAME = "Anon Brain"
# Where new versions are published: your GitHub repository as "owner/repo"
# (it must be public). Leave it empty to turn update checks off.
UPDATE_REPO = "SillyUserBrain/Anon-Brain"

log = logging.getLogger("anonbrain")


def frozen() -> bool:
    """True when running as the built Anon Brain.exe."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder with Anon Brain.exe (built) or app.py (from source)."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _bundle_dirs() -> list[Path]:
    dirs = [app_dir()]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass))
    dirs.append(app_dir() / "tools")
    return dirs


def bundled_tool(name: str) -> str:
    """ffmpeg / ffprobe shipped with the app, if any ('' if not)."""
    exe = name + (".exe" if sys.platform == "win32" else "")
    for d in _bundle_dirs():
        for p in (d / "ffmpeg" / exe, d / "ffmpeg" / "bin" / exe, d / exe):
            if p.is_file():
                return str(p)
    return ""


def find_tool(name: str) -> str:
    """Bundled copy first, then whatever is installed on the PC ('' if none)."""
    return bundled_tool(name) or shutil.which(name) or ""


# --- logging -------------------------------------------------------------------------
def log_dir() -> Path:
    from .settings import data_dir
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_file() -> Path:
    return log_dir() / "anonbrain.log"


def setup_logging():
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    try:
        h = logging.handlers.RotatingFileHandler(log_file(), maxBytes=1_000_000, backupCount=3,
                                                 encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    except OSError:
        log.addHandler(logging.NullHandler())
    log.info("---- %s %s starting (%s, Python %s, %s) ----", NAME, VERSION,
             platform.platform(), platform.python_version(), "exe" if frozen() else "source")


def log_exception(where: str, exc: BaseException):
    log.error("%s: %s\n%s", where, exc,
              "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


def system_info() -> str:
    lines = [f"{NAME} {VERSION} ({'exe' if frozen() else 'source'})",
             f"System: {platform.platform()}",
             f"Python: {platform.python_version()}"]
    ff = find_tool("ffmpeg")
    lines.append(f"FFmpeg: {'bundled' if ff and ff == bundled_tool('ffmpeg') else ff or 'NOT FOUND'}")
    try:
        from . import encoders
        found = encoders._found
        if found is not None:
            lines.append("Graphics: " + encoders.describe(found))
    except Exception:
        pass
    lines.append(f"Saved sign-ins: {keyring_status()}")
    return "\n".join(lines)


def error_report(max_lines: int = 250) -> str:
    """Everything worth sending when something goes wrong: version, PC, recent log."""
    try:
        tail = log_file().read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
    except OSError:
        tail = ["(no log yet)"]
    text = (f"==== {NAME} error report ({time.strftime('%Y-%m-%d %H:%M')}) ====\n"
            + system_info() + "\n\n---- recent log ----\n" + "\n".join(tail))
    home = str(Path.home())
    return text.replace(home, "~") if len(home) > 3 else text


def install_hooks(on_crash=None):
    """Log every unexpected error; on_crash(text) shows it to you."""
    def hook(kind, exc, tb):
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, exc, tb)
            return
        text = "".join(traceback.format_exception(kind, exc, tb))
        log.error("Unexpected error:\n%s", text)
        if on_crash:
            try:
                on_crash(text)
            except Exception:
                pass

    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)


# --- saved keys ----------------------------------------------------------------------
def setup_keyring():
    """Pick Windows Credential Manager directly. The automatic lookup keyring does
    can find nothing inside a built .exe, and then every save quietly fails."""
    if sys.platform != "win32":
        return
    try:
        import keyring
        from keyring.backends.Windows import WinVaultKeyring
        keyring.set_keyring(WinVaultKeyring())
    except Exception as e:
        log_exception("Couldn't set up Windows Credential Manager", e)


def keyring_status() -> str:
    try:
        import keyring
        test = "anonbrain_selftest"
        keyring.set_password(NAME, test, "ok")
        ok = keyring.get_password(NAME, test) == "ok"
        try:
            keyring.delete_password(NAME, test)
        except Exception:
            pass
        name = type(keyring.get_keyring()).__name__
        return f"working ({name})" if ok else f"NOT saving ({name})"
    except Exception as e:
        return f"NOT working ({e.__class__.__name__}: {e})"


def open_folder(path: Path):
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        log_exception("open folder", e)


def show_in_folder(path):
    """Open the file's folder with the file selected (or just the folder, if the file
    is gone or it is a folder)."""
    path = Path(path)
    if sys.platform == "win32" and path.is_file():
        import subprocess
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
            return
        except OSError as e:
            log_exception("show in folder", e)
    folder = path if path.is_dir() else path.parent
    if folder.is_dir():
        open_folder(folder)


# --- self test (Anon Brain.exe --selftest) -----------------------------------------------
def self_test() -> str:
    """Check that every engine inside the app loads. Writes selftest.txt in the data folder."""
    from .settings import data_dir
    out = [system_info(), ""]

    def check(name, fn):
        try:
            res = fn()
            out.append(f"OK    {name}" + (f": {res}" if res else ""))
        except Exception as e:
            out.append(f"FAIL  {name}: {e.__class__.__name__}: {e}")
            log_exception(f"self test: {name}", e)

    def ff():
        from .engine import run_tool
        r = run_tool([find_tool("ffmpeg"), "-version"])
        return r.stdout.splitlines()[0][:60]

    def ocr():
        import tempfile

        from PIL import Image, ImageDraw

        from .cards import font
        from .ocr import read_post
        im = Image.new("RGB", (520, 90), "white")
        ImageDraw.Draw(im).text((12, 25), "it was handed down to me", fill="black",
                                font=font("regular", 30))
        p = Path(tempfile.gettempdir()) / "anonbrain_selftest.png"
        im.save(p)
        return f"read “{read_post(p).text.strip()}”"

    def kokoro():
        import espeakng_loader  # noqa: F401
        import kokoro_onnx  # noqa: F401
        return "loaded"

    def piper():
        import piper  # noqa: F401
        return "loaded"

    def qt_media():
        from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401
        return "loaded"

    check("FFmpeg", ff)
    check("Text reading (OCR)", ocr)
    check("Free voices (Kokoro)", kokoro)
    check("Piper voices", piper)
    check("Sound playback", qt_media)
    def keys():
        st = keyring_status()
        if not st.startswith("working"):
            raise RuntimeError(st)
        return st

    check("Saved sign-ins", keys)
    text = "\n".join(out)
    try:
        (data_dir() / "selftest.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass
    log.info("self test:\n%s", text)
    return text
