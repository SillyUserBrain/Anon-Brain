"""History of every video made: thumbnail, text, settings, footage used.

Stored in %APPDATA%\\AnonBrain\\history.json, with thumbnails and a copy of
each post screenshot in %APPDATA%\\AnonBrain\\history\\.
"""

import json
import re
import shutil
import time
import uuid
from difflib import SequenceMatcher
from pathlib import Path

from .engine import _tool, run_tool
from .settings import data_dir, write_json


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())[:600]


class History:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "history.json"
        self.dir = self.path.parent / "history"
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.entries = []

    def save(self):
        write_json(self.path, self.entries, indent=1)

    def add(self, video: Path, text: str, image: str, hook: str, voice: str,
            gameplay: str, start: float | None, length: float) -> dict:
        eid = uuid.uuid4().hex[:10]
        thumb = self.dir / f"{eid}.jpg"
        try:
            run_tool([_tool("ffmpeg"), "-v", "error", "-y", "-ss", "1.5", "-i", video,
                      "-frames:v", "1", "-vf", "scale=216:-2", thumb], text=False)
        except Exception:
            pass
        img_copy = ""
        if image and Path(image).exists():
            img_copy = str(self.dir / f"{eid}{Path(image).suffix.lower()}")
            try:
                shutil.copy2(image, img_copy)
            except OSError:
                img_copy = ""
        entry = {
            "id": eid, "created": time.time(), "video": str(video), "text": text,
            "image": img_copy, "hook": hook, "voice": voice, "gameplay": gameplay,
            "start": start, "length": round(length, 2),
            "thumb": str(thumb) if thumb.exists() else "",
        }
        self.entries.insert(0, entry)
        self.save()
        return entry

    def remove(self, entry: dict, delete_files: bool = False):
        self.entries = [e for e in self.entries if e["id"] != entry["id"]]
        self.save()
        for key in ("thumb", "image"):
            if entry.get(key):
                Path(entry[key]).unlink(missing_ok=True)
        if delete_files and entry.get("video"):
            Path(entry["video"]).unlink(missing_ok=True)

    def find_similar(self, text: str, threshold: float = 0.85) -> dict | None:
        """A previous video made from (nearly) the same post, if any."""
        t = _norm(text)
        if len(t) < 20:
            return None
        for e in self.entries:
            if SequenceMatcher(None, t, _norm(e.get("text", ""))).quick_ratio() >= threshold:
                if SequenceMatcher(None, t, _norm(e.get("text", ""))).ratio() >= threshold:
                    return e
        return None
