"""TikTok, through TikTok's Content Posting API (your own free developer app).

Two ways to post:
  "inbox"  - the video lands in your TikTok inbox; open TikTok, tap it, Post.
             Works right away with a new developer app.
  "direct" - posts on its own. Until TikTok audits your app, it can only post
             to a PRIVATE account and the video is "only me".
"""

import time
from pathlib import Path
from urllib.parse import urlencode

from .. import oauth
from . import Posted, PostError, call

API = "https://open.tiktokapis.com"
PORT = 3455
REDIRECT = f"http://127.0.0.1:{PORT}/callback/"
SCOPES = "user.info.basic,video.upload,video.publish"
APP_KEY, TOKEN_KEY = "tiktok_app", "tiktok_token"
MB = 1024 * 1024


def app() -> dict:
    return oauth.load(APP_KEY)


def set_app(client_key: str, client_secret: str):
    oauth.save(APP_KEY, {"client_key": client_key.strip(), "client_secret": client_secret.strip()})


def connected() -> bool:
    return bool(oauth.load(TOKEN_KEY).get("refresh_token"))


def account() -> str:
    t = oauth.load(TOKEN_KEY)
    return t.get("name", "") if t else ""


def disconnect():
    oauth.save(TOKEN_KEY, None)


def _check(r, what="TikTok"):
    try:
        j = r.json()
    except ValueError:
        raise PostError(f"{what} error {r.status_code}.")
    err = j.get("error") or {}
    code = err.get("code", "ok") if isinstance(err, dict) else err
    if r.status_code >= 400 or code not in ("ok", "", None):
        msg = (err.get("message") if isinstance(err, dict) else "") or j.get("error_description") or ""
        raise PostError(_friendly(code, msg, r.status_code))
    return j


def _friendly(code, msg, status) -> str:
    hints = {
        "unaudited_client_can_only_post_to_private_accounts":
            "TikTok only lets apps it hasn't reviewed post to a private account. Make your "
            "account private in TikTok, or use 'Send to my TikTok inbox' instead.",
        "spam_risk_too_many_posts": "TikTok says you've posted too much today. Try again tomorrow.",
        "spam_risk_user_banned_from_posting": "TikTok has blocked this account from posting for now.",
        "access_token_invalid": "Your TikTok sign-in ran out. Connect TikTok again.",
        "scope_not_authorized": "Your TikTok app doesn't have permission to post. Add the "
                                "Content Posting API to your app, then connect again.",
        "rate_limit_exceeded": "TikTok says slow down. Anon Brain will try again later.",
        "privacy_level_option_mismatch": "TikTok didn't accept that privacy setting.",
    }
    return hints.get(code) or f"TikTok said: {msg or code} ({status})"


# --- sign in -----------------------------------------------------------------------
def connect(opener=None):
    a = app()
    if not a.get("client_key"):
        raise PostError("Add your TikTok app's Client key and secret first.")
    v, state = oauth.verifier(), oauth.verifier()[:24]
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": a["client_key"], "response_type": "code", "scope": SCOPES,
        "redirect_uri": REDIRECT, "state": state,
        "code_challenge": oauth.challenge_hex(v), "code_challenge_method": "S256"})
    kw = {"opener": opener} if opener else {}
    got = oauth.catch_code(url, PORT, "/callback/", state, **kw)
    r = call("POST", f"{API}/v2/oauth/token/", "TikTok", data={
        "client_key": a["client_key"], "client_secret": a["client_secret"],
        "code": got["code"], "grant_type": "authorization_code",
        "redirect_uri": REDIRECT, "code_verifier": v})
    _store(_check(r))
    try:
        info = _check(call("GET", f"{API}/v2/user/info/?fields=open_id,display_name",
                           "TikTok", headers=_auth()))
        name = info.get("data", {}).get("user", {}).get("display_name", "")
        t = oauth.load(TOKEN_KEY)
        t["name"] = name
        oauth.save(TOKEN_KEY, t)
    except PostError:
        pass
    try:        # @username needs the optional user.info.profile scope; links work without it
        info = _check(call("GET", f"{API}/v2/user/info/?fields=username", "TikTok",
                           headers=_auth()))
        t = oauth.load(TOKEN_KEY)
        t["username"] = info.get("data", {}).get("user", {}).get("username", "")
        oauth.save(TOKEN_KEY, t)
    except (PostError, KeyError):
        pass
    return account()


