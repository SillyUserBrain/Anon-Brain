"""Signing in to TikTok / YouTube from a desktop app, and keeping the keys safe.

The browser opens the site's sign-in page; when you approve, the site sends
the browser back to a tiny web server on your own PC (127.0.0.1), which hands
the one-time code to the app. Tokens and app keys are kept in Windows
Credential Manager (keyring), never in a plain file.
"""

import base64
import hashlib
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import keyring

SERVICE = "Anon Brain"


class AuthError(Exception):
    pass


# --- secrets in Credential Manager ---------------------------------------------------
def load(name: str) -> dict:
    try:
        raw = keyring.get_password(SERVICE, name)
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def save(name: str, data: dict | None):
    try:
        if data:
            keyring.set_password(SERVICE, name, json.dumps(data))
        else:
            keyring.delete_password(SERVICE, name)
    except Exception as e:
        if data:                     # a failed delete just means nothing was saved
            from .appinfo import log_exception
            log_exception(f"Couldn't save {name} to Credential Manager", e)
            raise AuthError("Windows Credential Manager wouldn't save your sign-in. "
                            "See Settings → About → Copy error details.")


# --- PKCE ---------------------------------------------------------------------------
def verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def challenge_b64(v: str) -> str:
    """Standard PKCE (Google)."""
    return base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def challenge_hex(v: str) -> str:
    """TikTok's desktop flavour: hex instead of base64."""
    return hashlib.sha256(v.encode()).hexdigest()


# --- the local catcher --------------------------------------------------------------
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Anon Brain</title>
<style>body{{background:#0d1014;color:#e8edf2;font-family:Segoe UI,Arial,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
div{{text-align:center}}h1{{color:{color};font-size:28px}}p{{opacity:.75}}</style></head>
<body><div><h1>{title}</h1><p>{text}</p></div></body></html>"""


def catch_code(auth_url: str, port: int, path: str = "/", state: str = "",
               timeout: float = 300, opener=webbrowser.open) -> dict:
    """Open auth_url in the browser and wait for the redirect to
    http://127.0.0.1:{port}{path}. Returns the query parameters (code, ...)."""
    got: dict = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            if u.path.rstrip("/") != path.rstrip("/"):
                self.send_response(404)
                self.end_headers()
                return
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            ok = "code" in q and (not state or q.get("state") == state)
            got.update(q)
            body = PAGE.format(
                color="#8fc43f" if ok else "#ff6b6b",
                title="Connected!" if ok else "That didn't work",
                text=("You can close this tab and go back to Anon Brain." if ok else
                      q.get("error_description") or q.get("error") or
                      "Go back to Anon Brain and try again."))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())
            done.set()

        def log_message(self, *a):
            pass

    try:
        server = HTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        raise AuthError(f"Port {port} on your PC is busy. Close other apps that might use it "
                        "and try again.")
    server.timeout = 0.5
    t0 = time.time()
    opener(auth_url)
    try:
        while not done.is_set() and time.time() - t0 < timeout:
            server.handle_request()
    finally:
        server.server_close()
    if not done.is_set():
        raise AuthError("Timed out waiting for you to sign in.")
    if state and got.get("state") != state:
        raise AuthError("The sign-in reply didn't match. Try again.")
    if "code" not in got:
        raise AuthError(got.get("error_description") or got.get("error") or
                        "Sign-in was cancelled.")
    return got


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
