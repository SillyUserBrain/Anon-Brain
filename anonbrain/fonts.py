"""Fonts on this PC, by name, for drawing captions.

Covers Windows' fonts, fonts you installed just for yourself, and font files
added in the app (kept in %APPDATA%\\AnonBrain\\fonts). The list of which file
holds which font is cached, so looking one up is quick after the first time.
"""

import json
import os
import shutil
import sys
import threading
from pathlib import Path

from .settings import data_dir

EXTS = {".ttf", ".otf", ".ttc"}
# how heavy a style name sounds (longer names first, so "semibold" isn't "bold")
WEIGHTS = [("extrabold", 16), ("extra bold", 16), ("ultrabold", 16), ("semibold", 12),
           ("semi bold", 12), ("demibold", 12), ("black", 18), ("heavy", 17), ("bold", 15)]
_index = None
_scanned = 0.0          # when the folders were last looked through
_lock = threading.Lock()


def my_fonts_dir() -> Path:
    d = data_dir() / "fonts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def font_dirs() -> list[Path]:
    dirs = [my_fonts_dir()]
    if sys.platform == "win32":
        dirs.append(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs += [Path("/Library/Fonts"), Path("/System/Library/Fonts"),
                 Path.home() / "Library" / "Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
                 Path.home() / ".fonts", Path.home() / ".local" / "share" / "fonts"]
    return [d for d in dirs if d.is_dir()]


def _files():
    for d in font_dirs():
        for root, _, names in os.walk(d):
            for n in names:
                if Path(n).suffix.lower() in EXTS:
                    yield Path(root) / n


def index() -> dict:
    """{file path: [family, style, mtime]} for every font file found (cached on disk)."""
    with _lock:
        return dict(_scan())


def _scan() -> dict:
    global _index, _scanned
    import time

    from PIL import ImageFont
    if _index is not None and time.time() - _scanned < 120:
        return _index
    cache_path = data_dir() / "font_index.json"
    if _index is None:
        try:
            _index = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _index = {}
    seen, changed = set(), False
    for f in _files():
        key = str(f)
        seen.add(key)
        try:
            stamp = f.stat().st_mtime
        except OSError:
            continue
        old = _index.get(key)
        if old and old[2] == stamp:
            continue
        try:
            fam, style = ImageFont.truetype(key, 12).getname()
        except Exception:       # not a font PIL can read: remember and skip it
            fam, style = "", ""
        _index[key] = [fam or "", style or "", stamp]
        changed = True
    for key in [k for k in _index if k not in seen]:
        del _index[key]
        changed = True
    _scanned = time.time()
    if changed:
        try:
            cache_path.write_text(json.dumps(_index), encoding="utf-8")
        except OSError:
            pass
    return _index


def _weight_score(text: str, bold: bool) -> int:
    t = text.lower()
    if "italic" in t or "oblique" in t:
        return -50
    w = next((v for word, v in WEIGHTS if word in t), 0)
    narrow = -3 if any(x in t for x in ("condensed", "narrow", "compressed")) else 0
    if bold:
        return w + narrow
    if w:
        return narrow
    plain = any(x in t for x in ("regular", "normal", "book")) or not t.strip()
    return (20 if plain else 10) + narrow


def find(family: str, bold: bool = True) -> str | None:
    """The font file for a font name (as listed in the font picker), or None."""
    want = (family or "").strip().lower()
    if not want:
        return None
    best, best_score = None, -999
    for path, (fam, style, _) in index().items():
        f = fam.lower()
        if f == want:
            score = 100 + _weight_score(style, bold)
        elif f.startswith(want + " "):     # "Montserrat Black" for "Montserrat"
            score = 50 + _weight_score(f[len(want):] + " " + style, bold)
        else:
            continue
        if score > best_score:
            best, best_score = path, score
    return best


def add_font_file(src: str) -> tuple[str, str]:
    """Copy a downloaded font into the app's fonts folder.
    Returns (font name, path) or raises ValueError if it isn't a font."""
    from PIL import ImageFont
    p = Path(src)
    if p.suffix.lower() not in EXTS:
        raise ValueError("Pick a .ttf or .otf font file.")
    try:
        fam, _ = ImageFont.truetype(str(p), 12).getname()
    except Exception:
        raise ValueError(f"“{p.name}” isn't a font file Anon Brain can read.")
    dest = my_fonts_dir() / p.name
    if p.resolve() != dest.resolve():
        shutil.copy2(p, dest)
    global _index
    _index = None
    return fam, str(dest)


def register_app_fonts():
    """Let Qt (the font picker) see fonts added in the app."""
    from PySide6.QtGui import QFontDatabase
    for f in my_fonts_dir().iterdir():
        if f.suffix.lower() in EXTS:
            QFontDatabase.addApplicationFont(str(f))
