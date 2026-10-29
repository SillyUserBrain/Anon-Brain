"""Opens the real window off-screen and clicks through every screen, failing if
anything raises an error along the way. Doesn't play sound or video."""

import sys

_app = _win = None
_errors: list = []


def _setup():
    """One window for all the UI checks (Qt allows only one app per run)."""
    global _app, _win
    if _win is not None:
        return _win
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(sys.argv[:1])
    _app.setStyle("Fusion")
    from anonbrain.ui.theme import build_style
    _app.setStyleSheet(build_style())

    class FakeOut:                     # real media players crash without a screen
        def setVolume(self, v):
            pass

    class FakePlayer(QObject):
        mediaStatusChanged = Signal(object)
        playbackStateChanged = Signal(object)
        Infinite, EndOfMedia, PlayingState = -1, 7, 1

        def __getattr__(self, name):   # setSource, play, pause, stop, ...
            return lambda *a, **k: None

        def playbackState(self):
            return 0

    import anonbrain.ui.pages as P
    P.QAudioOutput, P.QMediaPlayer = FakeOut, FakePlayer

    old_hook = sys.excepthook
    sys.excepthook = lambda *exc: (_errors.append(exc), old_hook(*exc))

    # "No voice": the free voices would be made for real in the background (slow here)
    from anonbrain.settings import Settings
    from anonbrain.voice import NO_VOICE
    s = Settings()
    s.values.update(tour_done=True, last_voice_id=NO_VOICE)
    s.save()
    s.flush()

    from anonbrain.ui.main_window import MainWindow
    _win = MainWindow()
    _win.resize(1100, 760)
    _win.show()
    return _win


def wait(ms):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def until(cond, secs):
    for _ in range(int(secs * 10)):
        if cond():
            return True
        wait(100)
    return False


def _no_errors():
    if _errors:
        import traceback
        msg = "".join(traceback.format_exception(*_errors[0]))
        _errors.clear()
        raise AssertionError("the app raised an error:\n" + msg)


def test_wizard_walkthrough():
    from tests.helpers import gameplay, reddit_card
    w = _setup()
    st = w.state
    w.splash.start.emit()
    wait(400)
    g = st.gameplay_page
    g.file = str(gameplay())
    g.set_mode("file")
    g.refresh()
    wait(800)
    assert g.is_complete()

    w.go(1)
    pp = st.post_page
    pp.load_image(reddit_card()[0])
    assert until(lambda: pp.posts[0]["post_text"] is not None, 60), "post was never read"
    assert pp.is_complete()

    w.go(2)
    lp = st.layout_page
    assert until(lambda: lp.canvas.bg is not None, 30)
    for fmt in ("1:1", "16:9", "9:16"):
        lp.set_format(fmt)
        wait(150)
    for i in range(lp.tabs.count()):
        lp.tabs.setCurrentIndex(i)
        wait(150)
    for fps in (24, 60, 30):
        lp.set_fps(fps)
    lp.mirror_box.setCurrentIndex(2)
    lp.fit_box.setCurrentIndex(1)
    wait(200)
    lp.undo()
    lp.undo()

    w.go(3)
    wait(400)
    w.go(4)
    wait(1500)
    job = st.build_job()
    assert job.fps == 30 and job.post_image and not job.clip_only
    _no_errors()


def test_clip_mode_keeps_volumes_apart():
    w = _setup()
    st = w.state
    w.go(1)
    pp, vp = st.post_page, st.voice_page
    normal = st.settings["game_volume"]
    pp.clip_box.setChecked(True)
    wait(200)
    assert pp.is_complete()
    w.go(3)
    vp.game_slider.setValue(77)
    wait(100)
    assert st.settings["clip_volume"] == 77 and st.settings["game_volume"] == normal
    job = st.build_job()
    assert job.clip_only and job.game_volume == 77
    w.go(1)
    pp.clip_box.setChecked(False)
    wait(200)
    assert st.build_job().game_volume == normal
    _no_errors()


def test_music_folder_option():
    from tests.helpers import songs
    w = _setup()
    st = w.state
    vp = st.voice_page
    w.go(3)
    wait(200)
    vp.set_music_folder(str(songs()))
    wait(100)
    assert "4 songs" in vp.music_label.text() and vp.folder_box.isVisible()
    assert not vp.song_box.isVisible()
    job = st.build_job()
    assert job.music_folder == str(songs()) and job.music_path == ""
    vp.repeat_box.setChecked(True)
    assert st.build_job().repeat_songs and "(repeats allowed)" in vp.summary_music()
    vp.repeat_box.setChecked(False)
    st.gameplay_page.reuse.setChecked(True)
    assert st.build_job().reuse_footage
    st.gameplay_page.reuse.setChecked(False)
    assert not st.build_job().reuse_footage
    vp.hear_random()
    assert vp._sample_song is not None and "Playing" in vp.preview_status.text()
    vp.stop_preview()
    w.go(4)
    wait(400)
    assert "Random song from songs" in st.render_page.rows["Music"].text()
    from anonbrain.presets import Values
    assert st.look_from(Values(st.settings, None))["music_folder"] == str(songs())
    w.go(3)
    vp.set_music("")
    assert st.build_job().music_folder == "" and not vp.folder_box.isVisible()
    _no_errors()


def test_side_screens():
    from tests.helpers import gameplay
    w = _setup()
    h = w.state.history
    h.add(gameplay(), "A story for the history screen", "", "", "", "", 0.0, 5.0)
    w.state.events.history_changed.emit()
    for i in range(w.settings_panel.tabs.count()):
        w.open_settings(i)
        wait(250)
    w.open_history()
    wait(500)
    from anonbrain.ui.common import _thumbs
    assert any(k[1:] == (226, 150) for k in _thumbs), "history thumbnail not shown"
    w.open_automate()
    for i in range(w.automate_page.tabs.count()):
        w.automate_page.tabs.setCurrentIndex(i)
        wait(250)
    w.go(0)
    wait(300)
    _no_errors()


def test_tour():
    w = _setup()
    w.go(0)
    wait(300)
    w.start_tour()
    assert w.tour is not None
    for _ in range(12):
        wait(150)
        if w.tour is None:
            break
        w.tour.show_step(w.tour.i + 1)
    assert w.tour is None and w.state.settings["tour_done"]
    _no_errors()


def teardown():
    """Close the window the way you would, letting background work finish."""
    global _win
    if _win is None:
        return
    from anonbrain.ui.common import wait_for_tasks
    _win.close()
    wait(300)
    if not wait_for_tasks(30000):
        from anonbrain.ui.common import _running
        names = [getattr(t.fn, "__qualname__", repr(t.fn)) for t in _running if t.isRunning()]
        raise AssertionError(f"background work never finished: {names}")
    _win.deleteLater()
    wait(200)
    _win = None
