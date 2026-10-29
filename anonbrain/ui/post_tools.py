"""Post step helpers: tabs for each post in a thread, pasting, and links."""

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..settings import data_dir
from .common import button, label


def pasted_dir() -> Path:
    d = data_dir() / "pasted"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clipboard_content():
    """('image', path) / ('file', path) / ('link', url) / ('text', text) / (None, None)."""
    cb = QGuiApplication.clipboard()
    md = cb.mimeData()
    if md is None:
        return None, None
    if md.hasUrls():
        for u in md.urls():
            if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in (
                    ".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                return "file", u.toLocalFile()
    if md.hasImage():
        img = cb.image()
        if not img.isNull():
            out = pasted_dir() / f"pasted_{time.strftime('%Y%m%d_%H%M%S')}.png"
            img.save(str(out))
            return "image", str(out)
    if md.hasText():
        t = md.text().strip()
        from ..links import looks_like_link
        if looks_like_link(t):
            return "link", t
        return "text", t
    return None, None


def clipboard_content_peek():
    """Like clipboard_content() but only says what's there (saves nothing)."""
    md = QGuiApplication.clipboard().mimeData()
    if md is None:
        return None, None
    if md.hasUrls() and any(u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in (
            ".png", ".jpg", ".jpeg", ".webp", ".bmp") for u in md.urls()):
        return "file", None
    if md.hasImage():
        return "image", None
    return ("text", None) if md.hasText() else (None, None)


class PostTabs(QWidget):
    """Post 1 · Post 2 · … · ＋ Add post"""
    picked = Signal(int)
    add = Signal()
    remove = Signal()

    def __init__(self):
        super().__init__()
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(6)
        self.buttons = []
        self.add_btn = button("＋ Add a reply (thread)", "Link", lambda: self.add.emit(),
                              tip="Add a reply: the video reads the posts one after another")
        self.remove_btn = button("✕ Remove", "Link", lambda: self.remove.emit(),
                                 tip="Take this post out of the video")
        self.set_count(1, 0)

    def set_count(self, n: int, current: int):
        for b in self.buttons:
            b.deleteLater()
        self.buttons = []
        while self.row.count():
            self.row.takeAt(0)
        for i in range(n):
            b = QPushButton("Post 1 (OP)" if i == 0 and n > 1 else f"Post {i + 1}")
            b.setObjectName("PostTab")
            b.setCheckable(True)
            b.setChecked(i == current)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.picked.emit(i))
            self.row.addWidget(b)
            self.buttons.append(b)
            b.setVisible(n > 1)
        self.row.addWidget(self.add_btn)
        self.row.addStretch()
        self.row.addWidget(self.remove_btn)
        self.remove_btn.setVisible(n > 1)


class PostPicker(QDialog):
    """Choose which posts from a link go in the video."""

    def __init__(self, fetched, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose the posts")
        self.setMinimumSize(620, 520)
        self.fetched = fetched
        self.settings = settings
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)
        root.addWidget(label("Choose the posts", "Title"))
        many = "comments" if fetched.site == "reddit" else "replies"
        root.addWidget(label(
            f"Tick the posts to read, in order. Pick one for a single post, or add {many} "
            "to make a thread: each one is read after the other (you can give each its own "
            "voice in step 4).", "Muted", wrap=True))
        self.list = QListWidget()
        self.list.setAlternatingRowColors(False)
        for p in fetched.posts[:300]:
            depth = getattr(p, "depth", 0)
            who = ("OP · " if p.is_op else "") + (p.author or "Anonymous")
            if p.site == "4chan":
                who += f" · No.{p.number}"
            elif p.score:
                who += f" · ▲{p.score}"
            it = QListWidgetItem("      " * depth + f"{who}\n" + "      " * depth + p.preview(110))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if p.id in fetched.picked else Qt.Unchecked)
            it.setData(Qt.UserRole, p.id)
            self.list.addItem(it)
        self.list.itemChanged.connect(lambda _: self._count())
        root.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.theme_box = None
        if fetched.site == "reddit":
            row.addWidget(label("Look", "Hint"))
            self.theme_box = QComboBox()
            self.theme_box.addItem("Reddit dark", "dark")
            self.theme_box.addItem("Reddit light", "light")
            self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(
                settings["reddit_theme"])))
            row.addWidget(self.theme_box)
        row.addStretch()
        row.addWidget(button("Only the first", "Link", lambda: self._only_first()))
        row.addWidget(button("Cancel", on_click=self.reject))
        self.ok = button("Use these", "Primary", self.accept)
        row.addWidget(self.ok)
        root.addLayout(row)
        self._count()

    def _only_first(self):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Checked if i == 0 else Qt.Unchecked)

    def _count(self):
        n = len(self.chosen_ids())
        self.ok.setEnabled(n > 0)
        self.ok.setText(f"Use {n} post{'s' * (n != 1)}" if n else "Pick a post")

    def chosen_ids(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]

    def chosen(self):
        ids = set(self.chosen_ids())
        posts = [p for p in self.fetched.posts if p.id in ids]
        theme = self.theme_box.currentData() if self.theme_box else "dark"
        if self.theme_box:
            self.settings["reddit_theme"] = theme
        return posts, theme


def draw_posts(posts, reddit_theme: str, status=lambda m, f: None) -> list[tuple[str, object]]:
    """Fetch any pictures, then draw each post as a card: [(png path, PostText)]."""
    from .. import links
    from ..cards import draw
    out = []
    d = data_dir() / "cards"
    d.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(posts):
        status(f"Drawing post {i + 1} of {len(posts)}…", i / max(1, len(posts)))
        if p.site == "4chan":
            links.fourchan_thumbnail(p, lambda m, f=i / max(1, len(posts)): status(m, f))
        path = d / f"{p.site}_{p.community}_{p.id}_{reddit_theme}.png"
        png, pt = draw(p, path, reddit_theme)
        out.append((str(png), pt))
    return out