def _store(j: dict):
    old = oauth.load(TOKEN_KEY)
    if "access_token" not in j:
        raise PostError("TikTok didn't send a sign-in token.")
    oauth.save(TOKEN_KEY, {**old, "access_token": j["access_token"],
                           "refresh_token": j.get("refresh_token", old.get("refresh_token")),
                           "expires": time.time() + int(j.get("expires_in", 86400)) - 120,
                           "open_id": j.get("open_id", old.get("open_id", ""))})


def _token() -> str:
    t = oauth.load(TOKEN_KEY)
    if not t.get("refresh_token"):
        raise PostError("Connect your TikTok account first.")
    if t.get("expires", 0) > time.time():
        return t["access_token"]
    a = app()
    r = call("POST", f"{API}/v2/oauth/token/", "TikTok", data={
        "client_key": a.get("client_key", ""), "client_secret": a.get("client_secret", ""),
        "grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
    try:
        _store(_check(r))
    except PostError:
        raise PostError("Your TikTok sign-in ran out. Connect TikTok again.")
    return oauth.load(TOKEN_KEY)["access_token"]


def _auth() -> dict:
    return {"Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json; charset=UTF-8"}


# --- posting -----------------------------------------------------------------------
def chunks(size: int) -> tuple[int, int]:
    """(chunk_size, count) the way TikTok wants: one piece up to 64 MB, else 10 MB
    pieces with the remainder added to the last one."""
    if size <= 64 * MB:
        return size, 1
    chunk = 10 * MB
    return chunk, size // chunk


def _upload(url: str, video: Path, status):
    size = video.stat().st_size
    chunk, count = chunks(size)
    with open(video, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            f.seek(start)
            data = f.read(end - start + 1)
            status(f"Uploading to TikTok… {int(100 * (i + 1) / count)}%")
            r = call("PUT", url, "TikTok", data=data, timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            if r.status_code not in (200, 201, 206):
                raise PostError(f"TikTok upload failed ({r.status_code}).")


def _wait(publish_id: str, status, timeout=300) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = _check(call("POST", f"{API}/v2/post/publish/status/fetch/", "TikTok",
                        headers=_auth(), json={"publish_id": publish_id}))
        d = j.get("data", {})
        s = d.get("status", "")
        if s == "FAILED":
            raise PostError(f"TikTok couldn't post it: {d.get('fail_reason') or 'unknown reason'}.")
        if s in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            return d
        status("TikTok is processing the video…")
        time.sleep(4)
    return {"status": "PROCESSING"}


def post(video: Path, caption: str, title: str = "", status=lambda m: None,
         mode: str = "inbox", **_) -> Posted:
    video = Path(video)
    size = video.stat().st_size
    chunk, count = chunks(size)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk,
              "total_chunk_count": count}
    if mode == "direct":
        status("Asking TikTok how you're allowed to post…")
        info = _check(call("POST", f"{API}/v2/post/publish/creator_info/query/", "TikTok",
                           headers=_auth(), json={})).get("data", {})
        options = info.get("privacy_level_options") or ["SELF_ONLY"]
        privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in options else options[0]
        body = {"post_info": {"title": caption[:2200], "privacy_level": privacy,
                              "disable_comment": False, "disable_duet": False,
                              "disable_stitch": False, "video_cover_timestamp_ms": 1500},
                "source_info": source}
        j = _check(call("POST", f"{API}/v2/post/publish/video/init/", "TikTok",
                        headers=_auth(), json=body))
    else:
        privacy = ""
        j = _check(call("POST", f"{API}/v2/post/publish/inbox/video/init/", "TikTok",
                        headers=_auth(), json={"source_info": source}))
    d = j.get("data", {})
    _upload(d["upload_url"], video, status)
    res = _wait(d["publish_id"], status)
    if mode != "direct":
        return Posted("inbox", note="In your TikTok inbox: open TikTok, tap the notification, "
                                    "and post it.", id=d["publish_id"])
    if res.get("status") == "PROCESSING":
        return Posted("processing", note="TikTok is still processing it.", id=d["publish_id"])
    ids = res.get("publicaly_available_post_id") or res.get("publicly_available_post_id") or []
    uname = oauth.load(TOKEN_KEY).get("username", "")
    url = f"https://www.tiktok.com/@{uname}/video/{ids[0]}" if ids and uname else ""
    if privacy != "PUBLIC_TO_EVERYONE":
        return Posted("private", url, "Posted as 'only me': TikTok hasn't approved your app "
                      "for public posts yet.", d["publish_id"])
    return Posted("posted", url, id=d["publish_id"])
