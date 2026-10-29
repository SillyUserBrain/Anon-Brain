"""Fast checks of the app's logic (no rendering, no internet)."""

from datetime import datetime
from pathlib import Path


def test_links_parse():
    from anonbrain.links import parse
    assert parse("https://www.reddit.com/r/delta/comments/abc123/some_title/")[0] == "reddit"
    assert parse("reddit.com/r/delta/s/2gUkOZbCuK")[0] == "reddit"
    assert parse("https://redd.it/abc123")[0] == "reddit"
    assert parse("https://boards.4chan.org/b/thread/123456#p123460") == \
        ("4chan", "b", "123456", "123460")
    assert parse("https://example.com/whatever") is None


def test_links_text_cleanup():
    from anonbrain.links import com_to_paras, md_to_paras
    paras = md_to_paras("**Bold** and [a link](http://x)\n\n> quoted\n\n&#x200B;\n---\n- item")
    assert [p.text for p in paras] == ["Bold and a link", "quoted", "• item"]
    assert paras[1].kind == "green"
    paras = com_to_paras('<a href="#p1" class="quotelink">&gt;&gt;123</a><br>&gt;be me<br>'
                         'plain text')
    assert [(p.kind, p.spoken) for p in paras] == [("quote", False), ("green", True),
                                                   ("text", True)]


def test_cleanup_table():
    from anonbrain.cleanup import CleanupTable
    t = CleanupTable()
    out = t.apply(">be me\n>tfw no gf")
    assert ">" not in out and "tfw" not in out.lower(), out


def test_automation_schedule():
    from anonbrain import automation as A
    assert A.parse_time("5:30 pm") == (17, 30)
    assert A.parse_time("25:00") is None
    cfg = A.config(_Settings({"automation": {"enabled": True, "times": ["17:00"],
                                             "filters": {"min_score": 7}}}))
    assert cfg["filters"]["min_score"] == 7 and cfg["filters"]["min_comments"] == 20
    store = A.Store(Path(_tmp()) / "automation.json")
    now = datetime(2026, 10, 28, 17, 20)        # a Wednesday
    assert A.due(cfg, store, now) == "2026-10-28 17:00"
    store.runs["2026-10-28 17:00"] = 1
    assert A.due(cfg, store, now) == ""
    assert A.next_run(cfg, now) == datetime(2026, 10, 29, 17, 0)


def test_automation_caption():
    from anonbrain import automation as A
    from anonbrain.reddit_source import Candidate
    import dataclasses
    fields = {f.name: f for f in dataclasses.fields(Candidate)}
    vals = {k: ("" if f.type in ("str", str) else 0) for k, f in fields.items()}
    vals.update(sub="Ask_Reddit", title="A title", author="me", score=1234, comments=56)
    c = Candidate(**vals)
    cfg = A.config(_Settings({}))
    cfg["caption"] = "{title} #{sub} {upvotes}"
    assert A.caption(cfg, c) == "A title #ask_reddit 1,234"


def test_captions_grouping():
    from anonbrain.captions import groups
    from anonbrain.voice import Word
    words = [Word(w, i * 0.3, i * 0.3 + 0.25) for i, w in
             enumerate("so I went to the store. then".split())]
    assert [[w.text for w in g] for g in groups(words, 3)] == \
        [["so", "I", "went"], ["to", "the", "store."], ["then"]]


def test_mirror_pattern():
    from anonbrain.engine import mirror_chain, mirror_spans
    spans = mirror_spans(30, seed=4)
    assert spans and all(1.5 <= b - a <= 3.5 or b == 30 for a, b in spans)
    assert all(spans[i][1] < spans[i + 1][0] for i in range(len(spans) - 1))
    assert "hflip" in mirror_chain("on", 10, 1, "a", "b")
    assert "null" in mirror_chain("off", 10, 1, "a", "b")


def test_versions():
    from anonbrain.updates import is_newer
    assert is_newer("1.0.1", "1.0.0") and is_newer("1.10.0", "1.9.9")
    assert not is_newer("1.0.0", "1.0.0") and not is_newer("0.9", "1.0.0")


def test_platform_fit():
    from anonbrain.platforms import check, speed_to_fit
    r = check(70, "9:16")
    assert any(p.key == "snapchat" for p in r["too_long"])
    assert any(p.key == "shorts" for p in check(30, "16:9")["wrong_shape"])
    assert speed_to_fit(200, 180, 180) is not None


def test_settings_save_and_reload():
    import time
    from anonbrain.settings import Settings
    path = Path(_tmp()) / "settings.json"
    s = Settings(path)
    for i in range(50):                      # a slider being dragged
        s["music_volume"] = i
    time.sleep(0.4)
    assert Settings(path)["music_volume"] == 49
    assert Settings(path)["fps"] == 30       # defaults fill in what was never saved


