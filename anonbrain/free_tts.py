"""Free voices that run on your own PC (Kokoro, no account or key needed).

The voice model (~120 MB) downloads once, the first time a free voice is
used, into %APPDATA%\\AnonBrain\\voices. After that it works offline.
"""

import threading
import wave
from pathlib import Path
from typing import Callable

import numpy as np
import requests

from .engine import EngineError
from .settings import data_dir

BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {
    "kokoro-v1.0.int8.onnx": 92_361_271,
    "voices-v1.0.bin": 28_214_398,
}
PREFIX = "free:"

# id -> display name. American voices first, then British.
VOICES = {
    "am_michael": "Michael · US male",
    "am_adam": "Adam · US male",
    "am_eric": "Eric · US male",
    "am_liam": "Liam · US male",
    "am_onyx": "Onyx · US male, deep",
    "am_puck": "Puck · US male, upbeat",
    "am_fenrir": "Fenrir · US male",
    "af_heart": "Heart · US female",
    "af_bella": "Bella · US female",
    "af_sarah": "Sarah · US female",
    "af_nicole": "Nicole · US female, soft",
    "af_sky": "Sky · US female",
    "af_nova": "Nova · US female",
    "bm_george": "George · UK male",
    "bm_lewis": "Lewis · UK male",
    "bm_daniel": "Daniel · UK male",
    "bf_emma": "Emma · UK female",
    "bf_isabella": "Isabella · UK female",
    "bf_alice": "Alice · UK female",
}
DEFAULT = PREFIX + "am_michael"

_model = None
_lock = threading.Lock()


class FreeVoiceError(EngineError):
    pass


def model_dir() -> Path:
    d = data_dir() / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_downloaded() -> bool:
    return all((model_dir() / f).exists() and (model_dir() / f).stat().st_size == size
               for f, size in FILES.items())


def download(status: Callable[[str, float], None] = lambda m, f: None):
    """Fetch the free voice model (one time, ~120 MB)."""
    total = sum(FILES.values())
    done = 0
    for name, size in FILES.items():
        dest = model_dir() / name
        if dest.exists() and dest.stat().st_size == size:
            done += size
            continue
        part = dest.with_suffix(dest.suffix + ".part")
        try:
            with requests.get(BASE + name, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(part, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        status(f"Downloading free voices (one time): {done / 1e6:.0f} of "
                               f"{total / 1e6:.0f} MB", done / total)
        except requests.RequestException:
            raise FreeVoiceError("Couldn't download the free voices. Check your internet "
                                 "connection and try again (it's only needed once).")
        part.replace(dest)


def _load():
    global _model
    if _model is None:
        from kokoro_onnx import Kokoro
        d = model_dir()
        _model = Kokoro(str(d / "kokoro-v1.0.int8.onnx"), str(d / "voices-v1.0.bin"))
    return _model


def synthesize(text: str, voice_id: str, out: Path, speed: float = 1.0,
               status: Callable[[str, float], None] = lambda m, f: None) -> Path:
    """Speak `text` with a free voice and save it as a WAV file."""
    voice = voice_id.removeprefix(PREFIX)
    if voice not in VOICES:
        voice = DEFAULT.removeprefix(PREFIX)
    if not is_downloaded():
        download(status)
    with _lock:   # the model isn't thread-safe
        samples, rate = _load().create(text, voice=voice, speed=speed,
                                       lang="en-gb" if voice.startswith("b") else "en-us")
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return out
