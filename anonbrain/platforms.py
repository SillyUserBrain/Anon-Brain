"""How long each short-video app allows (checked October 2026).

Limits change; these are the strict, official numbers where sources disagree.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    max_s: float              # longest video the app accepts
    note: str = ""
    shapes: tuple = ()        # shapes it treats as a short ("" = any)


PLATFORMS = [
    Platform("shorts", "YouTube Shorts", 180,
             "Must be vertical or square, or it becomes a normal video.", ("9:16", "1:1")),
    Platform("tiktok", "TikTok", 600,
             "10 min when recorded in the app (uploads can be 60 min). Creator Rewards "
             "only pays on videos over 1 minute."),
    Platform("reels", "Instagram Reels", 180,
             "Longer Reels mostly stop reaching people who don't follow you."),
    Platform("facebook", "Facebook Reels", 90),
    Platform("snapchat", "Snapchat Spotlight", 60),
    Platform("x", "X (free account)", 140, "Premium accounts can post much longer videos."),
]
BY_KEY = {p.key: p for p in PLATFORMS}
MAX_SPEED = 1.3     # fastest the voice can be sped up and still sound natural


def fmt(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def check(length: float, shape: str) -> dict:
    """Which apps a video of this length and shape fits."""
    fits, too_long, wrong_shape = [], [], []
    for p in PLATFORMS:
        if p.shapes and shape not in p.shapes:
            wrong_shape.append(p)
        elif length > p.max_s:
            too_long.append(p)
        else:
            fits.append(p)
    return {"fits": fits, "too_long": too_long, "wrong_shape": wrong_shape}


def speed_to_fit(length: float, voice_part: float, limit: float, current: float = 1.0):
    """Voice speed needed to bring `length` under `limit`. voice_part is how much of
    the length is the voice itself (the rest is pauses, lead-in, end card).
    Returns the new speed, or None if even MAX_SPEED isn't enough."""
    if length <= limit:
        return current
    fixed = length - voice_part
    room = limit - fixed - 0.3
    if room <= 0:
        return None
    speed = current * voice_part / room
    return round(speed + 0.005, 2) if speed <= MAX_SPEED else None
