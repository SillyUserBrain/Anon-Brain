"""One call that makes a finished video from the wizard's choices."""

import re
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from .cleanup import CleanupTable
from .engine import EngineError, render
from .layout import default_box, output_size
from .library import GameplayLibrary, LibraryExhausted, Segment, find_videos
from .ocr import PostText
from .reveal import build_frames, reveal_times, slide_plan
from .voice import NO_VOICE, Narration, Word, narrate

LEAD_IN = 0.4   # seconds of gameplay before the voice starts
TAIL = 1.2      # seconds after the voice ends
PART_LEAD = 0.45   # in a thread: each later post shows this long before its voice
PART_GAP = 0.4     # ...and stays this long after
CARD_IN = 0.3      # later posts fade in over this long


@dataclass
class Part:
    """One more post in a thread (the first post lives on the Job itself)."""
    image: str
    text: str
    post_text: PostText | None = None
    voice_id: str = ""            # "" = the main voice


@dataclass
class Job:
    gameplay_mode: str            # "file" or "folder"
    gameplay_path: str
    post_image: str
    text: str                     # what's in the text box
    post_text: PostText | None    # OCR result for this image (for the reveal)
    voice_id: str = NO_VOICE
    line_pause: float = 0.35      # seconds of silence between lines
    voice_model: str = "eleven_multilingual_v2"
    voice_volume: int = 100       # percent
    music_path: str = ""
    music_volume: int = 20        # percent
    music_start: float = 0.0      # seconds into the song to start from
    music_folder: str = ""        # a folder of songs: each video picks one, from a random part
    reveal: bool = True
    reveal_style: str = "fade"    # "fade" (lines fade in) or "slide" (crop glides down)
    output_dir: str = ""
    hook: str = ""                # big title text for the first seconds
    hook_spoken: bool = False     # also read the hook aloud first
    hook_color: str = "#8fc43f"
    skip_boring: bool = True      # avoid menus / loading screens in the footage
    reuse_footage: bool = False   # pick from anywhere, even parts already used
    repeat_songs: bool = False    # music folder: any song, even one that just played
    fmt: str = "9:16"             # shape of the video (see layout.py)
    resolution: str = "1080p"
    post_box: dict | None = None  # where the post sits; None = the default spot
    post_round: float = 0.0       # corner rounding: 0 = square .. 1 = oval / circle
    shadow: float = 0.0           # drop shadow strength 0..1 (0 = none)
    border: float = 0.0           # border thickness, pixels at 1080p (0 = none)
    border_style: str = "solid"   # "solid" or an animated style (layout.BORDER_STYLES)
    border_color: str = "#ffffff"
    border_colors: list = field(default_factory=list)   # the app's 3 colors, for animations
    parts: list = field(default_factory=list)   # more posts after this one (a thread)
    brand: dict | None = None     # watermark / end card overlays (rendered by the app)
    voice_speed: float = 1.0      # 1.0 = normal, 1.2 = 20% faster
    encoder: str = "auto"         # auto / nvidia / amd / intel / cpu (see encoders.py)
    min_length: float = 0.0       # seconds; shorter videos keep going (gameplay + music)
    fps: int = 30                 # frames per second: 24 (film), 30 or 60
    mirror: str = "off"           # "off", "on" or "random" (flips back and forth)
    fit: str = "fill"             # "fill" (crop to fill) or "blur" (whole video, blurred behind)
    clip_only: bool = False       # no post, no voice: just the video (movie clips)
    game_volume: int = 0          # the video's own sound, percent (0 = off)
    post_display: str = "post"    # "post", "intro" (post, then captions) or "captions"
    captions: dict | None = None  # caption look (captions.DEFAULT_STYLE fields)


def gameplay_videos(job: Job) -> list[Path]:
    if job.gameplay_mode == "folder":
        vids = find_videos(Path(job.gameplay_path))
        if not vids:
            raise EngineError("No videos found in your gameplay folder.")
        return vids
    p = Path(job.gameplay_path)
    if not p.is_file():
        raise EngineError("Pick a gameplay video first.")
    return [p]


