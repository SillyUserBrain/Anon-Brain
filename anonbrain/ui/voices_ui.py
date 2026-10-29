"""Adding your own AI voices: the "Add a voice" window and Settings → Voices."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import custom_voices as C
from .. import free_tts
from ..settings import cache_dir
from . import theme
from .common import Card, button, label, run_task

HELP = {
    "elevenlabs": "Any ElevenLabs voice: one from the Voice Library, or one someone shared "
                  "with you. Open the voice on elevenlabs.io and copy its <b>Voice ID</b>. "
                  "Uses your API key (Settings → ElevenLabs). Voices already in your "
                  "ElevenLabs account show up on their own, no need to add them.",
    "piper": "Free voices that run on your PC. Thousands are shared online (search "
             "“Piper voices”). Each voice is two files: <b>name.onnx</b> and "
             "<b>name.onnx.json</b>. Keep them in the same folder and pick the .onnx. "
             "The first Piper voice sets Piper up (a few MB, one time).",
    "kokoro": "A voice file for the free Kokoro voices: a single voice (<b>.npy</b>) or a "
              "voice pack (<b>.bin</b> / <b>.npz</b>), where you pick the voice inside.",
    "blend": "Make a brand-new voice by mixing two of the free voices. Slide to choose how "
             "much of each.",
    "server": "Any text-to-speech server with an OpenAI-style <b>/v1/audio/speech</b> address: "
              "OpenAI itself, or programs you run yourself like Kokoro-FastAPI, AllTalk or "
              "openedai-speech. For OpenAI use <b>https://api.openai.com/v1</b>, model "
              "<b>tts-1</b> and a voice like <b>onyx</b>.",
}


class AddVoiceDialog(QDialog):
    """Pick a kind of voice, fill in its details, test it, add it."""

    def __init__(self, state, parent=None, play=None):
        super().__init__(parent)
        self.state = state
        self.play = play
        self.added = None
        self.setWindowTitle("Add your own voice")
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)
        root.addWidget(label("Add your own voice", "Title"))

        row = QHBoxLayout()
        row.addWidget(label("Type", "Section"))
        self.kind = QComboBox()
        for k, name in C.KINDS.items():
            self.kind.addItem(name, k)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        row.addWidget(self.kind, 1)
        root.addLayout(row)
        self.help = label("", "Hint", wrap=True)
        self.help.setTextFormat(Qt.RichText)
        root.addWidget(self.help)

        self.forms = QStackedWidget()
        self.fields = {}
        for k in C.KINDS:
            self.forms.addWidget(getattr(self, f"_form_{k}")())
        root.addWidget(self.forms)

        row = QHBoxLayout()
        row.addWidget(label("Name", "Section"))
        self.name = QLineEdit()
        self.name.setPlaceholderText("What to call it in the voice list")
        row.addWidget(self.name, 1)
        root.addLayout(row)

        self.status = label("", wrap=True)
        root.addWidget(self.status)
        row = QHBoxLayout()
        self.test_btn = button("▶  Test", on_click=self.test, tip="Hear a short sample")
        row.addWidget(self.test_btn)
        row.addStretch()
        row.addWidget(button("Cancel", on_click=self.reject))
        self.add_btn = button("Add voice", "Primary", self.accept_voice)
        row.addWidget(self.add_btn)
        root.addLayout(row)
        self._kind_changed()

    # --- forms ------------------------------------------------------------------
    def _grid(self):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 4, 0, 4)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        g.setColumnStretch(1, 1)
        g.setAlignment(Qt.AlignTop)
        return w, g

    def _file_row(self, g, r, key, caption, filt):
        edit = QLineEdit()
        edit.setPlaceholderText("Choose a file…")
        edit.setReadOnly(True)
        g.addWidget(label(caption), r, 0)
        g.addWidget(edit, r, 1)

        def pick():
            f, _ = QFileDialog.getOpenFileName(self, caption, "", filt)
            if f:
                edit.setText(f)
                self._file_picked(key, Path(f))
        g.addWidget(button("Browse…", on_click=pick), r, 2)
        self.fields[key] = edit

    def _form_elevenlabs(self):
        w, g = self._grid()
        self.fields["el_id"] = QLineEdit()
        self.fields["el_id"].setPlaceholderText("e.g. 21m00Tcm4TlvDq8ikWAM")
        g.addWidget(label("Voice ID"), 0, 0)
        g.addWidget(self.fields["el_id"], 0, 1)
        return w

    def _form_piper(self):
        w, g = self._grid()
        self._file_row(g, 0, "piper_file", "Voice file", "Piper voice (*.onnx)")
        return w

    def _form_kokoro(self):
        w, g = self._grid()
        self._file_row(g, 0, "kokoro_file", "Voice file", "Kokoro voice (*.npy *.bin *.npz)")
        self.fields["kokoro_pick"] = QComboBox()
        self.pick_label = label("Voice in pack")
        g.addWidget(self.pick_label, 1, 0)
        g.addWidget(self.fields["kokoro_pick"], 1, 1, 1, 2)
        self.fields["kokoro_accent"] = QComboBox()
        self.fields["kokoro_accent"].addItem("American English", "us")
        self.fields["kokoro_accent"].addItem("British English", "uk")
        g.addWidget(label("Accent"), 2, 0)
        g.addWidget(self.fields["kokoro_accent"], 2, 1, 1, 2)
        self.pick_label.setVisible(False)
        self.fields["kokoro_pick"].setVisible(False)
        self.fields["kokoro_pick"].currentTextChanged.connect(self._suggest_name)
        return w

    def _form_blend(self):
        w, g = self._grid()
        for r, key in ((0, "a"), (1, "b")):
            box = QComboBox()
            for vid, name in free_tts.VOICES.items():
                box.addItem(name, vid)
            box.setCurrentIndex(box.findData("am_michael" if key == "a" else "am_onyx"))
            box.currentIndexChanged.connect(self._blend_name)
            g.addWidget(label("First voice" if key == "a" else "Second voice"), r, 0)
            g.addWidget(box, r, 1, 1, 2)
            self.fields[f"blend_{key}"] = box
        mix = QSlider(Qt.Horizontal)
        mix.setRange(0, 100)
        mix.setValue(50)
        self.mix_label = label("50 / 50", "Muted")
        mix.valueChanged.connect(lambda v: (self.mix_label.setText(f"{100 - v} / {v}"),
                                            self._blend_name()))
        g.addWidget(label("Mix"), 2, 0)
        g.addWidget(mix, 2, 1)
        g.addWidget(self.mix_label, 2, 2)
        self.fields["blend_mix"] = mix
        return w

    def _form_server(self):
        w, g = self._grid()
        rows = [("url", "Address", "https://api.openai.com/v1  or  http://localhost:8880/v1"),
                ("key", "API key", "Leave empty if the server doesn't need one"),
                ("model", "Model", "tts-1"),
                ("voice", "Voice", "onyx")]
        for r, (key, cap, ph) in enumerate(rows):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            if key == "key":
                e.setEchoMode(QLineEdit.Password)
            g.addWidget(label(cap), r, 0)
            g.addWidget(e, r, 1, 1, 2)
            self.fields[f"srv_{key}"] = e
        self.fields["srv_voice"].textChanged.connect(
            lambda t: self._suggest_name(t.strip().title()))
        return w

    # --- behaviour ----------------------------------------------------------------
    def _kind_changed(self):
        k = self.kind.currentData()
        self.forms.setCurrentIndex(list(C.KINDS).index(k))
        from PySide6.QtWidgets import QSizePolicy
        for i in range(self.forms.count()):        # only the shown form takes up room
            pol = QSizePolicy.Preferred if i == self.forms.currentIndex() else QSizePolicy.Ignored
            self.forms.widget(i).setSizePolicy(pol, pol)
        self.forms.adjustSize()
        self.adjustSize()
        self.help.setText(HELP[k])
        self.status.setText("")
        if k == "blend":
            self._blend_name()

    def _suggest_name(self, name):
        if name and (not self.name.text() or getattr(self, "_auto_name", "") == self.name.text()):
            self.name.setText(name)
            self._auto_name = name

    def _blend_name(self):
        a = self.fields["blend_a"].currentText().split(" ·")[0]
        b = self.fields["blend_b"].currentText().split(" ·")[0]
        self._suggest_name(f"{a} + {b}")

    def _file_picked(self, key, path: Path):
        stem = path.name.split(".")[0].replace("_", " ").replace("-", " ").strip()
        self._suggest_name(stem.title())
        if key == "piper_file":
            if C._piper_config(path) is None:
                self._say(f"⚠ {path.name}.json isn't in the same folder. Piper voices need "
                          "both files.", bad=True)
            else:
                self._say("")
        if key == "kokoro_file":
            box = self.fields["kokoro_pick"]
            box.clear()
            try:
                names = C.kokoro_names(path)
            except C.CustomVoiceError as e:
                self._say(f"⚠ {e}", bad=True)
                names = []
            for n in names:
                box.addItem(n, n)
            box.setVisible(bool(names))
            self.pick_label.setVisible(bool(names))
            if names:
                self._suggest_name(names[0])

    def _say(self, text, bad=False, good=False):
        color = theme.RED if bad else theme.primary() if good else None
        self.status.setText(f"<span style='color:{color}'>{text}</span>" if color and text
                            else text)

    def voice(self) -> tuple[dict | None, str]:
        """The voice described by the form, plus a server API key."""
        k = self.kind.currentData()
        f = self.fields
        v = {"kind": k, "name": self.name.text().strip()}
        if k == "elevenlabs":
            v["voice_id"] = f["el_id"].text().strip()
            if not v["voice_id"]:
                return None, "Paste the voice's ID."
        elif k == "piper":
            v["file"] = f["piper_file"].text()
            if not v["file"]:
                return None, "Choose the voice's .onnx file."
        elif k == "kokoro":
            v["file"] = f["kokoro_file"].text()
            if not v["file"]:
                return None, "Choose the voice file."
            v["pick"] = f["kokoro_pick"].currentData() or ""
            v["accent"] = f["kokoro_accent"].currentData()
        elif k == "blend":
            v["a"] = f["blend_a"].currentData()
            v["b"] = f["blend_b"].currentData()
            v["mix"] = f["blend_mix"].value() / 100
        elif k == "server":
            v["url"] = f["srv_url"].text().strip()
            v["model"] = f["srv_model"].text().strip() or "tts-1"
            v["voice"] = f["srv_voice"].text().strip() or "alloy"
            if not v["url"]:
                return None, "Type the server's address."
            return v, f["srv_key"].text().strip()
        return v, ""

    def test(self):
        v, extra = self.voice()
        if v is None:
            self._say(extra, bad=True)
            return
        out = cache_dir() / "sample_new_voice.wav"
        self.test_btn.setEnabled(False)
        self._say("Making a sample…")

        def work(emit):
            if v["kind"] == "elevenlabs":
                from ..voice import _elevenlabs_line
                return _elevenlabs_line("Be me. Find a post. Turn it into a video.",
                                        v["voice_id"], self.state.settings["voice_model"],
                                        "", "")[0]
            return C.test_voice(v, out, api_key=extra, status=emit)

        def done(path):
            self.test_btn.setEnabled(True)
            self._say("✓ Works. Playing the sample.", good=True)
            if self.play:
                self.play(path)

        def fail(msg, e):
            self.test_btn.setEnabled(True)
            self._say(f"⚠ {msg}", bad=True)

        run_task(self, work, done, fail, lambda m, f: self._say(m))

    def accept_voice(self):
        v, extra = self.voice()
        if v is None:
            self._say(extra, bad=True)
            return
        if not v["name"]:
            self._say("Give the voice a name.", bad=True)
            return
        try:
            self.added = C.add(self.state.settings, v, api_key=extra)
        except (C.CustomVoiceError, OSError) as e:
            self._say(f"⚠ {e}", bad=True)
            return
        self.state.events.voices_changed.emit()
        self.accept()


def sample_voice(owner, state, v: dict, play):
    """Make (once) and play a short sample of one of your voices."""
    out = cache_dir() / f"sample_custom_{v['id']}.wav"

    def work(emit):
        if v["kind"] == "elevenlabs":
            from ..voice import _elevenlabs_line
            return _elevenlabs_line("Be me. Find a post. Turn it into a video.",
                                    v["voice_id"], state.settings["voice_model"], "", "")[0]
        if out.exists():
            return out
        return C.synthesize(v, "Be me. Find a post. Turn it into a video.", out, emit)

    run_task(owner, work, play, lambda msg, e: QMessageBox.warning(owner, "Voice sample", msg))


def add_voice(state, parent, play=None) -> dict | None:
    """Open the Add a voice window; returns the new voice (or None)."""
    dlg = AddVoiceDialog(state, parent, play)
    dlg.exec()
    return dlg.added


class VoicesTab(QWidget):
    """Settings → Voices: the voices you've added."""

    def __init__(self, state, play=None):
        super().__init__()
        self.state = state
        self.play = play
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label("Your voices", "Section"))
        head.addStretch()
        head.addWidget(button("＋  Add a voice", "Primary", self.add))
        lay.addLayout(head)
        lay.addWidget(label(
            "Have an AI voice of your own? Add it here and it shows up in step 4 under "
            "<b>Your voices</b>. You can add ElevenLabs voice IDs, Piper or Kokoro voice "
            "files, a mix of two free voices, or a voice server.", "Muted", wrap=True))
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        lay.addLayout(self.list)
        self.empty = label("No voices added yet.", "Hint")
        lay.addWidget(self.empty)
        lay.addStretch()
        state.events.voices_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w:
                w.deleteLater()
        voices = C.all_voices(self.state.settings)
        self.empty.setVisible(not voices)
        for v in voices:
            card = Card()
            card.body.setContentsMargins(14, 10, 10, 10)
            row = QHBoxLayout()
            name = label(v["name"], "Section")
            row.addWidget(name)
            row.addWidget(label(C.describe(v), "Muted"))
            row.addStretch()
            row.addWidget(button("▶", on_click=lambda _=False, v=v: self.sample(v),
                                 tip="Hear a sample"))
            row.addWidget(button("Rename", on_click=lambda _=False, v=v: self.rename(v)))
            row.addWidget(button("✕", on_click=lambda _=False, v=v: self.remove(v),
                                 tip="Remove this voice"))
            card.body.addLayout(row)
            self.list.addWidget(card)

    def add(self):
        add_voice(self.state, self, self.play)

    def sample(self, v):
        if self.play is not None:
            sample_voice(self, self.state, v, self.play)

    def rename(self, v):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Rename voice", "New name:", text=v["name"])
        if ok and name.strip():
            C.rename(self.state.settings, v["id"], name)
            self.state.events.voices_changed.emit()

    def remove(self, v):
        if QMessageBox.question(self, "Remove voice",
                                f"Remove “{v['name']}”? Videos you already made keep their "
                                "sound.") == QMessageBox.Yes:
            C.remove(self.state.settings, v["id"])
            self.state.events.voices_changed.emit()
