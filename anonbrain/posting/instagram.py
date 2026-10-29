"""Instagram Reels, through Meta's Graph API (your own free Meta developer app).

Needs an Instagram Professional (Business or Creator) account linked to a
Facebook Page. You paste a token from Meta's Graph API Explorer once; Anon
Brain swaps it for a Page token that doesn't expire.
"""

import time
from pathlib import Path

from .. import oauth
from . import Posted, PostError, call

VER = "v24.0"
GRAPH = f"https://graph.facebook.com/{VER}"
APP_KEY, TOKEN_KEY = "instagram_app", "instagram_token"
PERMISSIONS = ("instagram_basic, instagram_content_publish, pages_show_list, "
               "pages_read_engagement, business_management")


def app() -> dict:
    return oauth.load(APP_KEY)


def set_app(app_id: str, app_secret: str):
    oauth.save(APP_KEY, {"app_id": app_id.strip(), "app_secret": app_secret.strip()})


def connected() -> bool:
    t = oauth.load(TOKEN_KEY)
    return bool(t.get("token") and t.get("ig_id"))


def account() -> str:
    return oauth.load(TOKEN_KEY).get("name", "")


def disconnect():
    oauth.save(TOKEN_KEY, None)


def _json(r, what="Instagram") -> dict:
    try:
        j = r.json()
    except ValueError:
        raise PostError(f"{what} error {r.status_code}.")
    if "error" in j:
        e = j["error"]
        code = e.get("code")
        if code == 190:
            raise PostError("Your Instagram sign-in isn't valid any more. Connect Instagram again.")
        if code in (4, 9, 17, 32, 613) or e.get("error_subcode") == 2207042:
            raise PostError("Instagram says you've posted too much for now (the limit is 50 "
                            "posts a day). Try again later.")
        raise PostError(f"Instagram said: {e.get('error_user_msg') or e.get('message')}")
    return j


def connect(user_token: str) -> str:
    """Swap a Graph API Explorer token for a never-expiring Page token."""
    a = app()
    token = user_token.strip()
    if not token:
        raise PostError("Paste the token from Graph API Explorer first.")
    if a.get("app_id") and a.get("app_secret"):
        j = _json(call("GET", f"{GRAPH}/oauth/access_token", "Facebook", params={
            "grant_type": "fb_exchange_token", "client_id": a["app_id"],
            "client_secret": a["app_secret"], "fb_exchange_token": token}), "Facebook")
        token = j.get("access_token", token)
    pages = _json(call("GET", f"{GRAPH}/me/accounts", "Facebook", params={
        "fields": "name,access_token,instagram_business_account{id,username}",
        "access_token": token}), "Facebook").get("data", [])
    for p in pages:
        ig = p.get("instagram_business_account")
        if ig:
            oauth.save(TOKEN_KEY, {"token": p.get("access_token") or token, "ig_id": ig["id"],
                                   "name": ig.get("username", ""), "page": p.get("name", ""),
                                   "saved": time.time()})
            return account()
    raise PostError("None of your Facebook Pages has an Instagram account linked. Link your "
                    "Instagram Professional account to a Facebook Page (Instagram app → "
                    "Settings → Account Center), then try again.")


def post(video: Path, caption: str, title: str = "", status=lambda m: None,
         share_to_feed: bool = True, **_) -> Posted:
    t = oauth.load(TOKEN_KEY)
    if not t.get("token"):
        raise PostError("Connect your Instagram account first.")
    video = Path(video)
    size = video.stat().st_size
    auth = {"Authorization": f"OAuth {t['token']}"}
    status("Getting Instagram ready…")
    j = _json(call("POST", f"{GRAPH}/{t['ig_id']}/media", "Instagram", headers=auth, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
        "share_to_feed": "true" if share_to_feed else "false"}))
    cid = j["id"]
    upload_uri = j.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{VER}/{cid}"
    status("Uploading to Instagram…")
    with open(video, "rb") as f:
        r = call("POST", upload_uri, "Instagram", data=f, timeout=1800,
                 headers={**auth, "offset": "0", "file_size": str(size)})
    if not r.ok:
        _json(r)
        raise PostError(f"Instagram upload failed ({r.status_code}).")
    t0 = time.time()
    while True:
        s = _json(call("GET", f"{GRAPH}/{cid}", "Instagram", headers=auth,
                       params={"fields": "status_code,status"}))
        code = s.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise PostError(f"Instagram couldn't process the video: {s.get('status', code)}")
        if time.time() - t0 > 600:
            raise PostError("Instagram took too long to process the video.")
        status("Instagram is processing the video…")
        time.sleep(5)
    pub = _json(call("POST", f"{GRAPH}/{t['ig_id']}/media_publish", "Instagram",
                     headers=auth, data={"creation_id": cid}))
    mid = pub.get("id", "")
    url = ""
    try:
        url = _json(call("GET", f"{GRAPH}/{mid}", "Instagram", headers=auth,
                         params={"fields": "permalink"})).get("permalink", "")
    except PostError:
        pass
    return Posted("posted", url, id=mid)
