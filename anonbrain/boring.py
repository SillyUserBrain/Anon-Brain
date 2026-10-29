"""Spot boring gameplay: frozen menus, loading screens, black screens.

Only the keyframes of the chosen slice are decoded (tiny and grey), so a
30-second check takes about a second even on long 1080p recordings.
"""

from pathlib import Path

import numpy as np

from .engine import _tool, run_tool

W, H = 64, 36
STILL_DIFF = 2.2      # average pixel change (0-255) below this = nothing moving
DARK = 14             # average brightness below this = black screen
MAX_STILL = 0.45      # more than this share of still moments = boring
MAX_DARK = 0.40


def _frames(path: Path, start: float, length: float, keyframes_only: bool) -> np.ndarray:
    cmd = [_tool("ffmpeg"), "-v", "error"]
    if keyframes_only:
        cmd += ["-skip_frame", "nokey"]
    cmd += ["-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(path), "-an",
            "-vf", (f"scale={W}:{H}" if keyframes_only else f"fps=1,scale={W}:{H}") + ",format=gray",
            "-fps_mode", "passthrough", "-f", "rawvideo", "-"]
    r = run_tool(cmd, text=False)
    data = np.frombuffer(r.stdout, dtype=np.uint8)
    n = len(data) // (W * H)
    return data[: n * W * H].reshape(n, H, W).astype(np.int16)


def score(path: Path, start: float, length: float) -> dict:
    """Share of the slice that's frozen or dark."""
    f = _frames(path, start, length, keyframes_only=True)
    if len(f) < 6:                       # long keyframe gaps: sample once a second instead
        f = _frames(path, start, length, keyframes_only=False)
    if len(f) < 2:
        return {"still": 0.0, "dark": 0.0, "samples": len(f)}
    diffs = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
    bright = f.mean(axis=(1, 2))
    return {"still": float((diffs < STILL_DIFF).mean()),
            "dark": float((bright < DARK).mean()),
            "samples": int(len(f))}


def is_boring(path: Path, start: float, length: float) -> bool:
    try:
        s = score(path, start, length)
    except Exception:
        return False                     # never block a render over this check
    return s["still"] > MAX_STILL or s["dark"] > MAX_DARK
