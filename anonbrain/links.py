"""Paste a link instead of a screenshot: Reddit posts / comments and 4chan threads.

fetch(url) -> Fetched: the post(s) behind the link, ready for cards.draw().
Uses the sites' public JSON (no account needed).
"""

import html
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

from .cards import Para, Post
from .engine import EngineError

UA = {"User-Agent": "AnonBrain/1.0 (desktop app that turns posts into videos)"}


class LinkError(EngineError):
    pass


@dataclass
class Fetched:
    site: str
    posts: list[Post] = field(default_factory=list)   # the main post first, then replies
    picked: list[str] = field(default_factory=list)   # ids the link pointed at
    title: str = ""


def looks_like_link(text: str) -> bool:
    return bool(parse(text.strip()))


def parse(url: str):
    """('reddit', url) / ('4chan', board, thread, post) / None"""
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    try:
        u = urlparse(url)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if host.endswith("reddit.com") or host == "redd.it":
        return ("reddit", url)
    if host.endswith("4chan.org") or host.endswith("4channel.org"):
        m = re.match(r"^/(\w+)/thread/(\d+)", u.path)
        if m:
            post = re.match(r"^(?:p|q)?(\d+)$", u.fragment or "")
            return ("4chan", m.group(1), m.group(2), post.group(1) if post else m.group(2))
    return None


def fetch(url: str, status=lambda m: None) -> Fetched:
    p = parse(url)
    if not p:
        raise LinkError("That isn't a Reddit or 4chan post link.")
    if p[0] == "reddit":
        return _reddit(p[1], status)
    return _fourchan(p[1], p[2], p[3], status)


def _get(url, what, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=20, **kw)
    except requests.RequestException:
        raise LinkError(f"Couldn't reach {what}. Check your internet connection.")
    if r.status_code == 404:
        raise LinkError(f"{what} says that post doesn't exist (deleted, or the thread "
                        "fell off the board).")
    if r.status_code in (403, 429):
        raise LinkError(f"{what} isn't letting us in right now. Wait a minute and try "
                        "again, or use a screenshot.")
    if not r.ok:
        raise LinkError(f"{what} error {r.status_code}.")
    return r


def _ago(ts: float) -> str:
    s = max(0, time.time() - ts)
    for unit, n in (("y", 31536000), ("mo", 2592000), ("d", 86400), ("h", 3600), ("m", 60)):
        if s >= n:
            return f"{int(s // n)}{unit} ago"
    return "just now"


def _count(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


# --- 4chan -------------------------------------------------------------------------
def com_to_paras(com: str) -> list[Para]:
    """4chan post HTML -> lines (greentext, reply links, plain)."""
    com = (com or "").replace("<wbr>", "")
    paras = []
    for raw in re.split(r"<br\s*/?>", com):
        is_quote = 'class="quotelink"' in raw or "class='quotelink'" in raw
        text = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        if not text and not paras:
            continue
        if is_quote and re.fullmatch(r">>>?[/\w]*\d+(\s*\(OP\))?", text):
            paras.append(Para(text, "quote", spoken=False))
        elif text.startswith(">") and not text.startswith(">>"):
            paras.append(Para(text, "green"))
        else:
            paras.append(Para(text, "text", spoken=bool(text)))
    while paras and not paras[-1].text:
        paras.pop()
    return paras


def _size(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, round(n / 1024))} KB"


def fourchan_post(p: dict, board: str, op_no: int, thumb: bytes | None = None) -> Post:
    return Post(site="4chan", author=html.unescape(p.get("name") or "Anonymous"),
                when=p.get("now", "").replace("\\", ""), number=str(p.get("no", "")),
                subject=html.unescape(p.get("sub", "")), paras=com_to_paras(p.get("com", "")),
                image=thumb,
                image_info=(f"{_size(p.get('fsize'))} {p.get('ext', '').lstrip('.').upper()}"
                            if p.get("tim") else ""),
                community=board, is_op=p.get("no") == op_no, id=str(p.get("no", "")))


def _fourchan(board, thread, post_no, status) -> Fetched:
    status("Getting the thread from 4chan…")
    data = _get(f"https://a.4cdn.org/{board}/thread/{thread}.json", "4chan").json()
    raw = data.get("posts", [])
    if not raw:
        raise LinkError("That thread is empty.")
    op = raw[0]["no"]
    posts = []
    for p in raw:
        posts.append(fourchan_post(p, board, op))
        posts[-1]._raw = p            # thumbnails are fetched only for the posts you pick
    picked = [str(op)] + ([str(post_no)] if str(post_no) != str(op) else [])
    return Fetched("4chan", posts, picked, title=f"/{board}/ thread {thread}")


def fourchan_thumbnail(post: Post, status=lambda m: None):
    raw = getattr(post, "_raw", None)
    if raw and raw.get("tim") and post.image is None:
        status("Getting the picture…")
        try:
            post.image = _get(f"https://i.4cdn.org/{post.community}/{raw['tim']}s.jpg",
                              "4chan").content
        except LinkError:
            post.image = None


# --- Reddit ------------------------------------------------------------------------
def md_to_paras(md: str) -> list[Para]:
    """Reddit markdown -> plain lines."""
    paras = []
    for line in (md or "").replace("\r", "").split("\n"):
        t = line.strip()
        t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)            # images
        t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)        # links -> their text
        t = re.sub(r"(\*\*|__|~~|\^)", "", t)
        t = re.sub(r"(?<!\w)[*_](\S[^*_]*\S|\S)[*_](?!\w)", r"\1", t)   # *italic*
        t = re.sub(r"^#{1,6}\s*", "", t)
        t = re.sub(r"^[-*+]\s+", "• ", t)
        t = html.unescape(t)
        if t in ("&#x200B;", "\u200b") or re.fullmatch(r"[-*_]{3,}", t):
            continue
        if t.startswith(">"):
            paras.append(Para(t.lstrip("> ").strip(), "green"))
        elif t:
            paras.append(Para(t))
    return paras


