"""Your own AI voices, added in Settings → Voices.

Kinds of voice you can add:
  elevenlabs - any ElevenLabs voice by its ID (Voice Library, or one shared with you)
  piper      - a Piper voice model (.onnx + .onnx.json), free and offline
  kokoro     - a Kokoro voice file (.npy, or a .bin / .npz holding voices), free and offline
  blend      - a new voice made by mixing two of the free voices
  server     - any text-to-speech server with an OpenAI-style /audio/speech endpoint
               (OpenAI, Kokoro-FastAPI, AllTalk, openedai-speech, and many others)

Voices are saved in settings.json as {"id", "name", "kind", ...}. Files are
copied into %APPDATA%\\AnonBrain\\voices\\custom so the originals can move.
A server's API key goes in Windows Credential Manager, never in a file.
"""

import shutil
import subprocess
import sys
import threading
import uuid
import wave
from pathlib import Path
from typing import Callable

import keyring
import numpy as np
import requests

from .engine import EngineError
from .settings import Settings, data_dir

PREFIX = "custom:"
KEYRING_SERVICE = "Anon Brain"

KINDS = {
    "elevenlabs": "ElevenLabs voice ID",
    "piper": "Piper voice file (.onnx)",
    "kokoro": "Kokoro voice file (.npy / .bin)",
    "blend": "Mix two free voices",
    "server": "Voice server (OpenAI-style)",
}

_piper_cache: dict = {}
_lock = threading.Lock()


class CustomVoiceError(EngineError):
    pass


def is_custom(voice_id: str) -> bool:
    return voice_id.startswith(PREFIX)


def folder() -> Path:
    d = data_dir() / "voices" / "custom"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- the saved list ------------------------------------------------------------
def all_voices(settings: Settings | None = None) -> list[dict]:
    return list((settings or Settings())["custom_voices"] or [])


def get(voice_id: str, settings: Settings | None = None) -> dict | None:
    key = voice_id.removeprefix(PREFIX)
    return next((v for v in all_voices(settings) if v["id"] == key), None)


def describe(v: dict) -> str:
    kind = v.get("kind")
    if kind == "elevenlabs":
        return "ElevenLabs"
    if kind == "piper":
        return "Piper · offline"
    if kind == "kokoro":
        return "Kokoro file · offline"
    if kind == "blend":
        return "Free voice mix · offline"
    if kind == "server":
        host = v.get("url", "").split("//")[-1].split("/")[0]
        return f"Server · {host}" if host else "Server"
    return kind or ""


def add(settings: Settings, v: dict, api_key: str = "") -> dict:
    """Save a new voice. Files are copied into the app's own folder."""
    v = dict(v)
    v["id"] = uuid.uuid4().hex[:10]
    v["name"] = (v.get("name") or "My voice").strip()
    if v["kind"] in ("piper", "kokoro"):
        dest = folder() / v["id"]
        dest.mkdir(parents=True, exist_ok=True)
        src = Path(v["file"])
        shutil.copy2(src, dest / src.name)
        if v["kind"] == "piper":
            cfg = _piper_config(src)
            if cfg is None:
                raise CustomVoiceError(f"Couldn't find {src.name}.json next to the voice "
                                       "file. Piper voices come as two files: put both "
                                       "in the same folder.")
            shutil.copy2(cfg, dest / cfg.name)
        v["file"] = str(dest / src.name)
    if v["kind"] == "server" and api_key:
        keyring.set_password(KEYRING_SERVICE, f"voice:{v['id']}", api_key)
    settings["custom_voices"] = all_voices(settings) + [v]
    return v


def remove(settings: Settings, voice_id: str):
    key = voice_id.removeprefix(PREFIX)
    settings["custom_voices"] = [v for v in all_voices(settings) if v["id"] != key]
    shutil.rmtree(folder() / key, ignore_errors=True)
    try:
        keyring.delete_password(KEYRING_SERVICE, f"voice:{key}")
    except Exception:
        pass


def rename(settings: Settings, voice_id: str, name: str):
    key = voice_id.removeprefix(PREFIX)
    voices = all_voices(settings)
    for v in voices:
        if v["id"] == key:
            v["name"] = name.strip() or v["name"]
    settings["custom_voices"] = voices


# --- speaking ----------------------------------------------------------------------
def synthesize(v: dict, text: str, out: Path,
               status: Callable[[str, float], None] = lambda m, f: None) -> Path:
    """Speak `text` with a custom voice into `out` (a .wav file).
    (ElevenLabs voices go through voice.py instead, which also gets timings.)"""
    kind = v.get("kind")
    if kind == "piper":
        return _piper(v, text, out, status)
    if kind in ("kokoro", "blend"):
        return _kokoro(v, text, out, status)
    if kind == "server":
        return _server(v, text, out)
    raise CustomVoiceError(f"Unknown voice type: {kind}")


def _write_wav(samples: np.ndarray, rate: int, out: Path):
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


