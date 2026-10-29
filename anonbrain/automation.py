"""Automate: find posts in your subreddits, make videos with a preset, post them.

Settings live in settings["automation"]; the queue of videos it made (and
where each was posted) lives in %APPDATA%\\AnonBrain\\automation.json.

run(...) is one whole round: pick posts -> draw cards -> make videos ->
post the ones set to auto-post, leave the rest waiting for your review.
"""

import copy
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from . import reddit_source as rs
from .layout import FORMATS, MAX_POST_HEIGHT, aspect, default_box, margins
from .platforms import BY_KEY
from .settings import data_dir, write_json

PLATFORM_LIMIT = {"tiktok": BY_KEY["tiktok"].max_s, "youtube": BY_KEY["shorts"].max_s,
                  "instagram": BY_KEY["reels"].max_s}
CARD_WIDTH = 420

DEFAULTS = {
    "enabled": False,
    "subs": ["AskReddit"],
    "sort": "top",
    "period": "day",
    "filters": {"min_score": 500, "min_comments": 20, "max_age_hours": 0, "min_words": 40,
                "max_words": 450, "nsfw": False, "text_only": True, "skip_words": "",
                "need_words": "", "rank": "both"},
    "comments": 0,          # also read this many top comments after the post
    "per_run": 1,           # videos each time it runs
    "times": ["11:00", "17:00", "21:00"],
    "days": [0, 1, 2, 3, 4, 5, 6],
    "catch_up": True,       # PC was off/asleep at a time: run when it's back (within 3 h)
    "preset": "",           # "" = your current settings
    "gameplay": "",         # folder of gameplay videos
    "reddit_theme": "dark",
    "hook_title": False,    # also show the title big at the start
    "min_length": 0,        # seconds; short stories keep going with gameplay + music
    "platforms": {
        "tiktok": {"on": False, "auto": False, "mode": "inbox"},
        "youtube": {"on": False, "auto": False, "privacy": "public"},
        "instagram": {"on": False, "auto": False},
    },
    "caption": "{title}\n\n#reddit #redditstories #{sub} #storytime",
    "tray": True,           # keep running in the tray when the window is closed
}


def config(settings) -> dict:
    """The automation settings with every key filled in."""
    saved = settings["automation"] or {}
    cfg = copy.deepcopy(DEFAULTS)
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            for k2, v2 in v.items():
                if isinstance(v2, dict) and isinstance(cfg[k].get(k2), dict):
                    cfg[k][k2].update(v2)
                else:
                    cfg[k][k2] = v2
        else:
            cfg[k] = v
    return cfg


def on_platforms(cfg) -> list[str]:
    return [k for k in ("tiktok", "youtube", "instagram") if cfg["platforms"][k]["on"]]


def length_limit(cfg) -> float:
    """Longest video every chosen app accepts (3 min if none chosen yet)."""
    keys = on_platforms(cfg)
    return min((PLATFORM_LIMIT[k] for k in keys), default=180.0)


# --- the queue ----------------------------------------------------------------------
class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "automation.json"
        self.lock = threading.RLock()
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        self.items: list[dict] = d.get("items", [])
        self.used: list[str] = d.get("used", [])
        self.runs: dict = d.get("runs", {})
        self.log: list[str] = d.get("log", [])

    def save(self):
        with self.lock:
            write_json(self.path, {"items": self.items, "used": self.used[-5000:],
                                   "runs": dict(list(self.runs.items())[-200:]),
                                   "log": self.log[-300:]}, indent=1)

    def note(self, text: str):
        with self.lock:
            self.log.append(time.strftime("%b %d %H:%M  ") + text)
            self.save()

    def add(self, item: dict):
        with self.lock:
            self.items.insert(0, item)
            if item.get("rid") and item["rid"] not in self.used:
                self.used.append(item["rid"])
            self.save()

    def get(self, iid: str) -> dict | None:
        return next((i for i in self.items if i["id"] == iid), None)

    def remove(self, iid: str, delete_video=False):
        with self.lock:
            it = self.get(iid)
            self.items = [i for i in self.items if i["id"] != iid]
            self.save()
        if it and delete_video and it.get("video"):
            Path(it["video"]).unlink(missing_ok=True)

    def waiting(self) -> list[dict]:
        """Videos with at least one app waiting for your OK."""
        return [i for i in self.items
                if any(t["state"] == "waiting" for t in i.get("targets", {}).values())]


