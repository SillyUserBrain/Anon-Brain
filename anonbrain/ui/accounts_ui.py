"""Connect TikTok / YouTube / Instagram / Reddit: step-by-step setup dialogs."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
)

from . import theme
from .common import button, label, run_task

STEPS = {
    "tiktok": {
        "title": "Connect TikTok",
        "site": "https://developers.tiktok.com/apps/",
        "steps": [
            "Sign in at <b>developers.tiktok.com</b> with your TikTok account and click "
            "<b>Manage apps → Connect an app</b> (it's free). Any app name works, like "
            "“My video poster”.",
            "Under <b>Products</b>, add <b>Login Kit</b> and <b>Content Posting API</b>. "
            "If you want videos posted without you, also switch on <b>Direct Post</b>.",
            "In Login Kit, choose platform <b>Desktop</b> and add this redirect URI:",
            "Under <b>Scopes</b>, make sure <b>user.info.basic</b>, <b>video.upload</b> and "
            "<b>video.publish</b> are added.",
            "Copy the <b>Client key</b> and <b>Client secret</b> into the boxes below, then "
            "click <b>Connect</b> and approve in the browser.",
        ],
        "copy": "http://127.0.0.1:3455/callback/",
        "note": "Until TikTok reviews your app, <b>auto-posting</b> only works if your account "
                "is set to <b>private</b>, and videos are posted as “only me”. Sending to your "
                "<b>TikTok inbox</b> works right away: you get a notification and tap Post.",
        "fields": [("client_key", "Client key"), ("client_secret", "Client secret")],
    },
    "youtube": {
        "title": "Connect YouTube",
        "site": "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
        "steps": [
            "Go to <b>console.cloud.google.com</b>, make a new project (any name), and "
            "<b>Enable</b> the <b>YouTube Data API v3</b>.",
            "Open <b>Google Auth Platform</b> (the OAuth consent screen), choose <b>External</b>, "
            "fill in the app name and your email, and add yourself as a <b>test user</b>. Then "
            "click <b>Publish app</b> so you don't have to sign in again every 7 days.",
            "Go to <b>Clients → Create client</b>, pick <b>Desktop app</b>, and "
            "<b>Download JSON</b>.",
            "Choose that file below and click <b>Connect</b>. Google will warn that the app "
            "isn't verified: click <b>Advanced → Go to (your app)</b>. It's your own app.",
        ],
        "note": "Google keeps uploads from unverified projects <b>private</b> until it reviews "
                "your project. You can make them public in YouTube Studio with one click. "
                "Each project can upload about 6 videos a day.",
        "fields": [],
        "file": True,
    },
    "instagram": {
        "title": "Connect Instagram",
        "site": "https://developers.facebook.com/apps/",
        "steps": [
            "Your Instagram must be a <b>Professional</b> account (Business or Creator) "
            "<b>linked to a Facebook Page</b> (Instagram → Settings → Account type, and "
            "Accounts Center to link the Page).",
            "At <b>developers.facebook.com</b>, click <b>Create app</b>, pick the "
            "<b>Business</b> type, and add the <b>Instagram</b> product with "
            "<b>API setup with Facebook login</b>.",
            "Open the <b>Graph API Explorer</b> (Tools menu), choose your app, add these "
            "permissions, and click <b>Generate Access Token</b>:",
            "Paste the token below. Also paste the <b>App ID</b> and <b>App secret</b> "
            "(App settings → Basic): Anon Brain uses them to swap the token for one that "
            "never runs out.",
        ],
        "copy": "instagram_basic, instagram_content_publish, pages_show_list, "
                "pages_read_engagement, business_management",
        "note": "While your Meta app is in development mode it can post to accounts that "
                "have a role on the app, which includes yours. The limit is 50 posts a day.",
        "fields": [("app_id", "App ID"), ("app_secret", "App secret"),
                   ("token", "Access token")],
    },
    "reddit": {
        "title": "Reddit key (optional)",
        "site": "https://www.reddit.com/prefs/apps",
        "steps": [
            "Only needed if Reddit stops letting Anon Brain read subreddits. Go to "
            "<b>reddit.com/prefs/apps</b> and click <b>create another app</b>.",
            "Pick <b>script</b>, give it a name, and use <b>http://localhost:8080</b> as the "
            "redirect URI. If Reddit asks you to request API access first, fill in the form "
            "(personal, non-commercial use is free).",
            "Copy the ID (the short code under the app's name) and the <b>secret</b> below.",
        ],
        "note": "Leave both boxes empty to go back to reading without a key.",
        "fields": [("id", "App ID"), ("secret", "Secret")],
    },
}


class ConnectDialog(QDialog):
    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        info = STEPS[key]
        self.setWindowTitle(info["title"])
        self.setMinimumWidth(620)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(10)
        root.addWidget(label(info["title"], "Title"))
        for i, step in enumerate(info["steps"], 1):
            row = QHBoxLayout()
            n = label(str(i))
            n.setFixedSize(26, 26)
            n.setAlignment(Qt.AlignCenter)
            n.setStyleSheet(f"background: {theme.primary()}; color: #0b0d10; font-weight: 800;"
                            " border-radius: 13px;")
            row.addWidget(n, 0, Qt.AlignTop)
            t = label(step, wrap=True)
            t.setTextFormat(Qt.RichText)
            row.addWidget(t, 1)
            root.addLayout(row)
            if info.get("copy") and step.rstrip().endswith(":"):
                c = QHBoxLayout()
                c.addSpacing(36)
                ed = QLineEdit(info["copy"])
                ed.setReadOnly(True)
                c.addWidget(ed, 1)
                c.addWidget(button("Copy", on_click=lambda _=False, v=info["copy"]:
                                   QGuiApplication.clipboard().setText(v)))
                root.addLayout(c)
        note = label(info["note"], "Hint", wrap=True)
        note.setTextFormat(Qt.RichText)
        root.addWidget(note)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.edits = {}
        saved = self._saved()
        for fkey, name in info["fields"]:
            ed = QLineEdit(saved.get(fkey, ""))
            ed.setMinimumHeight(36)
            if fkey in ("client_secret", "app_secret", "secret", "token"):
                ed.setEchoMode(QLineEdit.Password)
            form.addRow(label(name), ed)
            self.edits[fkey] = ed
        if info.get("file"):
            row = QHBoxLayout()
            self.file_label = label("No file chosen yet" if not saved.get("client_id") else
                                    "Client file added ✓", "Hint")
            row.addWidget(self.file_label, 1)
            row.addWidget(button("Choose file…", on_click=self.choose_file))
            form.addRow(label("Client file"), row)
        root.addLayout(form)
        self.status = label("", "Hint", wrap=True)
        root.addWidget(self.status)
        row = QHBoxLayout()
        row.addWidget(button("Open the site", "Link",
                             lambda: QDesktopServices.openUrl(QUrl(info["site"]))))
        row.addStretch()
        row.addWidget(button("Cancel", on_click=self.reject))
        self.ok = button("Save" if key == "reddit" else "Connect", "Primary", self.go)
        row.addWidget(self.ok)
        root.addLayout(row)

    def _saved(self) -> dict:
        if self.key == "reddit":
            from ..reddit_source import app
            return app()
        from ..posting import module
        return module(self.key).app()

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Google client file", "",
                                              "Client file (*.json)")
        if not path:
            return
        from ..posting import PostError, youtube
        try:
            cid, secret = youtube.read_client_file(path)
        except PostError as e:
            self.file_label.setText(str(e))
            return
        youtube.set_app(cid, secret)
        self.file_label.setText("Client file added ✓")

    def go(self):
        v = {k: e.text().strip() for k, e in self.edits.items()}
        if self.key == "reddit":
            from ..reddit_source import set_app
            set_app(v.get("id", ""), v.get("secret", ""))
            self.accept()
            return
        from ..posting import module
        mod = module(self.key)
        if self.key == "tiktok":
            if not v["client_key"] or not v["client_secret"]:
                return self._say("Fill in the Client key and secret first.", True)
            mod.set_app(v["client_key"], v["client_secret"])
            fn = mod.connect
            self._say("Approve Anon Brain in the browser window that just opened…")
        elif self.key == "youtube":
            fn = mod.connect
            self._say("Approve Anon Brain in the browser window that just opened…")
        else:
            if not v["token"]:
                return self._say("Paste the access token first.", True)
            mod.set_app(v["app_id"], v["app_secret"])
            fn = lambda: mod.connect(v["token"])
            self._say("Checking with Instagram…")
        self.ok.setEnabled(False)

        def done(name):
            self.ok.setEnabled(True)
            self.accept()

        def fail(msg, e):
            self.ok.setEnabled(True)
            self._say(msg, True)

        run_task(self, lambda emit: fn(), done, fail)

    def _say(self, text, bad=False):
        self.status.setObjectName("Error" if bad else "Hint")
        self.status.setStyleSheet("")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText(text)
