"""Quick test of the Anon Brain engine (no UI yet).

Usage (from the AnonBrain folder):
    py make_video.py test_media\\gameplay.mp4 test_media\\post.jpg
    py make_video.py gameplay.mp4 post.jpg --seconds 20 --out output\\my_video.mp4
"""

import argparse
import sys
import time
from pathlib import Path

from anonbrain.engine import EngineError, render


def main() -> int:
    p = argparse.ArgumentParser(description="Anon Brain: post + gameplay -> vertical video")
    p.add_argument("gameplay", help="gameplay video file")
    p.add_argument("post", help="screenshot of the post (png/jpg)")
    p.add_argument("--seconds", type=float, default=30, help="video length (default 30)")
    p.add_argument("--start", type=float, default=None, help="gameplay start time (default: random)")
    p.add_argument("--game-audio", action="store_true", help="keep the game's sound")
    p.add_argument("--out", default=None, help="output file (default: output/anonbrain_<time>.mp4)")
    a = p.parse_args()

    out = Path(a.out) if a.out else Path("output") / f"anonbrain_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    print("Rendering... (this can take a little while)")
    try:
        render(a.gameplay, a.post, out, duration=a.seconds,
               start=a.start, keep_game_audio=a.game_audio)
    except EngineError as e:
        print(f"\nError: {e}")
        return 1
    print(f"Done! Saved to {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