# Kokoro files and mixes ----------------------------------------------------------
def kokoro_style(v: dict) -> np.ndarray:
    """The voice 'style' array Kokoro speaks with."""
    from . import free_tts
    if v["kind"] == "blend":
        if not free_tts.is_downloaded():
            free_tts.download()
        bank = np.load(free_tts.model_dir() / "voices-v1.0.bin")
        mix = float(v.get("mix", 0.5))
        return (bank[v["a"]] * (1 - mix) + bank[v["b"]] * mix).astype(np.float32)
    path = Path(v["file"])
    if not path.exists():
        raise CustomVoiceError(f"The voice file for '{v['name']}' is missing. Remove the "
                               "voice and add it again.")
    data = np.load(path, allow_pickle=False)
    if isinstance(data, np.lib.npyio.NpzFile):          # .bin / .npz: a bank of voices
        names = list(data.keys())
        pick = v.get("pick") or names[0]
        arr = data[pick if pick in names else names[0]]
    else:
        arr = data
    arr = np.asarray(arr, np.float32)
    if arr.ndim == 2:
        arr = arr[:, None, :]
    if arr.ndim != 3 or arr.shape[-1] != 256:
        raise CustomVoiceError("That file isn't a Kokoro voice (expected a 510 × 1 × 256 "
                               "array).")
    return arr


def kokoro_names(path: Path) -> list[str]:
    """Voices inside a .bin / .npz bank (empty for a single .npy voice)."""
    try:
        data = np.load(path, allow_pickle=False)
    except Exception as e:
        raise CustomVoiceError(f"Couldn't open that file: {e}")
    return list(data.keys()) if isinstance(data, np.lib.npyio.NpzFile) else []


def _kokoro(v: dict, text: str, out: Path, status) -> Path:
    from . import free_tts
    if not free_tts.is_downloaded():
        free_tts.download(status)
    style = kokoro_style(v)
    british = v.get("accent") == "uk" or (v["kind"] == "blend" and v["a"].startswith("b"))
    with free_tts._lock:
        samples, rate = free_tts._load().create(text, voice=style, speed=float(v.get("speed", 1.0)),
                                                lang="en-gb" if british else "en-us")
    _write_wav(samples, rate, out)
    return out


# Piper ----------------------------------------------------------------------------
def _piper_config(model: Path) -> Path | None:
    for c in (model.with_name(model.name + ".json"), model.with_suffix(".json")):
        if c.exists():
            return c
    return None


def piper_installed() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def install_piper(status: Callable[[str, float], None] = lambda m, f: None):
    """Piper is optional: installed into the app's own Python the first time
    you add a Piper voice (a few MB)."""
    if piper_installed():
        return
    if getattr(sys, "frozen", False):
        raise CustomVoiceError("Piper voices need the full (not .exe) version of Anon Brain, "
                               "or run:  pip install piper-tts")
    status("Setting up Piper voices (one time)…", 0.1)
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                        "piper-tts"], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise CustomVoiceError("Couldn't install Piper. Check your internet connection.\n"
                               + (r.stderr or r.stdout)[-600:])
    import importlib
    importlib.invalidate_caches()


def _piper(v: dict, text: str, out: Path, status) -> Path:
    install_piper(status)
    from piper import PiperVoice
    model = Path(v["file"])
    if not model.exists():
        raise CustomVoiceError(f"The voice file for '{v['name']}' is missing. Remove the "
                               "voice and add it again.")
    with _lock:
        voice = _piper_cache.get(str(model))
        if voice is None:
            voice = PiperVoice.load(str(model), config_path=str(_piper_config(model) or ""))
            _piper_cache[str(model)] = voice
        with wave.open(str(out), "wb") as wf:
            if hasattr(voice, "synthesize_wav"):
                voice.synthesize_wav(text, wf)
            else:                                   # older piper-tts
                voice.synthesize(text, wf)
    return out


# OpenAI-style servers -------------------------------------------------------------
def server_key(v: dict) -> str:
    try:
        return keyring.get_password(KEYRING_SERVICE, f"voice:{v['id']}") or ""
    except Exception:
        return ""


def _server(v: dict, text: str, out: Path, api_key: str | None = None) -> Path:
    url = v.get("url", "").rstrip("/")
    if not url:
        raise CustomVoiceError("This voice has no server address.")
    if not url.endswith("/audio/speech"):
        url += "/audio/speech"
    key = api_key if api_key is not None else server_key(v)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": v.get("model") or "tts-1", "voice": v.get("voice") or "alloy",
            "input": text, "response_format": "wav"}
    try:
        r = requests.post(url, json=body, headers=headers, timeout=180)
    except requests.RequestException as e:
        raise CustomVoiceError(f"Couldn't reach the voice server at {url}. Is it running?\n{e}")
    if not r.ok:
        raise CustomVoiceError(f"The voice server said {r.status_code}: {r.text[:300]}")
    raw = out.with_suffix(".download")
    raw.write_bytes(r.content)
    # servers don't always honour "wav": convert whatever came back
    from .engine import _tool, run_tool
    c = run_tool([_tool("ffmpeg"), "-y", "-loglevel", "error", "-i", raw, "-ac", "1", out])
    raw.unlink(missing_ok=True)
    if c.returncode != 0:
        raise CustomVoiceError("The voice server sent back something that isn't audio.")
    return out


def test_voice(v: dict, out: Path, api_key: str | None = None,
               status: Callable[[str, float], None] = lambda m, f: None) -> Path:
    """Make a short sample with a voice that hasn't been saved yet."""
    text = "Be me. Find a post. Turn it into a video."
    if v.get("kind") == "server":
        return _server(v, text, out, api_key)
    if v.get("kind") == "piper":
        model = Path(v["file"])
        if _piper_config(model) is None:
            raise CustomVoiceError(f"Couldn't find {model.name}.json next to the voice file.")
    return synthesize(v, text, out, status)
