"""Faster renders on your graphics card (NVIDIA NVENC, AMD AMF, Intel Quick Sync).

detect() test-encodes a tiny clip with each hardware encoder your FFmpeg has,
once, and remembers which actually work on this PC. If a hardware encode
ever fails, the renderer falls back to the CPU (libx264) on its own.
"""

import json
import subprocess
import threading
from pathlib import Path

from .settings import data_dir

KINDS = {
    "nvidia": ("h264_nvenc", "NVIDIA (NVENC)"),
    "amd": ("h264_amf", "AMD (AMF)"),
    "intel": ("h264_qsv", "Intel (Quick Sync)"),
}
ORDER = ["nvidia", "amd", "intel"]
CHOICES = [("auto", "Automatic (fastest that works)"), ("nvidia", "NVIDIA graphics (NVENC)"),
           ("amd", "AMD graphics (AMF)"), ("intel", "Intel graphics (Quick Sync)"),
           ("cpu", "Processor only (most compatible)")]

_lock = threading.Lock()
_found: dict | None = None


def _flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _cache_key() -> str:
    from .appinfo import find_tool
    ff = find_tool("ffmpeg")
    try:
        return f"{ff}|{Path(ff).stat().st_mtime}"
    except OSError:
        return ff


def video_args(kind: str, fast: bool = False) -> list[str]:
    """FFmpeg output options for each encoder (similar quality to CRF 20)."""
    if kind == "nvidia":
        return ["-c:v", "h264_nvenc", "-preset", "p1" if fast else "p4", "-tune", "hq",
                "-rc", "vbr", "-cq", "27" if fast else "21", "-b:v", "0", "-pix_fmt", "yuv420p"]
    if kind == "amd":
        q = (26, 28, 30) if fast else (20, 22, 24)
        return ["-c:v", "h264_amf", "-quality", "speed" if fast else "balanced", "-rc", "cqp",
                "-qp_i", str(q[0]), "-qp_p", str(q[1]), "-qp_b", str(q[2]),
                "-pix_fmt", "yuv420p"]
    if kind == "intel":
        return ["-c:v", "h264_qsv", "-preset", "veryfast" if fast else "medium",
                "-global_quality", "28" if fast else "22", "-pix_fmt", "nv12"]
    return ["-c:v", "libx264", "-preset", "ultrafast" if fast else "veryfast",
            "-crf", "26" if fast else "20", "-pix_fmt", "yuv420p"]


def _compiled() -> set[str]:
    try:
        from .appinfo import find_tool
        r = subprocess.run([find_tool("ffmpeg") or "ffmpeg", "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=20, creationflags=_flags())
    except (OSError, subprocess.SubprocessError):
        return set()
    return {k for k, (name, _) in KINDS.items() if f" {name} " in r.stdout}


def _works(kind: str) -> bool:
    """Encode half a second of video with this encoder."""
    from .appinfo import find_tool
    cmd = [find_tool("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=0.5",
           *video_args(kind), "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=25,
                           creationflags=_flags())
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def detect(force: bool = False) -> dict:
    """{"nvidia": bool, "amd": bool, "intel": bool} for this PC (cached)."""
    global _found
    with _lock:
        if _found is not None and not force:
            return _found
        path = data_dir() / "encoders.json"
        key = _cache_key()
        if not force:
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                if saved.get("key") == key:
                    _found = saved["found"]
                    return _found
            except (OSError, ValueError, KeyError):
                pass
        have = _compiled()
        _found = {k: (k in have and _works(k)) for k in ORDER}
        try:
            path.write_text(json.dumps({"key": key, "found": _found}), encoding="utf-8")
        except OSError:
            pass
        return _found


def resolve(choice: str) -> str:
    """Setting ("auto", "nvidia", ...) -> the encoder to use now."""
    found = detect()
    if choice == "cpu":
        return "cpu"
    if choice in KINDS:
        return choice if found.get(choice) else "cpu"
    return next((k for k in ORDER if found.get(k)), "cpu")


def describe(found: dict) -> str:
    names = [KINDS[k][1] for k in ORDER if found.get(k)]
    return ("Found: " + ", ".join(names)) if names else \
        "No graphics-card encoder found, so videos are made on the processor."