def test_presets_roundtrip():
    from anonbrain.presets import Presets, Values
    from anonbrain.settings import Settings
    s = Settings(Path(_tmp()) / "s.json")
    s["fps"] = 24
    s["mirror"] = "random"
    p = Presets()
    p.save("Movie clips", s)
    s["fps"] = 60
    assert p.apply("Movie clips", s) and s["fps"] == 24
    assert Values(s, {"fps": 30})["fps"] == 30 and Values(s, None)["mirror"] == "random"


def test_layout_math():
    from anonbrain import layout as L
    assert L.output_size("9:16", "1080p") == (1080, 1920)
    box = L.default_box("9:16", 1.2)
    x, y, w, h = L.place_post(1080, 1920, 1200, 1000, box)
    assert 0 <= x and x + w <= 1080 and 0 <= y and y + h <= 1920


def test_reveal_timing():
    from anonbrain.reveal import reveal_times, slide_plan
    from anonbrain.voice import estimate_words
    from tests.helpers import reddit_card
    _, pt = reddit_card()
    words = estimate_words(pt.text.replace("\n", " "))
    times = reveal_times(pt, words)
    spoken = [t for t in times if t is not None]
    assert spoken and spoken == sorted(spoken)
    assert slide_plan(pt, times)["moves"]


def test_library_never_repeats():
    import random
    from anonbrain.library import GameplayLibrary, LibraryExhausted
    from tests.helpers import gameplay
    lib = GameplayLibrary(Path(_tmp()) / "used.json")
    rng = random.Random(3)
    used = []
    try:
        for _ in range(20):
            seg = lib.pick([gameplay()], 1.0, rng)
            lib.mark_used(seg)
            used.append((seg.start, seg.start + seg.length))
    except LibraryExhausted:
        pass
    used.sort()
    assert len(used) >= 2
    assert all(a[1] <= b[0] + 1e-6 for a, b in zip(used, used[1:])), used


def test_library_allows_repeats():
    import random
    from anonbrain.library import GameplayLibrary, LibraryExhausted
    from tests.helpers import gameplay
    lib = GameplayLibrary(Path(_tmp()) / "used.json")
    rng = random.Random(5)
    seg = lib.pick([gameplay()], 5.5, rng)          # only 6 s are usable: one pick fits
    lib.mark_used(seg)
    try:
        lib.pick([gameplay()], 5.5, rng)
        raise AssertionError("should have run out")
    except LibraryExhausted:
        pass
    for _ in range(5):                               # repeats on: never runs out
        lib.mark_used(lib.pick([gameplay()], 5.5, rng, reuse=True))


def test_music_repeats_allowed():
    import random
    from anonbrain import music
    from tests.helpers import songs
    rng = random.Random(2)
    picks = [music.pick(songs(), 5, rng, repeats=True)[0].name for _ in range(40)]
    assert any(a == b for a, b in zip(picks, picks[1:])), picks


def test_history_and_duplicates():
    from anonbrain.history import History
    from tests.helpers import gameplay
    h = History()
    h.add(gameplay(), "So my roommate never paid a single bill", "", "", "", "", 0.0, 5.0)
    assert h.find_similar("So my roommate never paid a single bill!") is not None
    assert h.find_similar("A completely different story about a cat") is None


def test_fonts_lookup():
    from anonbrain import fonts
    from anonbrain.captions import sample_image
    idx = fonts.index()
    if idx:                                 # any font on this PC
        fam = next(v[0] for v in idx.values() if v[0])
        assert fonts.find(fam) is not None
    img, h = sample_image({"font": "No Such Font Anywhere"}, 1080, 1920)
    assert img.getbbox() is not None and h > 0


def test_music_folder_picks():
    import random
    from anonbrain import music
    from tests.helpers import songs
    found = music.find_songs(songs())
    assert sorted(p.name for p in found) == ["one.mp3", "short.mp3", "three.wav", "two.m4a"]
    assert music.random_start(10, 30) == 0.0              # short song: from the top
    rng = random.Random(1)
    for _ in range(50):
        start = music.random_start(120, 30, rng)
        assert 0 <= start <= 120 - 30 - music.END_ROOM
    picks = [music.pick(songs(), 12, rng)[0].name for _ in range(12)]
    assert all(a != b for a, b in zip(picks, picks[1:])), picks     # never twice in a row
    assert len(set(picks[:4])) == 4, picks                          # all used before repeats
    song, start = music.pick(songs(), 12, rng)
    from anonbrain.engine import get_duration
    assert start == 0.0 or start + 12 + music.END_ROOM <= get_duration(song)


# --- small helpers -------------------------------------------------------------------
class _Settings:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, k):
        return self.values.get(k)


def _tmp() -> str:
    import tempfile
    from tests.helpers import WORK
    return tempfile.mkdtemp(dir=WORK)
