"""YouTube Shorts, through the YouTube Data API (your own free Google Cloud project).

A vertical or square video up to 3 minutes becomes a Short on its own.
Google keeps uploads from projects it hasn't reviewed ("unverified") private;
you can make them public in YouTube Studio, or ask Google for an audit.
"""

import json
import time
from pathlib import Path
from urllib.parse import urlencode

from .. import oauth
from . import Posted, PostError, call

APP_KEY, TOKEN_KEY = "youtube_app", "youtube_token"
SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def app() -> dict:
    return oauth.load(APP_KEY)


def set_app(client_id: str, client_secret: str):
    oauth.save(APP_KEY, {"client_id": client_id.strip(), "client_secret": client_secret.strip()})


def read_client_file(path: str) -> tuple[str, str]:
    """The client_secret_....json Google lets you download."""
    try:
        j = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PostError("That file isn't a Google client file (client_secret_….json).")
    d = j.get("installed") or j.get("web") or {}
    if not d.get("client_id"):
        raise PostError("That file has no client ID in it. Download the JSON for a "
                        "'Desktop app' OAuth client.")
    return d["client_id"], d.get("client_secret", "")


def connected() -> bool:
    return bool(oauth.load(TOKEN_KEY).get("refresh_token"))


def account() -> str:
    return oauth.load(TOKEN_KEY).get("name", "")


def disconnect():
    oauth.save(TOKEN_KEY, None)


def _err(r, what="YouTube") -> str:
    try:
        j = r.json()
        e = j.get("error")
        if isinstance(e, dict):
            reason = (e.get("errors") or [{}])[0].get("reason", "")
            if reason == "quotaExceeded":
                return "YouTube's daily upload allowance for your project is used up " \
                       "(about 6 uploads a day). It resets at midnight Pacific time."
            if reason == "uploadLimitExceeded":
                return "YouTube says this channel has hit its upload limit for today."
            return f"{what} said: {e.get('message', reason)}"
        return f"{what} said: {j.get('error_description') or e}"
    except ValueError:
        return f"{what} error {r.status_code}."


def connect(opener=None):
    a = app()
    if not a.get("client_id"):
        raise PostError("Add your Google client file first.")
    port = oauth.free_port()
    redirect = f"http://127.0.0.1:{port}/"
    v, state = oauth.verifier(), oauth.verifier()[:24]
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": a["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": oauth.challenge_b64(v), "code_challenge_method": "S256"})
    kw = {"opener": opener} if opener else {}
    got = oauth.catch_code(url, port, "/", state, **kw)
    r = call("POST", TOKEN_URL, "Google", data={
        "client_id": a["client_id"], "client_secret": a.get("client_secret", ""),
        "code": got["code"], "grant_type": "authorization_code",
        "redirect_uri": redirect, "code_verifier": v})
    if not r.ok:
        raise PostError(_err(r, "Google"))
    _store(r.json())
    try:
        ch = call("GET", "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                  "YouTube", headers=_auth()).json()
        name = ch.get("items", [{}])[0].get("snippet", {}).get("title", "")
        t = oauth.load(TOKEN_KEY)
        t["name"] = name
        oauth.save(TOKEN_KEY, t)
    except (PostError, ValueError, IndexError):
        pass
    return account()


def _store(j):
    old = oauth.load(TOKEN_KEY)
    oauth.save(TOKEN_KEY, {**old, "access_token": j["access_token"],
                           "refresh_token": j.get("refresh_token", old.get("refresh_token")),
                           "expires": time.time() + int(j.get("expires_in", 3600)) - 120})


def _token() -> str:
    t = oauth.load(TOKEN_KEY)
    if not t.get("refresh_token"):
        raise PostError("Connect your YouTube channel first.")
    if t.get("expires", 0) > time.time():
        return t["access_token"]
    a = app()
    r = call("POST", TOKEN_URL, "Google", data={
        "client_id": a.get("client_id", ""), "client_secret": a.get("client_secret", ""),
        "grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
    if not r.ok:
        raise PostError("Your YouTube sign-in ran out. Connect YouTube again.")
    _store(r.json())
    return oauth.load(TOKEN_KEY)["access_token"]


def _auth() -> dict:
    return {"Authorization": f"Bearer {_token()}"}


def post(video: Path, caption: str, title: str = "", status=lambda m: None,
         privacy: str = "public", **_) -> Posted:
    video = Path(video)
    size = video.stat().st_size
    title = (title or (caption.strip().splitlines()[0] if caption.strip() else "Story")).strip()
    if "#shorts" not in title.lower() and len(title) <= 91:
        title += " #Shorts"
    meta = {"snippet": {"title": title[:100], "description": caption[:5000],
                        "categoryId": "24"},          # Entertainment
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    status("Starting the YouTube upload…")
    r = call("POST", "https://www.googleapis.com/upload/youtube/v3/videos"
             "?uploadType=resumable&part=snippet,status", "YouTube",
             headers={**_auth(), "Content-Type": "application/json; charset=UTF-8",
                      "X-Upload-Content-Type": "video/mp4",
                      "X-Upload-Content-Length": str(size)}, data=json.dumps(meta))
    if not r.ok or "Location" not in r.headers:
        raise PostError(_err(r))
    status("Uploading to YouTube…")
    with open(video, "rb") as f:
        up = call("PUT", r.headers["Location"], "YouTube", data=f, timeout=1800,
                  headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
    if not up.ok:
        raise PostError(_err(up))
    j = up.json()
    vid = j.get("id", "")
    got = j.get("status", {}).get("privacyStatus", privacy)
    url = f"https://youtube.com/shorts/{vid}" if vid else ""
    if got == "private" and privacy != "private":
        return Posted("private", url, "Uploaded as private: Google keeps uploads private until "
                      "your project is verified. Make it public in YouTube Studio.", vid)
    return Posted("posted" if got == "public" else got, url, id=vid)
