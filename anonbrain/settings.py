"""Where Anon Brain keeps its data, plus simple saved settings.

Everything lives in %APPDATA%\\AnonBrain on Windows (~/.anonbrain elsewhere),
so each person who uses the app has their own settings, cleanup table and
used-footage history. The ElevenLabs key is NOT stored here; see voice.py.
"""

import atexit
import json
import os
import threading
import time
import weakref
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("APPDATA")
    d = Path(base) / "AnonBrain" if base else Path.home() / ".anonbrain"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_json(path: Path, obj, indent=None):
    """Save safely: write a temporary file, then swap it in. A crash or a full disk
    mid-save can't leave a half-written (unreadable) file behind."""
    write_text(path, json.dumps(obj, indent=indent))


def write_text(path: Path, text: str):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def default_output_dir() -> Path:
    return Path.home() / "Videos" / "Anon Brain"


DEFAULTS = {
    "output_dir": str(default_output_dir()),
    "voice_model": "eleven_multilingual_v2",
    "last_voice_id": "free:am_michael",
    "line_pause": 0.35,
    "voice_speed": 1.0,
    "target_platform": "",  # app you're making it for ("" = just show what fits)
    "encoder": "auto",
    "min_length": 0,        # seconds; 0 = off. Shorter videos keep going with gameplay + music
    "voice_volume": 100,
    "music_volume": 20,
    "last_music": "",
    "music_start": 0.0,     # seconds into the song where the video's music starts
    "music_mode": "song",   # "song" (last_music) or "folder" (a random song each video)
    "music_folder": "",
    "gameplay_mode": "folder",   # "file" or "folder"
    "last_gameplay_file": "",
    "last_gameplay_folder": "",
    "reveal": True,
    "reveal_style": "fade",  # fade / slide (only used when "reveal" is on)
    "post_display": "post",  # post / intro (post, then captions) / captions (no post)
    "captions": {},          # caption look (see captions.DEFAULT_STYLE for the fields)
    # appearance
    "color_primary": "#8fc43f",
    "color_secondary": "#2fc4a0",
    "color_tertiary": "#7a5cff",
    "bg_style": "orbs",
    "bg_blur": 60,          # 0..100
    "bg_speed": 35,         # 0..100
    "bg_brightness": 70,    # 20..100
    "ui_animations": True,
    "skip_boring": True,
    "reuse_footage": False,     # gameplay: pick from anywhere, even parts already used
    "repeat_songs": False,      # music folder: any song, even one that just played
    "hook_spoken": True,
    # layout
    "format": "9:16",
    "resolution": "1080p",
    "fps": 30,              # 24 (film), 30 or 60
    "mirror": "off",        # off / on / random (flips back and forth)
    "fit": "fill",          # fill (crop) / blur (whole video over a blurred copy)
    "clip_only": False,     # no post or voice: just the video (movie clips)
    "game_volume": 0,       # the video's own sound under a narrator, percent
    "clip_volume": 100,     # ...and in "just the video" mode (movie clips)
    "layouts": {},          # format -> {"x", "y", "w"} where the post sits
    "show_app_overlay": True,
    "custom_voices": [],
    "check_updates": True,  # look for new versions on GitHub (see updates.py)
    "tour_done": False,     # the first-run tour has been shown
    "automation": {},       # Automate screen (see automation.py for the fields)
    "watermark": {},        # your handle (see ui/brand.py for the fields)
    "endcard": {},          # "Follow for part 2" at the end
    "brand_pos": {},        # format -> where each sits
    "reddit_theme": "dark",    # your own voices (see custom_voices.py)
    "post_round": 0,        # 0 = square corners .. 100 = oval / circle
    "post_shadow": False,
    "post_shadow_strength": 50,
    "post_border": False,
    "post_border_width": 8,          # pixels at 1080p
    "post_border_style": "solid",    # or spin / rainbow / shimmer
    "post_border_color": "primary",  # primary / secondary / tertiary / "#rrggbb"
}


_open: "weakref.WeakSet[Settings]" = weakref.WeakSet()


def flush_all():
    """Write every unsaved change now (the app is closing)."""
    for s in list(_open):
        s.flush()


atexit.register(flush_all)


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "settings.json"
        self.values = dict(DEFAULTS)
        self.listeners = []         # called after every save (undo history uses it)
        try:
            self.values.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        self._lock = threading.Lock()
        self._timer = None
        self._text = self._written = None
        self._last_write = 0.0
        _open.add(self)

    def __getitem__(self, key):
        return self.values.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.values[key] = value
        self.save()

    def save(self):
        """Listeners hear about it now; the file is written at most ~4 times a second
        (dragging a slider changes a setting dozens of times a second)."""
        self._text = json.dumps(self.values, indent=2)
        wait = self._last_write + 0.25 - time.monotonic()
        if wait <= 0:
            self.flush()
        elif self._timer is None:
            self._timer = threading.Timer(wait, self.flush)
            self._timer.daemon = True
            self._timer.start()
        for fn in list(self.listeners):
            fn()

    def flush(self):
        """Write any change not on disk yet (also runs when the app closes)."""
        with self._lock:
            self._timer = None
            text = self._text
            if text is None or text == self._written:
                return
            try:
                write_text(self.path, text)
                self._written = text
            except OSError:
                pass
            self._last_write = time.monotonic()