# --- schedule -----------------------------------------------------------------------
def parse_time(t: str):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*([ap]m)?\s*", t.lower())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if m.group(3):
        h = h % 12 + (12 if m.group(3) == "pm" else 0)
    return (h, mi) if 0 <= h < 24 and 0 <= mi < 60 else None


def due(cfg, store: Store, now: datetime | None = None) -> str:
    """The time slot to run now ('2026-10-28 17:00'), or ''."""
    if not cfg["enabled"]:
        return ""
    now = now or datetime.now()
    late = timedelta(hours=3) if cfg["catch_up"] else timedelta(minutes=10)
    for day_back in (0, 1):
        day = now - timedelta(days=day_back)
        if day.weekday() not in cfg["days"]:
            continue
        for t in cfg["times"]:
            hm = parse_time(t)
            if not hm:
                continue
            at = day.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
            key = at.strftime("%Y-%m-%d %H:%M")
            if at <= now <= at + late and key not in store.runs:
                return key
    return ""


def next_run(cfg, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now()
    best = None
    for d in range(8):
        day = now + timedelta(days=d)
        if day.weekday() not in cfg["days"]:
            continue
        for t in cfg["times"]:
            hm = parse_time(t)
            if hm:
                at = day.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
                if at > now and (best is None or at < best):
                    best = at
        if best:
            return best
    return best


# --- picking posts ------------------------------------------------------------------
def estimate(c: rs.Candidate, look: dict, comments: int = 0) -> float:
    from .pipeline import LEAD_IN, PART_GAP, PART_LEAD, TAIL
    from .voice import estimate_length
    text = c.title + "\n" + c.body
    secs, _ = estimate_length(text, look.get("line_pause", 0.35), look.get("voice_speed", 1.0))
    pages = max(1, c.words // 150)
    return LEAD_IN + secs + TAIL + (pages - 1) * (PART_LEAD + PART_GAP) + comments * 8


def candidates(cfg, look: dict, store: Store, history=None, status=lambda m: None):
    """(chosen, every post looked at with why it was skipped, errors)."""
    f = rs.Filters.from_dict(cfg["filters"])
    used = set(store.used)
    chosen, looked, errors = rs.pick(cfg["subs"], cfg["sort"], cfg["period"], f, used,
                                     n=200, status=status)
    limit = length_limit(cfg)
    out, final = [], []
    for c, why in looked:
        if not why:
            secs = estimate(c, look, cfg["comments"])
            if secs > limit:
                why = f"too long for the apps (~{int(secs)}s)"
            elif history is not None and history.find_similar(c.title + "\n" + c.body, 0.9):
                why = "already made (in History)"
        final.append((c, why))
        if not why and len(out) < max(1, int(cfg["per_run"])):
            out.append(c)
    final.sort(key=lambda cw: (bool(cw[1]), -rs.rank_value(cw[0], f.rank)))
    return out, final, errors


def max_card_ratio(look: dict) -> float:
    """Tallest a card can be (height / width) and still fit nicely on screen."""
    fmt = look.get("fmt", "9:16")
    fmt = fmt if fmt in FORMATS else "9:16"
    m = margins(fmt)
    box = look.get("post_box") or default_box(fmt, 1.0)
    room = (1 - m["top"] - m["bottom"] - 0.02) if fmt == "9:16" else 0.86
    room = min(room, MAX_POST_HEIGHT)
    w = min(max(box.get("w", 0.9), 0.3), 1.0)
    return max(0.6, room / (w * aspect(fmt)))


def build_posts(c: rs.Candidate, n_comments: int, max_ratio: float, status=lambda m: None):
    """The Reddit post (split into pages if long) plus its top comments, as Posts."""
    from .cards import paginate
    from .links import fetch, reddit_post
    posts = []
    main = None
    try:
        got = fetch(c.url, status)
        main = got.posts[0]
        comments = [p for p in got.posts[1:] if getattr(p, "depth", 0) == 0
                    and p.author not in ("AutoModerator", "[deleted]")
                    and len(" ".join(x.text for x in p.paras).split()) >= 5]
    except Exception:
        comments = []
    if main is None:            # couldn't get the full post: draw from the listing
        main = reddit_post({"author": c.author, "created_utc": c.created, "title": c.title,
                            "selftext": c.body, "subreddit": c.sub, "score": c.score,
                            "num_comments": c.comments, "id": c.id})
    main.image = None if c.body.strip() else main.image
    posts += paginate(main, max_ratio, CARD_WIDTH)

    def score(p):
        try:
            return float(str(p.score).replace("k", "")) * (1000 if "k" in str(p.score) else 1)
        except ValueError:
            return 0

    for cm in sorted(comments, key=score, reverse=True)[:n_comments]:
        posts += paginate(cm, max_ratio, CARD_WIDTH)
    return posts


def caption(cfg, c: rs.Candidate) -> str:
    tag = re.sub(r"[^A-Za-z0-9_]", "", c.sub.lower())
    vals = {"title": c.title.strip(), "sub": tag, "subreddit": c.sub, "author": c.author,
            "upvotes": f"{c.score:,}", "comments": f"{c.comments:,}"}
    text = cfg["caption"] or "{title}"
    for k, v in vals.items():
        text = text.replace("{" + k + "}", v)
    return text.strip()


# --- one round --------------------------------------------------------------------
def make_one(c: rs.Candidate, cfg, look: dict, base: dict, cleanup, library, history,
             status=lambda m, f: None):
    """Draw the cards and make the video. Returns (Made, number of cards)."""
    from .cards import draw
    from .pipeline import Job, Part, make_video
    status("Getting the post…", 0.0)
    posts = build_posts(c, int(cfg["comments"]), max_card_ratio(look),
                        lambda m: status(m, 0.0))
    d = data_dir() / "cards"
    d.mkdir(parents=True, exist_ok=True)
    drawn = []
    for i, p in enumerate(posts):
        status(f"Drawing card {i + 1} of {len(posts)}…", 0.01)
        png, pt = draw(p, d / f"auto_{c.id}_{i}_{cfg['reddit_theme']}.png", cfg["reddit_theme"])
        if pt.text.strip():
            drawn.append((str(png), pt))
    if not drawn:
        raise ValueError("The post had nothing to read.")
    first, rest = drawn[0], drawn[1:]
    job = Job(**base, **look, post_image=first[0], text=first[1].text, post_text=first[1],
              hook=c.title if cfg["hook_title"] else "", hook_spoken=False,
              parts=[Part(img, pt.text, pt) for img, pt in rest])
    return make_video(job, cleanup, library, status, history=history), len(drawn)


def new_item(c: rs.Candidate, cfg, made) -> dict:
    targets = {}
    for k in on_platforms(cfg):
        targets[k] = {"state": "queued" if cfg["platforms"][k]["auto"] else "waiting",
                      "url": "", "note": "", "error": ""}
    return {"id": uuid.uuid4().hex[:10], "rid": c.id, "sub": c.sub, "title": c.title,
            "url": c.url, "score": c.score, "comments": c.comments,
            "video": str(made.path), "length": round(made.duration, 1),
            "created": time.time(), "caption": caption(cfg, c), "targets": targets}


def post_item(item: dict, cfg, store: Store, status=lambda m: None, only: str = "") -> list[str]:
    """Post every 'queued' target of an item (or just `only`). Returns messages."""
    from .posting import NAMES, PostError, module
    msgs = []
    video = Path(item["video"])
    for key, t in item["targets"].items():
        if t["state"] != "queued" or (only and key != only):
            continue
        name = NAMES[key]
        if not video.is_file():
            t.update(state="failed", error="The video file is gone (moved or deleted).")
            store.save()
            msgs.append(f"{name}: the video file is gone")
            continue
        mod = module(key)
        if not mod.connected():
            t.update(state="failed", error=f"{name} isn't connected. Connect it in Automate → "
                                           "Post to, then click Try again.")
            store.save()
            msgs.append(f"{name}: not connected")
            continue
        t.update(state="posting", error="")
        store.save()
        opts = cfg["platforms"].get(key, {})
        try:
            res = mod.post(video, item["caption"], title=item["title"],
                           status=lambda m, n=name: status(m), mode=opts.get("mode", "inbox"),
                           privacy=opts.get("privacy", "public"))
            t.update(state=res.state, url=res.url, note=res.note, error="", when=time.time())
            msgs.append(f"{name}: " + {"posted": "posted", "inbox": "sent to your inbox",
                                       "private": "posted (private)",
                                       "processing": "uploaded, still processing"}
                        .get(res.state, res.state))
            store.note(f"{name}: {item['title'][:60]} → {res.state}")
        except PostError as e:
            t.update(state="failed", error=str(e))
            msgs.append(f"{name}: {e}")
            store.note(f"{name} failed: {e}")
        except Exception as e:      # never let one app stop the others
            t.update(state="failed", error=str(e) or e.__class__.__name__)
            msgs.append(f"{name}: {e}")
            store.note(f"{name} failed: {e}")
        store.save()
    return msgs


def approve(item: dict, key: str = ""):
    for k, t in item["targets"].items():
        if (not key or k == key) and t["state"] in ("waiting", "failed"):
            t["state"] = "queued"


def run(cfg, look: dict, base: dict, store: Store, cleanup, library, history,
        status=lambda m, f: None, stop=lambda: False, slot: str = "") -> dict:
    """One round. Returns {"made": [...items], "errors": [...], "posted": [...]}."""
    if slot:
        store.runs[slot] = time.time()
        store.save()
    status("Looking for posts…", 0.0)
    chosen, _, errors = candidates(cfg, look, store, history, lambda m: status(m, 0.0))
    made, posted = [], []
    if not chosen:
        why = "; ".join(errors) if errors else "no post matched your filters"
        store.note(f"Ran, but {why}.")
        return {"made": [], "errors": errors or ["No new posts matched your filters."],
                "posted": []}
    n = len(chosen)
    for k, c in enumerate(chosen):
        if stop():
            break
        tag = f"Video {k + 1} of {n}: " if n > 1 else ""
        try:
            m, cards = make_one(c, cfg, look, base, cleanup, library, history,
                                lambda msg, f, k=k, tag=tag: status(tag + msg, (k + f * 0.85) / n))
        except Exception as e:
            from .library import LibraryExhausted
            errors.append(f"r/{c.sub} “{c.title[:50]}”: {e}")
            store.note(f"Couldn't make “{c.title[:50]}”: {e}")
            if isinstance(e, LibraryExhausted):
                break
            store.used.append(c.id)      # don't keep retrying a broken post
            store.save()
            continue
        item = new_item(c, cfg, m)
        if history is not None:
            item["thumb"] = next((e.get("thumb", "") for e in history.entries
                                  if e.get("video") == str(m.path)), "")
        store.add(item)
        store.note(f"Made “{c.title[:60]}” ({int(m.duration)}s, {cards} card"
                   f"{'s' * (cards != 1)}) from r/{c.sub}")
        made.append(item)
        posted += post_item(item, cfg, store,
                            lambda msg, k=k, tag=tag: status(tag + msg, (k + 0.9) / n))
    status("Done", 1.0)
    return {"made": made, "errors": errors, "posted": posted}
