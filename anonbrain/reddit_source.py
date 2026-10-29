"""Find good posts in a subreddit: by upvotes, comments, age, length.

Uses Reddit's public JSON. If Reddit starts refusing (it limits apps without
a key), add a free Reddit "script" app's ID and secret in Automate -> Find
posts and Anon Brain signs in as that app instead.
"""

import re
import time
from dataclasses import dataclass

import requests

from . import oauth
from .links import UA, LinkError

APP_KEY = "reddit_app"
SORTS = [("top", "Top"), ("hot", "Hot"), ("new", "New"), ("rising", "Rising")]
PERIODS = [("day", "Today"), ("week", "This week"), ("month", "This month"),
           ("year", "This year"), ("all", "All time")]
_token: dict = {}


@dataclass
class Candidate:
    id: str
    sub: str
    title: str
    body: str
    score: int
    comments: int
    created: float
    permalink: str
    nsfw: bool = False
    flair: str = ""
    author: str = ""
    is_text: bool = True

    @property
    def url(self) -> str:
        return "https://www.reddit.com" + self.permalink

    @property
    def words(self) -> int:
        return len((self.title + " " + self.body).split())

    @property
    def age_hours(self) -> float:
        return max(0.0, (time.time() - self.created) / 3600)


def clean_sub(name: str) -> str:
    name = name.strip()
    m = re.search(r"reddit\.com/r/([A-Za-z0-9_]+)", name)
    if m:
        return m.group(1)
    return re.sub(r"^/?r/", "", name).strip("/ ")


def set_app(client_id: str, secret: str):
    oauth.save(APP_KEY, {"id": client_id.strip(), "secret": secret.strip()}
               if client_id.strip() else None)
    _token.clear()


def app() -> dict:
    return oauth.load(APP_KEY)


def _app_token() -> str:
    a = app()
    if not a.get("id"):
        return ""
    if _token.get("exp", 0) > time.time():
        return _token["t"]
    try:
        r = requests.post("https://www.reddit.com/api/v1/access_token",
                          auth=(a["id"], a.get("secret", "")),
                          data={"grant_type": "client_credentials"}, headers=UA, timeout=20)
        j = r.json()
    except (requests.RequestException, ValueError):
        return ""
    if "access_token" not in j:
        return ""
    _token.update(t=j["access_token"], exp=time.time() + int(j.get("expires_in", 3600)) - 60)
    return _token["t"]


def listing(sub: str, sort: str = "top", period: str = "day", limit: int = 100) -> list[Candidate]:
    sub = clean_sub(sub)
    if not sub:
        raise LinkError("Type a subreddit name, like AskReddit.")
    params = {"limit": min(limit, 100), "raw_json": 1}
    if sort == "top":
        params["t"] = period
    tok = _app_token()
    if tok:
        url, headers = f"https://oauth.reddit.com/r/{sub}/{sort}", {**UA, "Authorization": f"bearer {tok}"}
    else:
        url, headers = f"https://www.reddit.com/r/{sub}/{sort}.json", UA
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
    except requests.RequestException:
        raise LinkError("Couldn't reach Reddit. Check your internet connection.")
    if r.status_code in (403, 404):
        try:
            reason = r.json().get("reason", "")
        except ValueError:
            reason = ""
        if reason in ("private", "banned", "quarantined") or r.status_code == 404:
            raise LinkError(f"r/{sub} can't be read ({reason or 'not found'}).")
        raise LinkError("Reddit isn't letting Anon Brain in. Add a free Reddit app key "
                        "(Automate → Find posts → Reddit key) and try again.")
    if r.status_code == 429:
        raise LinkError("Reddit says slow down. Anon Brain will try again next time.")
    if not r.ok:
        raise LinkError(f"Reddit error {r.status_code}.")
    try:
        children = r.json()["data"]["children"]
    except (ValueError, KeyError, TypeError):
        raise LinkError(f"r/{sub} didn't send a list of posts.")
    return [_cand(c["data"]) for c in children if c.get("kind") == "t3"]


def _cand(d: dict) -> Candidate:
    body = d.get("selftext") or ""
    if body.strip() in ("[removed]", "[deleted]"):
        body = ""
    return Candidate(
        id=d.get("id", ""), sub=d.get("subreddit", ""), title=d.get("title", ""), body=body,
        score=int(d.get("score") or 0), comments=int(d.get("num_comments") or 0),
        created=float(d.get("created_utc") or time.time()), permalink=d.get("permalink", ""),
        nsfw=bool(d.get("over_18")), flair=d.get("link_flair_text") or "",
        author=d.get("author", ""),
        is_text=bool(d.get("is_self")) and not d.get("stickied") and not d.get("pinned")
        and d.get("distinguished") not in ("moderator", "admin"))


@dataclass
class Filters:
    min_score: int = 500
    min_comments: int = 20
    max_age_hours: float = 0          # 0 = any age
    min_words: int = 40
    max_words: int = 450
    nsfw: bool = False
    text_only: bool = True
    skip_words: str = ""              # comma separated: skip posts containing these
    need_words: str = ""              # comma separated: only posts containing one of these
    rank: str = "both"                # upvotes / comments / both

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def _words(s: str) -> list[str]:
    return [w.strip().lower() for w in s.split(",") if w.strip()]


def why_not(c: Candidate, f: Filters, used: set) -> str:
    """'' if the post passes, else a short reason (shown in the 'what would be picked' list)."""
    if c.id in used:
        return "already made"
    if f.text_only and not c.is_text:
        return "not a text post"
    if c.nsfw and not f.nsfw:
        return "NSFW"
    if c.score < f.min_score:
        return f"only {c.score} upvotes"
    if c.comments < f.min_comments:
        return f"only {c.comments} comments"
    if f.max_age_hours and c.age_hours > f.max_age_hours:
        return "too old"
    if c.words < f.min_words:
        return "too short"
    if f.max_words and c.words > f.max_words:
        return "too long"
    text = (c.title + " " + c.body).lower()
    if any(w in text for w in _words(f.skip_words)):
        return "has a skipped word"
    need = _words(f.need_words)
    if need and not any(w in text for w in need):
        return "missing a must-have word"
    return ""


def rank_value(c: Candidate, how: str) -> float:
    if how == "upvotes":
        return c.score
    if how == "comments":
        return c.comments
    return c.score + 4 * c.comments      # a comment is worth ~4 upvotes


def pick(subs: list[str], sort: str, period: str, f: Filters, used: set, n: int,
         status=lambda m: None) -> tuple[list[Candidate], list[tuple[Candidate, str]], list[str]]:
    """(chosen, every post looked at with its reason, errors per subreddit)."""
    seen, errors = [], []
    for s in subs:
        status(f"Looking through r/{clean_sub(s)}…")
        try:
            seen += listing(s, sort, period)
        except LinkError as e:
            errors.append(str(e))
    uniq = {}
    for c in seen:
        uniq.setdefault(c.id, c)
    looked = [(c, why_not(c, f, used)) for c in uniq.values()]
    ok = sorted((c for c, why in looked if not why), key=lambda c: -rank_value(c, f.rank))
    chosen, ids = [], set()
    for c in ok:
        if c.id not in ids:
            chosen.append(c)
            ids.add(c.id)
        if len(chosen) >= n:
            break
    looked.sort(key=lambda cw: (bool(cw[1]), -rank_value(cw[0], f.rank)))
    return chosen, looked, errors
