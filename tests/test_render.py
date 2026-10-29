"""Real renders, checked for length, frame rate, size and sound.

They use the "No voice" option (silent, timed like speech) so no internet or keys are
needed, and 720p so they finish in a few minutes even on a slow PC."""

from pathlib import Path

from tests.helpers import WORK, gameplay, movie, music, probe, reddit_card


def _job(**kw):
    from anonbrain.pipeline import Job
    from anonbrain.voice import NO_VOICE
    png, pt = reddit_card()
    text = "AITA for testing everything?\nMy roommate never runs the tests.\n" \
           "So I made the app run them by itself."
    out = WORK / "out"
    out.mkdir(exist_ok=True)
    job = Job("file", str(gameplay()), png, text, pt, voice_id=NO_VOICE,
              output_dir=str(out), resolution="720p", encoder="cpu")
    for k, v in kw.items():
        setattr(job, k, v)
    return job


def _make(job, **kw):
    from anonbrain.cleanup import CleanupTable
    from anonbrain.library import GameplayLibrary
    lib = GameplayLibrary(WORK / f"used_{id(job)}.json")
    from anonbrain.pipeline import make_video
    made = make_video(job, CleanupTable(), lib, **kw)
    assert Path(made.path).is_file() and Path(made.path).stat().st_size > 10_000
    return made, probe(made.path)


def _check(info, made, fps, size=(720, 1280), audio=True):
    assert abs(info["fps"] - fps) < 0.01, info
    assert (info["width"], info["height"]) == size, info
    assert abs(info["duration"] - made.duration) < 0.5, (info, made.duration)
    assert info["audio"] == audio, info


def test_post_fade():
    made, info = _make(_job(music_path=str(music())))
    _check(info, made, 30)
    assert 4 < made.duration < 20


def test_post_slide_60fps():
    made, info = _make(_job(reveal_style="slide", fps=60, border=6, border_style="spin",
                            post_round=0.2, shadow=0.5))
    _check(info, made, 60, audio=False)     # no voice, music or game sound: silent


def test_captions_mirrored():
    made, info = _make(_job(post_display="captions", mirror="on",
                            captions={"words": 2, "highlight": "box"}))
    _check(info, made, 30, audio=False)


def test_intro_then_captions():
    made, info = _make(_job(post_display="intro", hook="Testing day", hook_spoken=True, game_volume=40))
    _check(info, made, 30)


def test_thread():
    from anonbrain.pipeline import Part
    png, pt = reddit_card()
    made, info = _make(_job(parts=[Part(png, "And then it worked.", pt)],
                            music_path=str(music()), game_volume=30))
    _check(info, made, 30)


def test_movie_clip_24fps_blur_random_mirror():
    made, info = _make(_job(gameplay_path=str(movie()), clip_only=True, fps=24, fit="blur",
                            mirror="random", game_volume=100))
    _check(info, made, 24)
    assert abs(made.duration - 6) < 0.5


def test_movie_clip_wide_shape_60fps():
    made, info = _make(_job(gameplay_path=str(movie()), clip_only=True, fps=60,
                            fmt="16:9", game_volume=80))
    _check(info, made, 60, size=(1280, 720))


def test_music_folder_and_preview_keeps_song():
    from tests.helpers import songs
    job = _job(music_folder=str(songs()), music_volume=60)
    preview, _ = _make(job, preview=True)
    assert preview.song and Path(preview.song[0]).parent.name in ("songs", "more")
    made, info = _make(job, segment=preview.segment, song=preview.song)
    _check(info, made, 30)
    assert made.song == preview.song                 # the real video uses the previewed song
    again, _ = _make(job)
    assert again.song and again.song[0] != made.song[0]     # it counted as played


def test_preview():
    made, info = _make(_job(), preview=True)
    assert info["duration"] <= 6.5 and min(info["width"], info["height"]) == 540, info