def output_name(text: str) -> str:
    words = re.sub(r"[^A-Za-z0-9]+", " ", text).split()[:5]
    slug = "_".join(words).lower() or "video"
    return f"{slug}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"


def spoken_text(job: Job, cleanup: CleanupTable) -> str:
    """Exactly what the voice reads (the hook first, if it's read aloud)."""
    body = cleanup.apply(job.text)
    if job.hook.strip() and job.hook_spoken:
        return cleanup.apply(job.hook.strip()) + "\n" + body
    return body


@dataclass
class Made:
    path: Path
    segment: Segment
    duration: float
    song: tuple | None = None     # (song, start) the music came from, if any


def _visuals(job: Job, image: str, post_text, narration: Narration, lead: float, tmp: Path,
             status) -> tuple[list, dict | None]:
    """Reveal frames (fade) or a slide plan for one post."""
    frames, slide = [(Path(image), 0.0)], None
    if job.reveal and post_text and any(l.narrated for l in post_text.lines):
        status("Setting up the line reveal...")
        times = reveal_times(post_text, narration.words)
        if job.reveal_style == "slide":
            slide = slide_plan(post_text, times, offset=lead)
        else:
            frames = build_frames(Path(image), post_text, times, tmp, offset=lead)
    return frames, slide


def _caption_plan(job: Job, narration: Narration, lead: float, first: bool,
                  hook_until: float, cleanup: CleanupTable) -> dict:
    """Whether the post shows, until when, and the captions (render() arguments)."""
    mode = job.post_display if job.post_display in ("intro", "captions") else "post"
    if mode == "post" or not narration.words:
        return {"show_post": True, "post_until": None, "captions": None}
    has_hook = first and bool(job.hook.strip())
    after = hook_until if has_hook else 0.0          # captions wait for the hook card
    show, until = mode == "intro" and first, None
    if show:
        skip = 0
        if has_hook and job.hook_spoken:
            skip = len([l for l in cleanup.apply(job.hook.strip()).splitlines() if l.strip()])
        spans = narration.lines
        if len(spans) <= skip + 1:      # nothing after the title: keep the post up
            return {"show_post": True, "post_until": None, "captions": None}
        until = max(spans[skip][1] + lead + 0.25, after, 2.0)
        after = until - 0.3
    words = [Word(w.text, w.start + lead, w.end + lead) for w in narration.words
             if w.start + lead >= after - 0.02]
    plan = {"show_post": show, "post_until": until,
            "captions": {"words": words, "style": dict(job.captions or {})}}
    if show:
        plan["body_from"] = spans[skip + 1][0]      # narration time the story starts
    return plan


