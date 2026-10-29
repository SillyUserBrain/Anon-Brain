"""Settings screen: appearance, voices (ElevenLabs key + your own), accounts for
posting, text cleanup, and where / how videos are saved."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..voice import MODELS, get_key, set_key, test_key
from . import background, theme
from .background import GlassFrame
from .common import button, label, run_task

TABS = ["Appearance", "Voices", "Accounts", "Text cleanup", "Saving & speed", "About"]


class SettingsPanel(QWidget):
    """Shown inside the main window (so the glass and background stay visible)."""
    closed = Signal()
    appearance_changed = Signal()

    def __init__(self, state):
        super().__init__()
        self.setObjectName("Transparent")
        self.state = state
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(16)
        head = QHBoxLayout()
        head.addWidget(label("Settings", "Title"))
        head.addStretch()
        head.addWidget(button("Done", "Primary", self.finish))
        root.addLayout(head)

        card = GlassFrame(radius=22)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(18, 16, 18, 16)
        self.tabs = QTabWidget()
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.addTab(self._appearance_tab(), "Appearance")
        self.tabs.addTab(self._voices_tab(), "Voices")
        self.tabs.addTab(self._accounts_tab(), "Accounts")
        self.tabs.addTab(self._cleanup_tab(), "Text cleanup")
        self.tabs.addTab(self._output_tab(), "Saving && speed")
        self.tabs.addTab(self._about_tab(), "About")
        self.tabs.currentChanged.connect(self._tab_changed)
        inner.addWidget(self.tabs)
        root.addWidget(card, 1)

    def open_tab(self, tab):
        self.tabs.setCurrentIndex(TABS.index(tab) if isinstance(tab, str) else tab)
        self.key_edit.setText(get_key())

    # --- Appearance ----------------------------------------------------------
    def _appearance_tab(self):
        s = self.state.settings
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        lay.addWidget(label("Colors", "Section"))
        lay.addWidget(label("Primary is used for buttons and highlights. All three color the "
                            "background and the title.", "Hint", wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self.swatches, self.hex_edits = {}, {}
        for i, (key, name) in enumerate((("primary", "Primary"), ("secondary", "Secondary"),
                                         ("tertiary", "Tertiary"))):
            grid.addWidget(label(name), 0, i * 3)
            sw = button("", "Swatch", lambda _=False, k=key: self.pick_color(k), "Pick a color")
            sw.setFixedSize(44, 32)
            grid.addWidget(sw, 0, i * 3 + 1)
            ed = QLineEdit()
            ed.setFixedWidth(92)
            ed.editingFinished.connect(lambda k=key: self.hex_entered(k))
            grid.addWidget(ed, 0, i * 3 + 2)
            self.swatches[key], self.hex_edits[key] = sw, ed
        grid.setColumnStretch(9, 1)
        lay.addLayout(grid)

        presets = QHBoxLayout()
        presets.addWidget(label("Presets", "Hint"))
        for name, cols in theme.PRESETS.items():
            b = button(name, on_click=lambda _=False, c=cols: self.set_colors(*c))
            b.setStyleSheet(
                "QPushButton { border-radius: 14px; padding: 6px 14px; font-weight: 600;"
                f" color: #ffffff; border: 1px solid rgba(255,255,255,0.25);"
                f" background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {cols[0]},"
                f" stop:0.5 {cols[1]}, stop:1 {cols[2]}); }}")
            presets.addWidget(b)
        presets.addStretch()
        lay.addLayout(presets)

        lay.addSpacing(10)
        lay.addWidget(label("Background", "Section"))
        row = QHBoxLayout()
        row.addWidget(label("Style"))
        self.style_box = QComboBox()
        for sid, name in background.STYLES.items():
            self.style_box.addItem(name, sid)
        self.style_box.setCurrentIndex(max(0, self.style_box.findData(s["bg_style"])))
        self.style_box.currentIndexChanged.connect(
            lambda: self._set("bg_style", self.style_box.currentData()))
        self.style_box.setMinimumWidth(240)
        row.addWidget(self.style_box)
        row.addStretch()
        lay.addLayout(row)
        self.sliders = {}
        for key, name, lo, hi in (("bg_blur", "Blur", 0, 100), ("bg_speed", "Motion speed", 0, 100),
                                  ("bg_brightness", "Brightness", 20, 100)):
            r = QHBoxLayout()
            lab = label(name)
            lab.setFixedWidth(120)
            r.addWidget(lab)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(lo, hi)
            sl.setValue(int(s[key]))
            val = label(f"{sl.value()}%")
            val.setFixedWidth(46)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            sl.valueChanged.connect(lambda v, k=key, vl=val: (vl.setText(f"{v}%"), self._set(k, v)))
            r.addWidget(sl, 1)
            r.addWidget(val)
            lay.addLayout(r)
            self.sliders[key] = sl
        lay.addWidget(label("Motion speed 0 stops the animation (uses the least power).", "Hint"))
        self.anim_box = QCheckBox("Smooth animations (page transitions, button effects)")
        self.anim_box.setChecked(bool(s["ui_animations"]))
        self.anim_box.toggled.connect(self._set_animations)
        lay.addWidget(self.anim_box)
        r = QHBoxLayout()
        r.addStretch()
        r.addWidget(button("Reset appearance", "Link", self.reset_appearance))
        lay.addLayout(r)
        lay.addStretch()
        self._refresh_swatches()
        return w

    def _refresh_swatches(self):
        for key, sw in self.swatches.items():
            c = theme.COLORS[key]
            sw.setStyleSheet(f"QPushButton#Swatch {{ background: {c}; }}")
            self.hex_edits[key].setText(c.upper())

    def _set_animations(self, on):
        from . import anim
        anim.ENABLED = on
        self.state.settings.values["ui_animations"] = on

    def _set(self, key, value):
        self.state.settings.values[key] = value
        if background.CURRENT:
            background.CURRENT.apply_settings()

    def set_colors(self, p, s, t):
        st = self.state.settings.values
        st["color_primary"], st["color_secondary"], st["color_tertiary"] = p, s, t
        theme.apply_colors(QApplication.instance(), p, s, t)
        self._refresh_swatches()
        if background.CURRENT:
            background.CURRENT.apply_settings()
        self.appearance_changed.emit()

    def _colors_with(self, key, value):
        c = dict(theme.COLORS)
        c[key] = value
        return c["primary"], c["secondary"], c["tertiary"]

    def pick_color(self, key):
        c = QColorDialog.getColor(QColor(theme.COLORS[key]), self, f"Pick the {key} color")
        if c.isValid():
            self.set_colors(*self._colors_with(key, c.name()))

    def hex_entered(self, key):
        text = self.hex_edits[key].text().strip()
        if not text.startswith("#"):
            text = "#" + text
        if QColor.isValidColorName(text) if hasattr(QColor, "isValidColorName") else QColor(text).isValid():
            self.set_colors(*self._colors_with(key, QColor(text).name()))
        else:
            self._refresh_swatches()

    def reset_appearance(self):
        for k, v in (("bg_style", "orbs"), ("bg_blur", 60), ("bg_speed", 35), ("bg_brightness", 70)):
            self.state.settings.values[k] = v
        self.style_box.setCurrentIndex(self.style_box.findData("orbs"))
        for k in ("bg_blur", "bg_speed", "bg_brightness"):
            self.sliders[k].setValue(self.state.settings.values[k])
        self.set_colors(*theme.DEFAULT_COLORS)

    # --- ElevenLabs ----------------------------------------------------------
    def _voices_tab(self):
        """ElevenLabs (optional) and your own voices, in one scrolling tab."""
        from PySide6.QtWidgets import QFrame, QScrollArea

        from .voices_ui import VoicesTab
        host = QWidget()
        host.setObjectName("Transparent")
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._key_tab())
        lay.addWidget(VoicesTab(self.state,
                                play=lambda p: self.state.voice_page._play_sample_file(p)))
        lay.addStretch()
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(host)
        area.viewport().setAutoFillBackground(False)
        return area

    def _tab_changed(self, i):
        if i == 2:
            self.refresh_accounts()
        elif i == 5:
            self.refresh_about()

    def _about_tab(self):
        from .. import appinfo
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)
        head = label(f"{appinfo.NAME}  {appinfo.VERSION}", "Section")
        head.setStyleSheet("font-size: 14pt;")
        lay.addWidget(head)
        lay.addWidget(label("Posts in, videos out. Runs entirely on your PC.", "Muted"))
        lay.addSpacing(6)
        lay.addWidget(label("This PC", "Section"))
        self.about_info = label("", wrap=True)
        self.about_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.about_info.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace;")
        lay.addWidget(self.about_info)
        lay.addSpacing(6)
        lay.addWidget(label("Something not working?", "Section"))
        lay.addWidget(label("Copy error details puts the app version, your PC's setup and the "
                            "recent log on your clipboard. Paste it to whoever gave you the "
                            "app. It doesn't include keys, sign-ins or your posts' text.",
                            "Muted", wrap=True))
        row = QHBoxLayout()
        self.copy_err_btn = button("Copy error details", "Primary", self._copy_errors)
        row.addWidget(self.copy_err_btn)
        from .. import appinfo as _ai
        row.addWidget(button("Open log folder", on_click=lambda: _ai.open_folder(_ai.log_dir())))
        from ..settings import data_dir
        row.addWidget(button("Open data folder", on_click=lambda: _ai.open_folder(data_dir())))
        row.addStretch()
        lay.addLayout(row)

        from .. import updates
        lay.addSpacing(6)
        lay.addWidget(label("Updates", "Section"))
        urow = QHBoxLayout()
        self.update_auto = QCheckBox("Check for updates automatically")
        self.update_auto.setChecked(bool(self.state.settings["check_updates"]))
        self.update_auto.toggled.connect(lambda on: self._set("check_updates", on))
        urow.addWidget(self.update_auto)
        urow.addSpacing(10)
        self.update_btn = button("Check now", on_click=self._check_updates)
        urow.addWidget(self.update_btn)
        urow.addStretch()
        lay.addLayout(urow)
        self.update_status = label("", "Muted", wrap=True)
        lay.addWidget(self.update_status)
        if not updates.enabled():
            self.update_auto.hide()
            self.update_btn.hide()
            self.update_status.setText("Update checks aren't set up in this copy of the app.")

        lay.addSpacing(6)
        lay.addWidget(label("New here?", "Section"))
        trow = QHBoxLayout()
        trow.addWidget(button("Show the tour again", on_click=self._show_tour))
        trow.addStretch()
        lay.addLayout(trow)
        lay.addStretch()
        return w

    def _check_updates(self):
        win = self.state.window
        self.update_btn.setEnabled(False)
        self.update_status.setText("Checking…")

        def result(rel, err):
            self.update_btn.setEnabled(True)
            if err:
                self.update_status.setText(f"Couldn't check: {err}")
            elif rel is None:
                from .. import appinfo
                self.update_status.setText(f"You're up to date ({appinfo.VERSION}).")
            else:
                self.update_status.setText(f"Version {rel.version} is ready. Click “New update "
                                           "available” in the top-right corner.")
                win.updater.open_dialog()
        win.updater.check(manual=True, on_result=result)

    def _show_tour(self):
        win = self.state.window
        win.close_settings()
        QTimer.singleShot(450, win.start_tour)

    def refresh_about(self):
        from .. import appinfo
        self.about_info.setText(appinfo.system_info().replace("\n", "<br>"))
        self.copy_err_btn.setText("Copy error details")

    def _copy_errors(self):
        from .errors import copy_report
        copy_report()
        self.copy_err_btn.setText("✓ Copied")

    def _accounts_tab(self):
        """Where Automate posts: TikTok, YouTube, Instagram (and the optional Reddit key)."""
        from ..posting import NAMES, ORDER
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)
        lay.addWidget(label("Accounts", "Section"))
        lay.addWidget(label("Connect the apps ⚡ Automate posts to. Each one walks you through "
                            "making your own free developer app, which the sites require. "
                            "Sign-ins are kept in Windows Credential Manager.", "Muted",
                            wrap=True))
        self.acct_rows = {}
        rows = [(k, NAMES[k]) for k in ORDER] + [("reddit", "Reddit key (optional)")]
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        for i, (key, name) in enumerate(rows):
            grid.addWidget(label(name, "Section"), i, 0)
            st = label("", "Muted")
            grid.addWidget(st, i, 1)
            conn = button("Connect…", on_click=lambda _=False, k=key: self.connect_account(k))
            grid.addWidget(conn, i, 2)
            disc = button("Disconnect", "Link", lambda _=False, k=key: self.disconnect_account(k))
            grid.addWidget(disc, i, 3)
            self.acct_rows[key] = (st, conn, disc)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addWidget(label("Choose which apps each video goes to, and whether it waits for "
                            "your OK, in ⚡ Automate → Post to.", "Hint", wrap=True))
        lay.addStretch()
        self.refresh_accounts()
        return w

    def refresh_accounts(self):
        from ..posting import module
        from ..reddit_source import app as reddit_app
        for key, (st, conn, disc) in self.acct_rows.items():
            if key == "reddit":
                ok, name = bool(reddit_app().get("id")), ""
                st.setText("Key added ✓" if ok else "Not needed unless Reddit blocks reading")
            else:
                mod = module(key)
                ok, name = mod.connected(), mod.account()
                st.setText(("Connected" + (f" as {name}" if name else "") + " ✓") if ok
                           else "Not connected")
            conn.setText("Change…" if ok and key == "reddit" else
                         "Reconnect…" if ok else "Add key…" if key == "reddit" else "Connect…")
            disc.setVisible(ok)

    def connect_account(self, key):
        from .accounts_ui import ConnectDialog
        ConnectDialog(key, self).exec()
        self.refresh_accounts()

    def disconnect_account(self, key):
        if QMessageBox.question(self, "Disconnect", "Remove this sign-in from this PC?") != \
                QMessageBox.Yes:
            return
        if key == "reddit":
            from ..reddit_source import set_app
            set_app("", "")
        else:
            from ..posting import module
            module(key).disconnect()
        self.refresh_accounts()

    def _key_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 8)
        lay.setSpacing(10)
        lay.addWidget(label("ElevenLabs (optional)", "Section"))
        lay.addWidget(label(
            "Anon Brain works for free without this: its free voices run on your PC. "
            "A key adds your ElevenLabs voices, using your ElevenLabs credits. "
            "It's saved in Windows Credential Manager on this PC only. If you share the app, "
            "each person adds their own key.", "Muted", wrap=True))
        lay.addWidget(label(
            "Get one on elevenlabs.io: open your account settings, find <b>API Keys</b>, "
            "create a key and copy it (it's often only shown once).", "Hint", wrap=True))

        row = QHBoxLayout()
        self.key_edit = QLineEdit(get_key())
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("Paste your ElevenLabs API key")
        row.addWidget(self.key_edit, 1)
        show = QCheckBox("Show")
        show.toggled.connect(lambda v: self.key_edit.setEchoMode(
            QLineEdit.Normal if v else QLineEdit.Password))
        row.addWidget(show)
        lay.addLayout(row)

        row = QHBoxLayout()
        self.test_btn = button("Test && save key", "Primary", self.test_and_save)
        row.addWidget(self.test_btn)
        row.addWidget(button("Remove key", on_click=self.remove_key))
        row.addStretch()
        lay.addLayout(row)
        self.key_status = label("", wrap=True)
        lay.addWidget(self.key_status)

        row = QHBoxLayout()
        row.addWidget(label("ElevenLabs model"))
        self.model_box = QComboBox()
        for mid, name in MODELS.items():
            self.model_box.addItem(name, mid)
        self.model_box.setCurrentIndex(max(0, self.model_box.findData(self.state.settings["voice_model"])))
        self.model_box.currentIndexChanged.connect(
            lambda: self.state.settings.__setitem__("voice_model", self.model_box.currentData()))
        row.addWidget(self.model_box)
        row.addStretch()
        lay.addLayout(row)
        return w

    def test_and_save(self):
        key = self.key_edit.text().strip()
        if not key:
            self.key_status.setText("Paste a key first.")
            return
        self.test_btn.setEnabled(False)
        self.key_status.setText("Checking with ElevenLabs…")

        def done(n):
            set_key(key)
            self.state.voices = []          # reload with the new key
            self.test_btn.setEnabled(True)
            self.key_status.setText(f"<span style='color:{theme.primary()}'>✓ Key works and is saved. "
                                    f"{n} voices available.</span>")

        def fail(msg, e):
            self.test_btn.setEnabled(True)
            self.key_status.setText(f"<span style='color:{theme.RED}'>⚠ {msg} (not saved)</span>")

        run_task(self, lambda emit: test_key(key), done, fail)

    def remove_key(self):
        if QMessageBox.question(self, "Remove key", "Remove the saved ElevenLabs key from this PC?"
                                ) == QMessageBox.Yes:
            set_key("")
            self.key_edit.clear()
            self.state.voices = []
            self.key_status.setText("Key removed.")

    # --- Cleanup table -------------------------------------------------------
    def _cleanup_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.addWidget(label(
            "Shorthand on the left is read aloud as the words on the right. Click a cell to "
            "edit it. Changes save automatically.", "Muted", wrap=True))

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.textChanged.connect(self.fill_table)
        row.addWidget(self.search, 1)
        self.sort_box = QComboBox()
        self.sort_box.addItem("Newest first", "newest")
        self.sort_box.addItem("A–Z", "az")
        self.sort_box.currentIndexChanged.connect(self.fill_table)
        row.addWidget(self.sort_box)
        row.addWidget(button("＋", "Icon", self.add_row, "Add a new shorthand"))
        lay.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Shorthand", "Read as", ""])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(2, 44)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemChanged.connect(self._edited)
        lay.addWidget(self.table, 1)

        self.dup_label = label("", "Error", wrap=True)
        lay.addWidget(self.dup_label)
        row = QHBoxLayout()
        self.count_label = label("", "Hint")
        row.addWidget(self.count_label)
        row.addStretch()
        row.addWidget(button("Reset to starter list", "Link", self.reset_table))
        lay.addLayout(row)
        self.fill_table()
        return w

    def fill_table(self, focus_entry=None):
        table = self.state.cleanup
        q = self.search.text().strip().lower()
        entries = [e for e in table.sorted(self.sort_box.currentData())
                   if not q or q in e.short.lower() or q in e.full.lower() or e is focus_entry]
        self.table.blockSignals(True)
        self.table.setRowCount(len(entries))
        self.rows = entries
        for r, e in enumerate(entries):
            self.table.setItem(r, 0, QTableWidgetItem(e.short))
            self.table.setItem(r, 1, QTableWidgetItem(e.full))
            delete = button("🗑", "Link", lambda _=False, e=e: self.delete_entry(e), "Delete")
            self.table.setCellWidget(r, 2, delete)
        self.table.blockSignals(False)
        self.count_label.setText(f"{len(table.entries)} entries")
        if focus_entry is not None and focus_entry in entries:
            r = entries.index(focus_entry)
            self.table.setCurrentCell(r, 0)
            self.table.scrollToItem(self.table.item(r, 0))
            self.table.editItem(self.table.item(r, 0))

    def _edited(self, item):
        e = self.rows[item.row()]
        text = item.text().strip()
        if item.column() == 0:
            dup = self.state.cleanup.find(text, exclude=e)
            if dup:
                self.table.blockSignals(True)
                item.setText(e.short)
                self.table.blockSignals(False)
                self.dup_label.setText(f"“{dup.short}” is already in the list (read as “{dup.full}”).")
                return
            e.short = text
        else:
            e.full = text
        self.dup_label.setText("")
        self.state.cleanup.save()

    def add_row(self):
        # reuse an empty row instead of stacking blank ones
        e = next((x for x in self.state.cleanup.entries if not x.short.strip()), None)
        e = e or self.state.cleanup.add()
        self.state.cleanup.save()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.fill_table(focus_entry=e)

    def delete_entry(self, e):
        self.state.cleanup.entries.remove(e)
        self.state.cleanup.save()
        self.fill_table()

    def reset_table(self):
        if QMessageBox.question(self, "Reset list",
                                "Replace your list with the starter list? Your own additions "
                                "will be removed.") == QMessageBox.Yes:
            self.state.cleanup.reset_to_starter()
            self.fill_table()

    def finish(self):
        # drop rows left completely empty
        c = self.state.cleanup
        c.entries = [e for e in c.entries if e.short.strip() or e.full.strip()]
        c.save()
        self.state.settings.save()
        self.fill_table()
        self.closed.emit()

    # --- Output --------------------------------------------------------------
    def _output_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.addWidget(label("Save videos to", "Section"))
        row = QHBoxLayout()
        self.out_label = label(self.state.settings["output_dir"], wrap=True)
        row.addWidget(self.out_label, 1)
        row.addWidget(button("Change…", on_click=self.change_output))
        lay.addLayout(row)

        lay.addSpacing(18)
        lay.addWidget(label("Render with", "Section"))
        lay.addWidget(label("Your graphics card can make videos several times faster than the "
                            "processor. If it ever has a problem, Anon Brain quietly uses the "
                            "processor instead.", "Muted", wrap=True))
        row = QHBoxLayout()
        from ..encoders import CHOICES
        self.enc_box = QComboBox()
        for key, name in CHOICES:
            self.enc_box.addItem(name, key)
        self.enc_box.setCurrentIndex(max(0, self.enc_box.findData(
            self.state.settings["encoder"] or "auto")))
        self.enc_box.currentIndexChanged.connect(
            lambda: self.state.settings.__setitem__("encoder", self.enc_box.currentData()))
        row.addWidget(self.enc_box, 1)
        self.enc_check = button("Check again", on_click=lambda: self.check_encoders(True),
                                tip="Test each graphics card encoder again (after a driver "
                                    "or FFmpeg update)")
        row.addWidget(self.enc_check)
        lay.addLayout(row)
        self.enc_status = label("Checking your graphics card…", "Hint", wrap=True)
        lay.addWidget(self.enc_status)
        lay.addStretch()
        self.check_encoders(False)
        return w

    def check_encoders(self, force=False):
        from ..encoders import KINDS, describe, detect
        self.enc_status.setText("Checking your graphics card…")
        self.enc_check.setEnabled(False)

        def done(found):
            self.enc_check.setEnabled(True)
            self.enc_status.setText(describe(found))
            for i in range(self.enc_box.count()):
                key = self.enc_box.itemData(i)
                if key in KINDS:
                    name = dict(__import__("anonbrain.encoders", fromlist=["CHOICES"]).CHOICES)[key]
                    self.enc_box.setItemText(i, name + ("  ✓" if found.get(key) else
                                                        "  (not found)"))

        def fail(msg, e):
            self.enc_check.setEnabled(True)
            self.enc_status.setText(f"Couldn't check: {msg}")

        run_task(self, lambda emit: detect(force), done, fail)

    def change_output(self):
        d = QFileDialog.getExistingDirectory(self, "Where should videos be saved?",
                                             self.state.settings["output_dir"])
        if d:
            self.state.settings["output_dir"] = d
            self.out_label.setText(d)
