"""Keyboard shortcuts, and the cheat sheet (F1)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QVBoxLayout

from .common import button, label

# (where, keys, what) - shown on the cheat sheet
SHEET = [
    ("Anywhere", "Ctrl+→  /  Ctrl+←", "Next step / previous step"),
    ("Anywhere", "Ctrl+1 … Ctrl+5", "Jump to a step"),
    ("Anywhere", "Ctrl+Enter", "Next step (on step 5: make the video)"),
    ("Anywhere", "Ctrl+H", "History"),
    ("Anywhere", "Ctrl+Shift+A", "Automate"),
    ("Anywhere", "Ctrl+,", "Settings"),
    ("Anywhere", "Ctrl+S", "Save the current look as a preset"),
    ("Anywhere", "Esc", "Close Settings / History / Automate"),
    ("Anywhere", "F1", "This list"),
    ("Post", "Ctrl+V", "Paste a screenshot or a Reddit / 4chan link"),
    ("Post", "Ctrl+B", "Add the post to the batch"),
    ("Post", "Ctrl+N", "Add another post (make a thread)"),
    ("Layout", "Ctrl+Z  /  Ctrl+Y", "Undo / redo (also Ctrl+Shift+Z)"),
    ("Layout", "Arrow keys", "Nudge the post (Shift: bigger steps)"),
    ("Layout", "+  /  −", "Make the post bigger / smaller"),
    ("Layout", "T  /  C  /  B", "Snap the post to the top / center / bottom"),
    ("Layout", "F", "Fit width"),
    ("Layout", "1  2  3  4", "Shape: vertical, portrait, square, widescreen"),
    ("Voice", "Ctrl+Space", "Play / stop the mix preview"),
    ("Render", "Ctrl+P", "Quick preview"),
]


def _sc(parent, keys, fn, context=Qt.WindowShortcut):
    for k in ([keys] if isinstance(keys, (str, QKeySequence.StandardKey)) else keys):
        s = QShortcut(QKeySequence(k), parent)
        s.setContext(context)
        s.activated.connect(fn)


def install(window):
    st = window.state

    def on(page_attr):
        return window.screens.currentWidget() is window.wizard and \
            window.pages[window.index] is getattr(st, page_attr)

    def step(delta):
        if window.screens.currentWidget() is window.wizard:
            window.go(window.index + delta)

    def jump(i):
        if window.screens.currentWidget() is not window.wizard:
            window.show_screen(window.wizard, -1)
        window.go(i)

    def enter():
        if window.screens.currentWidget() is not window.wizard:
            return
        if on("render_page"):
            rp = st.render_page
            if not rp.running and rp.make_btn.isEnabled():
                rp.make()
        else:
            step(1)

    def undo(redo=False):
        if on("layout_page"):
            (st.layout_page.redo if redo else st.layout_page.undo)()

    def escape():
        if window.screens.currentWidget() in (window.settings_panel, window.history_page,
                                              window.automate_page):
            window.close_settings()

    _sc(window, ["Ctrl+Right", "Alt+Right"], lambda: step(1))
    _sc(window, ["Ctrl+Left", "Alt+Left"], lambda: step(-1))
    for i in range(5):
        _sc(window, f"Ctrl+{i + 1}", lambda i=i: jump(i))
    _sc(window, ["Ctrl+Return", "Ctrl+Enter"], enter)
    _sc(window, "Ctrl+H", window.open_history)
    _sc(window, "Ctrl+Shift+A", window.open_automate)
    _sc(window, "Ctrl+,", lambda: window.open_settings())
    _sc(window, "Ctrl+S", lambda: window.preset_menu.save_new())
    _sc(window, "Escape", escape)
    _sc(window, ["F1", "Ctrl+/"], lambda: CheatSheet(window).exec())
    _sc(window, "Ctrl+Z", lambda: undo())
    _sc(window, ["Ctrl+Y", "Ctrl+Shift+Z"], lambda: undo(True))
    _sc(window, "Ctrl+P", lambda: on("render_page") and not st.render_page.running
        and st.render_page.preview())
    _sc(window, "Ctrl+B", lambda: on("post_page") and st.post_page.add_to_batch())
    _sc(window, "Ctrl+N", lambda: on("post_page") and st.post_page.add_post())
    _sc(window, "Ctrl+Space", lambda: on("voice_page") and st.voice_page.toggle_preview())

    # Layout step: plain letters (typing in a text box still types, as usual)
    lp = st.layout_page
    ctx = Qt.WidgetWithChildrenShortcut
    _sc(lp, "T", lambda: lp.snap("top"), ctx)
    _sc(lp, "C", lambda: lp.snap("center"), ctx)
    _sc(lp, "B", lambda: lp.snap("bottom"), ctx)
    _sc(lp, "F", lp.fit_width, ctx)
    for key, fmt in (("1", "9:16"), ("2", "4:5"), ("3", "1:1"), ("4", "16:9")):
        _sc(lp, key, lambda f=fmt: lp.set_format(f), ctx)


class CheatSheet(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(10)
        root.addWidget(label("Keyboard shortcuts", "Title"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(5)
        r, last = 0, None
        for where, keys, what in SHEET:
            if where != last:
                if last is not None:
                    r += 1
                grid.addWidget(label(where, "Section"), r, 0, 1, 2)
                r += 1
                last = where
            k = label(keys)
            k.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace; "
                            "color: white; background: rgba(255,255,255,0.08); "
                            "border-radius: 6px; padding: 2px 8px;")
            grid.addWidget(k, r, 0, Qt.AlignLeft)
            grid.addWidget(label(what, "Muted"), r, 1)
            r += 1
        root.addLayout(grid)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("Got it", "Primary", self.accept))
        root.addLayout(row)