def _resolve_share(url: str) -> str:
    """Share links (reddit.com/r/x/s/AbC123, redd.it/abc) redirect to the real post.
    Read the redirect ourselves: Reddit often refuses the page it points to, but the
    redirect itself always carries the post's address."""
    for _ in range(5):
        u = urlparse(url)
        if "/comments/" in u.path:
            return url
        if (u.hostname or "") == "redd.it" and re.fullmatch(r"/\w+/?", u.path):
            return f"https://www.reddit.com/comments/{u.path.strip('/')}/"
        try:
            r = requests.get(url, headers=UA, timeout=20, allow_redirects=False)
        except requests.RequestException:
            raise LinkError("Couldn't reach Reddit. Check your internet connection.")
        loc = r.headers.get("Location") or r.headers.get("location")
        if not loc:
            m = re.search(r'https://www\.reddit\.com/r/\w+/comments/\w+[^"\'<> ]*', r.text or "")
            if m:
                return m.group(0)
            break
        url = loc if loc.startswith("http") else "https://www.reddit.com" + loc
    raise LinkError("Couldn't open that share link. Open it in your browser and copy the "
                    "address from there (it has /comments/ in it).")


def _reddit_json_url(url: str) -> str:
    u = urlparse(url)
    host = u.hostname or ""
    if host == "redd.it" or "/s/" in u.path or "/comments/" not in u.path:
        u = urlparse(_resolve_share(url))
    path = u.path.rstrip("/")
    m = re.search(r"/comments/\w+(?:/[^/]*)?(?:/\w+)?", path)
    if not m:
        raise LinkError("Paste the link to a Reddit post (it has /comments/ in it).")
    sub = re.match(r"^/r/\w+", path)
    return f"https://www.reddit.com{sub.group(0) if sub else ''}{m.group(0)}.json?raw_json=1&limit=200"


def _reddit_get(json_url: str):
    """The post's JSON. Tries Reddit's app API first if you added a Reddit key, then
    the normal and old sites (Reddit sometimes refuses one but not the other)."""
    tried = []
    try:
        from .reddit_source import _app_token
        tok = _app_token()
    except Exception:
        tok = ""
    path = urlparse(json_url).path.replace(".json", "")
    q = "?raw_json=1&limit=200"
    if tok:
        tried.append(("https://oauth.reddit.com" + path + q, {**UA, "Authorization": f"bearer {tok}"}))
    tried += [(json_url, UA), ("https://old.reddit.com" + path + ".json" + q, UA),
              ("https://api.reddit.com" + path + q, UA)]
    last = None
    for url, headers in tried:
        try:
            r = requests.get(url, headers=headers, timeout=20)
        except requests.RequestException:
            last = LinkError("Couldn't reach Reddit. Check your internet connection.")
            continue
        if r.status_code == 404:
            raise LinkError("Reddit says that post doesn't exist (deleted or removed).")
        if r.ok:
            try:
                return r.json()
            except ValueError:
                pass
        last = LinkError("Reddit isn't letting Anon Brain in right now. Wait a minute and "
                         "try again, add a free Reddit key (Settings → Accounts), or use a "
                         "screenshot.")
    raise last


def reddit_post(d: dict, picture: bytes | None = None) -> Post:
    return Post(site="reddit", author=d.get("author", "[deleted]"),
                when=_ago(d.get("created_utc", time.time())), subject=d.get("title", ""),
                paras=md_to_paras(d.get("selftext", "")), image=picture,
                community=d.get("subreddit", ""), score=_count(d.get("score")),
                comments=_count(d.get("num_comments")), is_op=True, id=d.get("id", ""))


def reddit_comment(d: dict, op_author: str) -> Post:
    author = d.get("author", "[deleted]")
    return Post(site="reddit", author=author + (" (OP)" if author == op_author else ""),
                when=_ago(d.get("created_utc", time.time())),
                paras=md_to_paras(d.get("body", "")), score=_count(d.get("score")),
                is_comment=True, id=d.get("id", ""))


def _walk(children, op_author, out, depth=0):
    for c in children:
        if c.get("kind") != "t1":
            continue
        d = c["data"]
        p = reddit_comment(d, op_author)
        p.depth = depth
        out.append(p)
        rep = d.get("replies")
        if isinstance(rep, dict) and depth < 3:
            _walk(rep["data"]["children"], op_author, out, depth + 1)


def _reddit(url, status) -> Fetched:
    status("Getting the post from Reddit…")
    json_url = _reddit_json_url(url)
    data = _reddit_get(json_url)
    pd = data[0]["data"]["children"][0]["data"]
    picture = None
    img = None
    if pd.get("post_hint") == "image" or re.search(r"\.(jpe?g|png|webp)$", pd.get("url", "")):
        img = pd.get("url")
    elif pd.get("preview", {}).get("images"):
        img = pd["preview"]["images"][0]["source"]["url"]
    if img:
        status("Getting the picture…")
        try:
            picture = _get(html.unescape(img), "Reddit").content
        except LinkError:
            picture = None
    post = reddit_post(pd, picture)
    post.depth = 0
    comments: list[Post] = []
    _walk(data[1]["data"]["children"] if len(data) > 1 else [], pd.get("author"), comments)
    picked = [post.id]
    m = re.search(r"/comments/\w+/[^/]*/(\w+)\.json", urlparse(json_url).path)
    if m and comments:                                 # a link to one comment
        picked.append(m.group(1))
    return Fetched("reddit", [post] + comments, picked, title=f"r/{post.community}")
