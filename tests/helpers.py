"""Shared bits for the checks: a throwaway data folder and small test videos."""

import functools
import os
import subprocess
import tempfile
from pathlib import Path

WORK = Path(tempfile.mkdtemp(prefix="anonbrain_tests_"))


def use_scratch_data():
    """Point the app's data folder at a temporary one, so the checks never touch your
    real settings, history or sign-ins. Must run before anything from anonbrain loads."""
    os.environ["APPDATA"] = str(WORK / "appdata")
    (WORK / "appdata").mkdir(exist_ok=True)


def ffmpeg(*args):
    from anonbrain.engine import _tool
    r = subprocess.run([_tool("ffmpeg"), "-v", "error", "-y", *map(str, args)],
                       capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert r.returncode == 0, r.stderr[-600:]


@functools.lru_cache(None)
def gameplay() -> Path:
    """12 s of moving 1280x720 60 fps 'gameplay' with sound."""
    out = WORK / "gameplay.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=60", "-f", "lavfi",
           "-i", "sine=f=330:sample_rate=48000", "-t", 12, "-c:v", "libx264", "-preset",
           "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", out)
    return out


@functools.lru_cache(None)
def movie() -> Path:
    """6 s wide (2.39:1) 'movie clip' with sound."""
    out = WORK / "movie.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x536:rate=24", "-f", "lavfi",
           "-i", "sine=f=220:sample_rate=48000", "-t", 6, "-c:v", "libx264", "-preset",
           "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", out)
    return out


@functools.lru_cache(None)
def music() -> Path:
    out = WORK / "music.mp3"
    ffmpeg("-f", "lavfi", "-i", "sine=f=440:d=30", out)
    return out


@functools.lru_cache(None)
def songs() -> Path:
    """A folder of four songs of different lengths (one in a subfolder)."""
    d = WORK / "songs"
    (d / "more").mkdir(parents=True, exist_ok=True)
    for name, f, secs in (("one.mp3", 300, 40), ("two.m4a", 500, 25),
                          ("more/three.wav", 700, 60), ("short.mp3", 900, 5)):
        ffmpeg("-f", "lavfi", "-i", f"sine=f={f}:d={secs}", d / name)
    (d / "notes.txt").write_text("not a song")
    return d


@functools.lru_cache(None)
def reddit_card():
    """(png, PostText) of a drawn Reddit post."""
    from anonbrain.cards import Para, Post, draw
    post = Post("reddit", author="tester", when="2h", subject="AITA for testing everything?",
                paras=[Para("My roommate never runs the tests."),
                       Para("So I made the app run them by itself.")],
                community="AmItheAsshole", score="1.2k", comments="88")
    png, pt = draw(post, WORK / "card.png")
    return str(png), pt


def probe(path) -> dict:
    """{"duration": s, "fps": f, "audio": bool, "width": w, "height": h}"""
    import json
    from anonbrain.engine import _tool
    r = subprocess.run([_tool("ffprobe"), "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,r_frame_rate,width,height",
                        "-of", "json", str(path)], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    d = json.loads(r.stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    num, den = v["r_frame_rate"].split("/")
    return {"duration": float(d["format"]["duration"]), "fps": float(num) / float(den),
            "audio": any(s["codec_type"] == "audio" for s in d["streams"]),
            "width": v["width"], "height": v["height"]}