def _title_card(image: str, post_text, words, body_from: float, out: Path) -> Path | None:
    """The post with its story lines cut out (just the header, title and footer),
    for "post first, then captions". None = keep the whole post."""
    if not post_text or not post_text.lines:
        return None
    times = reveal_times(post_text, words)
    lines = [(l, t) for l, t in zip(post_text.lines, times) if t is not None]
    body = [l for l, t in lines if t >= body_from - 0.05]
    title = [l for l, t in lines if t < body_from - 0.05]
    if not body or not title:
        return None
    from PIL import Image
    with Image.open(image) as im:
        im = im.convert("RGB")
        title_bottom = max(l.bottom for l in title)
        top = int((title_bottom + min(l.top for l in body)) / 2)
        top = max(top, title_bottom + 2)
        bottom = min(im.height, max(l.bottom for l in body) + 4)
        below = [l.top for l in post_text.lines if l.top >= bottom - 2]
        if below:      # leave the same room above the footer as above the story
            bottom = min(bottom + max(0, (min(below) - bottom) // 2), min(below) - 2)
        if bottom - top < 8 or top >= im.height:
            return None
        card = Image.new("RGB", (im.width, im.height - (bottom - top)))
        card.paste(im.crop((0, 0, im.width, top)), (0, 0))
        card.paste(im.crop((0, bottom, im.width, im.height)), (0, top))
        card.save(out)
    return out


def _box(job: Job, image: str) -> dict:
    if job.post_box:
        return job.post_box
    from PIL import Image
    with Image.open(image) as im:
        return default_box(job.fmt, im.width / im.height)


def _brand(job: Job, end_at: float) -> dict | None:
    if not job.brand:
        return None
    b = {k: dict(v) for k, v in job.brand.items() if v}
    if "endcard" in b:
        b["endcard"]["start"] = end_at
    return b or None


def _pad(job: Job, natural: float) -> float:
    """Extra seconds after the story so the video is at least job.min_length long."""
    return max(0.0, float(job.min_length or 0) - natural)


def _endcard_at(job: Job, voice_end: float, length: float, pad: float) -> float:
    """When the end card starts: right after the voice, or at the very end if the
    video was stretched with extra gameplay."""
    end = (job.brand or {}).get("endcard")
    if not end or pad <= 0:
        return voice_end + 0.3
    return max(voice_end + 0.3, length - end["len"] - 0.3)


def _tail(job: Job) -> float:
    end = (job.brand or {}).get("endcard")
    return max(TAIL, 0.3 + end["len"]) if end else TAIL


def _encoder(job: Job, status) -> str:
    from .encoders import detect, resolve
    if job.encoder != "cpu" and not getattr(_encoder, "_checked", False):
        status("Checking your graphics card...", 0.11)
        detect()
        _encoder._checked = True
    return resolve(job.encoder or "auto")


def _style(job: Job) -> dict:
    return dict(post_round=job.post_round, shadow=job.shadow, border=job.border,
                border_style=job.border_style, border_color=job.border_color,
                border_colors=job.border_colors)


def _picture(job: Job, seed: int = 0) -> dict:
    """Frame rate, mirroring, fit and the video's own sound (render() arguments)."""
    import random
    fps = job.fps if job.fps in (24, 30, 60) else 30
    return dict(fps=fps, mirror=job.mirror if job.mirror in ("on", "random") else "off",
                fit="blur" if job.fit == "blur" else "fill",
                mirror_seed=seed or random.randrange(1, 10 ** 6),
                keep_game_audio=job.game_volume > 0, game_volume=job.game_volume / 100)


def make_video(job: Job, cleanup: CleanupTable, library: GameplayLibrary,
               status: Callable[[str, float], None] = lambda s, f: None,
               narration: Narration | None = None, segment: Segment | None = None,
               preview: bool = False, history=None, song: tuple | None = None) -> Made:
    """status(message, fraction 0..1) is called as the video is made.

    preview=True makes a quick, small 6-second clip (nothing is marked as
    used); pass its segment and song back in to render the real video on the
    same footage and music."""
    if job.clip_only:
        return _make_clip(job, library, status, segment, preview, history, song)
    if job.parts and not preview:
        return _make_thread(job, cleanup, library, status, segment, history, song)
    status("Preparing the voice...", 0.02)
    if narration is None:
        narration = narrate(spoken_text(job, cleanup), job.voice_id, job.voice_model,
                            job.line_pause, lambda m, f: status(m, 0.02 + 0.06 * f),
                            speed=job.voice_speed)
    duration = LEAD_IN + narration.length + _tail(job)
    pad = _pad(job, duration)
    duration += pad
    seg = segment or _pick(job, library, duration, status)
    job = _with_song(job, duration, status, song, remember=not preview)

    # how long the hook card stays up
    hook_until = 2.8
    if job.hook.strip() and job.hook_spoken:
        n = len(cleanup.apply(job.hook).split())
        if n < len(narration.words):
            hook_until = max(1.2, narration.words[n].start + LEAD_IN - 0.1)

    plan = _caption_plan(job, narration, LEAD_IN, True, hook_until, cleanup)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        image = job.post_image
        if "body_from" in plan:
            image = str(_title_card(image, job.post_text, narration.words,
                                    plan.pop("body_from"), tmp / "title.png") or image)
            frames, slide = [(Path(image), 0.0)], None
        elif plan["show_post"]:
            frames, slide = _visuals(job, image, job.post_text, narration, LEAD_IN, tmp,
                                     lambda m: status(m, 0.1))
        else:
            frames, slide = [(Path(image), 0.0)], None
        if plan["captions"]:
            status("Setting up the captions...", 0.1)
        hook_img = None
        if job.hook.strip():
            from .hook import render_hook
            hook_img = render_hook(job.hook, tmp / "hook.png", job.hook_color)

        size = output_size(job.fmt, job.resolution)
        if preview:
            from .settings import cache_dir
            out = cache_dir() / "preview.mp4"
            length = min(duration, 6.0)
        else:
            out = Path(job.output_dir) / output_name(job.hook or job.text)
            length = duration
        render(seg.path, frames, out, duration=length, start=seg.start,
               voice=narration.audio, voice_delay=LEAD_IN,
               voice_volume=job.voice_volume / 100,
               music=Path(job.music_path) if job.music_path else None,
               music_volume=job.music_volume / 100, music_start=job.music_start,
               hook=hook_img, hook_until=hook_until,
               size=size, post_box=_box(job, image), **_style(job),
               slide=slide, brand=_brand(job, _endcard_at(job, LEAD_IN + narration.length,
                                                          duration, pad)),
               **plan,
               encoder=_encoder(job, status), **_picture(job),
               scale=540 / min(size) if preview else 1.0, fast=preview,
               progress=lambda f: status("Rendering preview..." if preview else "Rendering video...",
                                         0.12 + 0.88 * f))

    if not preview:
        if seg.start is not None:
            library.mark_used(seg)
        if history is not None:
            status("Saving to history...", 0.99)
            history.add(out, job.text, job.post_image, job.hook, job.voice_id,
                        str(seg.path), seg.start, duration)
    status("Done!", 1.0)
    return Made(out, seg, duration, _song_of(job))


def _with_song(job: Job, length: float, status, song=None, remember=True) -> Job:
    """The job with its music settled. A folder of songs means a random song, from a
    random part (or the one a preview already picked)."""
    from . import music
    if song:
        if job.music_folder and remember:
            music.remember(song[0])
        return replace(job, music_path=str(song[0]), music_start=float(song[1]))
    if not job.music_folder:
        return job
    status("Choosing the music...", 0.09)
    path, start = music.pick(job.music_folder, length, record=remember,
                             repeats=job.repeat_songs)
    return replace(job, music_path=str(path), music_start=start)


def _song_of(job: Job):
    return (job.music_path, job.music_start) if job.music_path else None


def _pick(job: Job, library: GameplayLibrary, duration: float, status) -> Segment:
    status("Choosing gameplay...", 0.08)
    videos = gameplay_videos(job)
    try:
        return library.pick(videos, duration, avoid_boring=job.skip_boring,
                            status=lambda m: status(m, 0.09), reuse=job.reuse_footage)
    except LibraryExhausted:
        if job.gameplay_mode == "file":
            return Segment(videos[0], None, duration)   # single clip: allow reuse
        raise


def _make_clip(job: Job, library: GameplayLibrary, status, segment: Segment | None,
               preview: bool, history, song=None) -> Made:
    """Just the video (a movie clip, say): no post, no voice. Its own sound, music,
    a hook, your handle and the end card are all optional."""
    import random

    from .engine import get_duration
    status("Getting the clip ready...", 0.05)
    if segment is not None:
        clip, start = segment.path, segment.start or 0.0
    else:
        videos = gameplay_videos(job)
        clip, start = (videos[0] if job.gameplay_mode == "file" else random.choice(videos)), 0.0
    length = max(get_duration(clip) - start, 0.5)
    length = max(length, float(job.min_length or 0))      # shorter clips loop
    seg = Segment(clip, start, length)
    job = _with_song(job, length, status, song, remember=not preview)
    size = output_size(job.fmt, job.resolution)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        hook_img = None
        if job.hook.strip():
            from .hook import render_hook
            hook_img = render_hook(job.hook, tmp / "hook.png", job.hook_color)
        if preview:
            from .settings import cache_dir
            out, dur = cache_dir() / "preview.mp4", min(length, 6.0)
        else:
            out, dur = Path(job.output_dir) / output_name(job.hook or clip.stem), length
        end = (job.brand or {}).get("endcard")
        brand = _brand(job, max(0.0, length - end["len"] - 0.3) if end else 0.0)
        render(clip, None, out, duration=dur, start=start, show_post=False,
               music=Path(job.music_path) if job.music_path else None,
               music_volume=job.music_volume / 100, music_start=job.music_start,
               hook=hook_img, hook_until=2.8, size=size, brand=brand,
               encoder=_encoder(job, status), **_picture(job),
               scale=540 / min(size) if preview else 1.0, fast=preview,
               progress=lambda f: status("Rendering preview..." if preview else
                                         "Rendering video...", 0.1 + 0.9 * f))
    if not preview and history is not None:
        status("Saving to history...", 0.99)
        history.add(out, job.hook or clip.stem, "", job.hook, "", str(clip), start, length)
    status("Done!", 1.0)
    return Made(out, seg, dur, _song_of(job))


@dataclass
class LengthGuess:
    seconds: float      # the whole video (including any padding to the minimum)
    voice: float        # of which the voice is actually talking (what speed changes)
    exact: bool         # False = estimated (ElevenLabs voice not made yet)
    padded: float = 0.0  # extra gameplay + music added to reach the minimum length


def predict_length(job: Job, cleanup: CleanupTable,
                   status: Callable[[str, float], None] = lambda m, f: None) -> LengthGuess:
    """How long the video will be. Voices that run on your PC are made for real
    (and cached, so rendering later is quicker); ElevenLabs voices are only
    estimated unless they were made before, so this never spends credits."""
    from .voice import estimate_length, is_cached, is_paid
    if job.clip_only:
        from .engine import get_duration
        videos = gameplay_videos(job)
        secs = get_duration(videos[0])
        pad = max(0.0, float(job.min_length or 0) - secs)
        return LengthGuess(secs + pad, 0.0, job.gameplay_mode == "file" or len(videos) == 1, pad)
    posts = [Part(job.post_image, job.text, job.post_text, job.voice_id)] + list(job.parts)
    total, talk, exact = 0.0, 0.0, True
    n = len(posts)
    for i, p in enumerate(posts):
        text = cleanup.apply(p.text)
        if i == 0 and job.hook.strip() and job.hook_spoken:
            text = cleanup.apply(job.hook.strip()) + "\n" + text
        if not text.strip():
            continue
        voice = p.voice_id or job.voice_id
        lines = [l for l in text.splitlines() if l.strip()]
        pauses = job.line_pause * max(0, len(lines) - 1)
        if is_paid(voice) and not is_cached(text, voice, job.voice_model):
            length, spoken = estimate_length(text, job.line_pause, job.voice_speed)
            exact = False
        else:
            nr = narrate(text, voice, job.voice_model, job.line_pause,
                         lambda m, f, i=i: status(m, (i + f) / n), speed=job.voice_speed)
            length, spoken = nr.length, max(0.0, nr.length - pauses)
        lead = LEAD_IN if i == 0 else PART_LEAD
        after = _tail(job) if i == n - 1 else PART_GAP
        total += lead + length + after
        talk += spoken
    pad = _pad(job, total)
    return LengthGuess(total + pad, talk, exact, pad)


def narrate_thread(job: Job, cleanup: CleanupTable,
                   status: Callable[[str, float], None] = lambda m, f: None) -> Narration:
    """Every post's voice joined, with the gaps the video will have (for previews)."""
    from .engine import get_duration
    from .settings import cache_dir
    from .voice import _join_audio, _tag
    posts = [Part(job.post_image, job.text, job.post_text, job.voice_id)] + list(job.parts)
    narrs = []
    for i, p in enumerate(posts):
        text = cleanup.apply(p.text)
        if i == 0 and job.hook.strip() and job.hook_spoken:
            text = cleanup.apply(job.hook.strip()) + "\n" + text
        narrs.append(narrate(text, p.voice_id or job.voice_id, job.voice_model,
                             job.line_pause, lambda m, f, i=i: status(
                                 f"Post {i + 1} of {len(posts)}: {m}", (i + f) / len(posts)),
                             speed=job.voice_speed))
    audio = [n.audio for n in narrs if n.audio]
    if not audio:
        return Narration(None, [], sum(n.length for n in narrs))
    out = cache_dir() / f"{_tag('thread', *[str(a) for a in audio])}.wav"
    if not out.exists():
        _join_audio(audio, PART_GAP + PART_LEAD, out)
    return Narration(out, [], get_duration(out))


def _make_thread(job: Job, cleanup: CleanupTable, library: GameplayLibrary, status,
                 segment: Segment | None, history, song=None) -> Made:
    """Several posts, one after another, over one stretch of gameplay. Each post
    is rendered on its own (with its own voice), then they're joined and the
    music goes over the whole video."""
    from .engine import _tool, get_duration, has_audio, pick_start, run_tool
    posts = [Part(job.post_image, job.text, job.post_text, job.voice_id)] + list(job.parts)
    n = len(posts)

    # voices first: they decide how long everything is
    narrs = []
    for i, p in enumerate(posts):
        text = cleanup.apply(p.text)
        if i == 0 and job.hook.strip() and job.hook_spoken:
            text = cleanup.apply(job.hook.strip()) + "\n" + text
        voice = p.voice_id or job.voice_id
        narrs.append(narrate(text, voice, job.voice_model, job.line_pause,
                             lambda m, f, i=i: status(f"Post {i + 1} of {n}: {m}",
                                                      0.02 + 0.08 * (i + f) / n),
                             speed=job.voice_speed))
    leads = [LEAD_IN] + [PART_LEAD] * (n - 1)
    lengths = [leads[i] + narrs[i].length + (PART_GAP if i < n - 1 else _tail(job))
               for i in range(n)]
    pad = _pad(job, sum(lengths))
    lengths[-1] += pad                  # the last post stays up while the gameplay goes on
    total = sum(lengths)
    seg = segment or _pick(job, library, total, status)
    job = _with_song(job, total, status, song)
    clip = get_duration(seg.path)
    start0 = seg.start if seg.start is not None else pick_start(clip, total)

    size = output_size(job.fmt, job.resolution)
    hook_until = 2.8
    if job.hook.strip() and job.hook_spoken:
        k = len(cleanup.apply(job.hook).split())
        if k < len(narrs[0].words):
            hook_until = max(1.2, narrs[0].words[k].start + LEAD_IN - 0.1)

    out = Path(job.output_dir) / output_name(job.hook or job.text)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pieces, t = [], 0.0
        enc = _encoder(job, status)
        used = set()
        pic = _picture(job)
        for i, p in enumerate(posts):
            ptmp = tmp / f"p{i}"
            ptmp.mkdir()
            plan = _caption_plan(job, narrs[i], leads[i], i == 0, hook_until, cleanup)
            image = p.image
            if "body_from" in plan:
                image = str(_title_card(image, p.post_text, narrs[i].words,
                                        plan.pop("body_from"), ptmp / "title.png") or image)
                frames, slide = [(Path(image), 0.0)], None
            elif plan["show_post"]:
                frames, slide = _visuals(job, image, p.post_text, narrs[i], leads[i], ptmp,
                                         lambda m: None)
            else:
                frames, slide = [(Path(image), 0.0)], None
            hook_img = None
            if i == 0 and job.hook.strip():
                from .hook import render_hook
                hook_img = render_hook(job.hook, ptmp / "hook.png", job.hook_color)
            last = i == n - 1
            brand = _brand(job, _endcard_at(job, leads[i] + narrs[i].length, lengths[i],
                                            pad if last else 0.0))
            if brand and not last:
                brand.pop("endcard", None)
            start = (start0 + t) % clip if clip > 0 else 0.0
            piece = ptmp / "piece.mp4"
            base = 0.12 + 0.8 * t / total
            span = 0.8 * lengths[i] / total
            render(seg.path, frames, piece, duration=lengths[i], start=start,
                   voice=narrs[i].audio, voice_delay=leads[i],
                   voice_volume=job.voice_volume / 100,
                   hook=hook_img, hook_until=hook_until,
                   size=size, post_box=_box(job, image), **_style(job),
                   slide=slide, brand=brand, card_in=CARD_IN if i else 0.0, **plan,
                   encoder=enc, **{**pic, "mirror_seed": pic["mirror_seed"] + i},
                   progress=lambda f, b=base, s=span, i=i: status(
                       f"Rendering post {i + 1} of {n}...", b + s * f))
            pieces.append(piece)
            from . import engine as _engine
            if _engine.LAST_ENCODER != enc:     # the card gave up: keep the rest the same
                used.add(_engine.LAST_ENCODER)
                enc = _engine.LAST_ENCODER
            used.add(enc)
            t += lengths[i]

        status("Joining the posts...", 0.93)
        lst = tmp / "pieces.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in pieces), encoding="utf-8")
        joined = tmp / "joined.mp4"
        # pieces from different encoders can't simply be glued: re-encode them then
        from .encoders import video_args
        vcodec = ["-c", "copy"] if len(used) <= 1 else [*video_args("cpu"), "-c:a", "copy"]
        r = run_tool([_tool("ffmpeg"), "-y", "-loglevel", "error", "-f", "concat",
                      "-safe", "0", "-i", lst, *vcodec, joined])
        if r.returncode != 0:
            raise EngineError("Couldn't join the posts:\n" + r.stderr[-800:])
        out.parent.mkdir(parents=True, exist_ok=True)
        # (the pieces may carry the voice, the gameplay's own sound, or both)
        has_voice = has_audio(joined)
        cmd = [_tool("ffmpeg"), "-y", "-loglevel", "error", "-i", str(joined)]
        if job.music_path:
            status("Adding the music...", 0.96)
            fade = max(total - 1.5, 0)
            cmd += ["-stream_loop", "-1", "-ss", f"{job.music_start:.2f}", "-i", job.music_path]
            mus = (f"[1:a]volume={job.music_volume / 100:.3f},atrim=0:{total:.3f},"
                   f"afade=t=out:st={fade:.2f}:d=1.5,aresample=44100,"
                   f"aformat=channel_layouts=stereo")
            from .engine import LIMITER
            graph = (mus + "[m];[0:a]apad[va];[va][m]amix=inputs=2:normalize=0:"
                     f"duration=shortest,{LIMITER}[a]"
                     if has_voice else mus + "[a]")
            cmd += ["-filter_complex", graph, "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-c", "copy"]
        cmd += ["-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
        r = run_tool(cmd)
        if r.returncode != 0:
            raise EngineError("Couldn't finish the video:\n" + r.stderr[-800:])

    if seg.start is not None:
        library.mark_used(seg)
    if history is not None:
        status("Saving to history...", 0.99)
        history.add(out, "\n\n".join(p.text for p in posts), job.post_image, job.hook,
                    job.voice_id, str(seg.path), seg.start, total)
    status("Done!", 1.0)
    return Made(out, seg, total, _song_of(job))
