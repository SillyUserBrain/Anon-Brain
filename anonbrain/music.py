"""Background music from a folder: each video gets a random song, from a random part.

The last few songs are remembered so the same one doesn't come up twice in a row.
"""

import json
import random
from pathlib import Path

from .engine import EngineError, get_duration
from .settings import data_dir, write_json

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".wma"}
AVOID_LAST = 10     # don't repeat any of the last this-many songs (if the folder has more)
END_ROOM = 4.0      # seconds kept clear of the song's end (fade-outs, silence)


def find_songs(folder) -> list[Path]:
    folder = Path(folder or "")
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*")
                  if p.suffix.lower() in AUDIO_EXTS and p.is_file())


def random_start(song_length: float, video_length: float, rng=random) -> float:
    """A start point where the whole video plays before the song ends. Songs shorter
    than the video start at the beginning (and loop)."""
    room = song_length - video_length - END_ROOM
    if room < 1.0:
        return 0.0
    return round(rng.uniform(0.0, room), 1)


def _recent_path() -> Path:
    return data_dir() / "recent_songs.json"


def _recent() -> list[str]:
    try:
        return list(json.loads(_recent_path().read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return []


def remember(song):
    """Count a song as just played (so it isn't picked again soon)."""
    try:
        write_json(_recent_path(), (_recent() + [str(song)])[-50:])
    except OSError:
        pass


def pick(folder, video_length: float, rng=random, record: bool = True,
         repeats: bool = False) -> tuple[Path, float]:
    """(song, start in seconds) for a video this long. record=False for a
    preview: the song isn't counted as played. repeats=True: any song, even one
    that just played."""
    songs = find_songs(folder)
    if not songs:
        raise EngineError("No songs found in your music folder. Add some (MP3, WAV, M4A…) "
                          "or pick a single song on the Voice & Music step.")
    recent = _recent()
    avoid = set(recent[-min(AVOID_LAST, len(songs) - 1):]) \
        if len(songs) > 1 and not repeats else set()
    fresh = [s for s in songs if str(s) not in avoid]
    rng.shuffle(fresh)
    others = [s for s in songs if str(s) in avoid]
    rng.shuffle(others)
    for song in fresh + others:           # a broken file just gets skipped
        try:
            length = get_duration(song)
        except EngineError:
            continue
        if length <= 0:
            continue
        if record:
            remember(song)
        return song, random_start(length, video_length, rng)
    raise EngineError("None of the songs in your music folder could be opened.")
