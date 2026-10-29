"""Posting finished videos to TikTok, YouTube Shorts and Instagram Reels.

Each platform module has the same few functions:
    connected() -> bool, account() -> str, disconnect(),
    post(video, caption, title, status, **options) -> Posted
"""

from dataclasses import dataclass

import requests


class PostError(Exception):
    pass


@dataclass
class Posted:
    state: str            # "posted" / "inbox" (finish in the app) / "private" / "processing"
    url: str = ""
    note: str = ""        # shown to you, e.g. "Posted as private: TikTok hasn't approved..."
    id: str = ""


NAMES = {"tiktok": "TikTok", "youtube": "YouTube Shorts", "instagram": "Instagram Reels"}
ORDER = ["tiktok", "youtube", "instagram"]


def module(key: str):
    from . import instagram, tiktok, youtube
    return {"tiktok": tiktok, "youtube": youtube, "instagram": instagram}[key]


def call(method: str, url: str, what: str, **kw) -> requests.Response:
    kw.setdefault("timeout", 60)
    try:
        r = requests.request(method, url, **kw)
    except requests.RequestException as e:
        raise PostError(f"Couldn't reach {what}. Check your internet connection. ({e.__class__.__name__})")
    return r
