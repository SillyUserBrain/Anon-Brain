"""Gameplay library: pick random, never-repeating slices of your recordings.

Point it at a folder of gameplay videos (hour-long recordings are perfect).
Each render takes an unused slice and the library remembers it, so no two
videos share footage. When everything is used up you can reset the history.
"""

import json
import random
from dataclasses import dataclass
from pathlib import Path

from .engine import EngineError, get_duration
from .settings import data_dir, write_json

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv"}
EDGE_SKIP = 3.0   # skip the first/last few seconds (menus, recording start/stop)


class LibraryExhausted(EngineError):
    """No unused footage long enough for this video."""


@dataclass
class Segment:
    path: Path
    start: float
    length: float


def find_videos(folder: Path) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in VIDEO_EXTS and p.is_file())


def _merge(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


class GameplayLibrary:
    def __init__(self, ledger_path: Path | None = None):
        self.ledger_path = ledger_path or data_dir() / "used_footage.json"
        try:
            self.ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.ledger = {}

    # --- bookkeeping -------------------------------------------------------
    @staticmethod
    def _key(path: Path) -> str:
        st = path.stat()
        return f"{path.resolve()}|{st.st_size}"

    def _entry(self, path: Path) -> dict:
        key = self._key(path)
        entry = self.ledger.get(key)
        if entry is None:
            entry = {"length": get_duration(path), "used": []}
            self.ledger[key] = entry
            self._save()
        return entry

    def _save(self):
        write_json(self.ledger_path, self.ledger, indent=1)

    def _free(self, entry: dict, reuse: bool = False) -> list[tuple[float, float]]:
        """Parts that can be picked: not used yet (unless reuse) and not boring."""
        lo, hi = EDGE_SKIP, entry["length"] - EDGE_SKIP
        if hi - lo < 1:
            lo, hi = 0.0, entry["length"]
        free, cur = [], lo
        taken = entry.get("bad", []) + ([] if reuse else entry["used"])
        for s, e in _merge(taken):
            if s > cur:
                free.append((cur, min(s, hi)))
            cur = max(cur, e)
        if cur < hi:
            free.append((cur, hi))
        return [(s, e) for s, e in free if e > s]

    # --- public ------------------------------------------------------------
    def stats(self, videos: list[Path]) -> dict:
        """Total and unused footage (seconds) across these videos."""
        total = unused = 0.0
        for v in videos:
            entry = self._entry(v)
            total += entry["length"]
            unused += sum(e - s for s, e in self._free(entry))
        return {"count": len(videos), "total": total, "unused": unused}

    def pick(self, videos: list[Path], length: float, rng=random,
             avoid_boring: bool = False, status=lambda m: None,
             reuse: bool = False) -> Segment:
        """Random unused slice of `length` seconds from any of the videos
        (reuse=True: from anywhere, used or not).

        With avoid_boring, slices that are mostly menus, loading or black
        screens are skipped and remembered so they're never picked again."""
        if not avoid_boring:
            return self._pick(videos, length, rng, reuse)
        from .boring import is_boring
        seg = None
        for attempt in range(8):
            try:
                seg = self._pick(videos, length, rng, reuse)
            except LibraryExhausted:
                if seg is None:
                    raise
                return seg                   # only boring bits left: better than nothing
            if seg.start is None or self._entry(seg.path)["length"] < length:
                return seg                   # short clip that loops: nothing to choose
            status("Checking the gameplay for menus and loading screens…")
            if not is_boring(seg.path, seg.start, seg.length):
                return seg
            entry = self._entry(seg.path)
            entry["bad"] = _merge(entry.get("bad", []) + [[seg.start, seg.start + seg.length]])
            self._save()
        return seg                           # everything looked boring: use the last pick

    def _pick(self, videos: list[Path], length: float, rng=random,
              reuse: bool = False) -> Segment:
        if not videos:
            raise EngineError("No gameplay videos found in that folder.")
        options = []  # (path, free_start, free_end)
        for v in videos:
            for s, e in self._free(self._entry(v), reuse):
                if e - s >= length:
                    options.append((v, s, e))
        if not options:
            if len(videos) == 1 and self._entry(videos[0])["length"] < length:
                return Segment(videos[0], 0.0, length)  # short clip: engine loops it
            raise LibraryExhausted(
                "All of your gameplay footage has been used. Add more videos to the "
                "folder, reset the used-footage history, or turn on Allow repeats on the "
                "Gameplay step."
            )
        # Weight by how many different start points each gap allows
        weights = [(e - s - length) + 1 for _, s, e in options]
        path, s, e = rng.choices(options, weights=weights)[0]
        start = round(rng.uniform(s, e - length), 2)
        return Segment(path, start, length)

    def mark_used(self, seg: Segment):
        entry = self._entry(seg.path)
        entry["used"] = _merge(entry["used"] + [[seg.start, seg.start + seg.length]])
        self._save()

    def reset(self, videos: list[Path] | None = None):
        """Forget used footage (for these videos, or everything)."""
        if videos is None:
            self.ledger = {}
        else:
            for v in videos:
                self.ledger.pop(self._key(v), None)
        self._save()
