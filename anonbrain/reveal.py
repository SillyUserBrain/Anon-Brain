"""Line-by-line reveal.

Each line of the post stays hidden (painted over with the post's own
background colour) until the narrator reaches it. The header, name, date
and thumbnail stay visible the whole time, so the post keeps its shape.

Timing comes from matching the words in each screenshot line to the words
in the narration. Lines that can't be matched (e.g. edited in the text box
or expanded shorthand) borrow the timing of the line before them.
"""

import re
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .ocr import PostText
from .voice import Word


def _norm(text: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", text.lower()).split() if w]


def reveal_times(post: PostText, words: list[Word]) -> list[float | None]:
    """Seconds into the narration when each OCR line should appear.
    None = always visible (header lines)."""
    ocr_tokens, owner = [], []
    for i, line in enumerate(post.lines):
        if line.narrated:
            for t in _norm(line.text):
                ocr_tokens.append(t)
                owner.append(i)

    narr_tokens, narr_times = [], []
    for w in words:
        for t in _norm(w.text):
            narr_tokens.append(t)
            narr_times.append(w.start)

    first_time: dict[int, float] = {}
    sm = SequenceMatcher(None, ocr_tokens, narr_tokens, autojunk=False)
    for block in sm.get_matching_blocks():
        for k in range(block.size):
            line = owner[block.a + k]
            t = narr_times[block.b + k]
            first_time[line] = min(first_time.get(line, t), t)

    times, prev = [], 0.0
    for i, line in enumerate(post.lines):
        if not line.narrated:
            times.append(None)
            continue
        t = first_time.get(i, prev)
        t = max(t, prev)          # never reveal out of order
        times.append(t)
        prev = t
    return times


def _bg_colour(arr: np.ndarray, box) -> tuple:
    """Median colour of a thin ring around the text box = the post background."""
    h, w = arr.shape[:2]
    l, t, r, b = box
    pad = 5
    L, T, R, B = max(0, l - pad), max(0, t - pad), min(w, r + pad), min(h, b + pad)
    region = arr[T:B, L:R].reshape(-1, arr.shape[2])
    mask = np.ones((B - T, R - L), bool)
    mask[t - T + 2: b - T - 2, l - L + 2: r - L - 2] = False
    ring = region[mask.reshape(-1)]
    if len(ring) == 0:
        ring = region
    return tuple(int(v) for v in np.median(ring, axis=0))


# How the reveal feels. Lines are always fully shown a moment BEFORE the
# narrator says them, never after.
FADE = 0.28          # seconds each line takes to fade in
FADE_EARLY = 0.08    # ...finishing this long before its first word
SLIDE = 0.55         # seconds the crop takes to glide down to the next line
SLIDE_EARLY = 0.05   # ...arriving this long before the line's first word
FPS = 30


def _hidden_boxes(post: PostText, times, arr) -> list[tuple[float, tuple, tuple]]:
    h, w = arr.shape[:2]
    hidden = []  # (time, box, colour)
    for line, t in zip(post.lines, times):
        if t is None:
            continue
        box = (max(0, line.left - 3), max(0, line.top - 3),
               min(w, line.right + 3), min(h, line.bottom + 3))
        hidden.append((t, box, _bg_colour(arr, box)))
    return hidden


def build_frames(image: Path, post: PostText, times: list[float | None],
                 out_dir: Path, offset: float = 0.0) -> list[tuple[Path, float]]:
    """Images of the post as its lines fade in: [(png, start_time), ...].

    Each hidden line is painted over with the post's own background colour;
    the paint fades away over FADE seconds, finishing just before the line
    is read."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Image.open(image).convert("RGB")
    arr = np.asarray(base)
    hidden = _hidden_boxes(post, times, arr)
    if not hidden:
        path = out_dir / "reveal_000.png"
        base.save(path)
        return [(path, 0.0)]

    # when each line is fully visible (video time)
    done = [max(0.0, t + offset - FADE_EARLY) for t, _, _ in hidden]
    # frames: one still between fades, plus one per video frame during a fade
    moments = {0.0}
    for d in done:
        start = max(0.0, d - FADE)
        k = 0
        while start + k / FPS < d:
            moments.add(round(start + k / FPS, 4))
            k += 1
        moments.add(round(d, 4))
    moments = sorted(moments)

    covers = Image.new("RGBA", base.size, (0, 0, 0, 0))
    frames, last_key = [], None
    for m in moments:
        amounts = []
        for (t, box, colour), d in zip(hidden, done):
            a = 1.0 if m <= d - FADE else 0.0 if m >= d else (d - m) / FADE
            a = a * a * (3 - 2 * a)                     # smooth start and finish
            amounts.append(round(a, 3))
        key = tuple(amounts)
        if key == last_key:
            continue
        last_key = key
        layer = covers.copy()
        draw = ImageDraw.Draw(layer)
        for (t, box, colour), a in zip(hidden, amounts):
            if a > 0:
                draw.rectangle(box, fill=colour + (int(255 * a),))
        img = Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")
        path = out_dir / f"reveal_{len(frames):03d}.png"
        img.save(path, compress_level=1)
        frames.append((path, m))
    frames[0] = (frames[0][0], 0.0)
    return frames


def slide_plan(post: PostText, times: list[float | None], offset: float = 0.0) -> dict:
    """For the slide-down reveal: where the crop starts and each glide down.

    Returns {"start": y, "moves": [(begin, seconds, y), ...]} with y in the
    screenshot's pixels (the crop's bottom edge) and times in video seconds."""
    spoken = [(t, l) for l, t in zip(post.lines, times) if t is not None]
    if not spoken:
        return {"start": None, "moves": []}
    start = max(0, min(l.top for _, l in spoken) - 4)
    tops = sorted(l.top for l in post.lines)

    def stop_below(bottom: int) -> float:
        """Halfway between this line and whatever starts below it."""
        below = [t for t in tops if t > bottom - 2]
        return (bottom + below[0]) / 2 if below and below[0] - bottom < 24 else bottom + 6

    # lines that appear together go down together, to the lowest of them
    steps: dict[float, float] = {}
    for t, l in spoken:
        steps[t] = max(steps.get(t, 0), stop_below(l.bottom))
    moves, y, free_at = [], start, 0.0
    for t in sorted(steps):
        target = max(steps[t], y)
        if target <= y:
            continue
        arrive = max(0.05, t + offset - SLIDE_EARLY)
        begin = max(free_at, arrive - SLIDE)
        length = max(0.12, arrive - begin)
        moves.append((round(begin, 3), round(length, 3), target))
        y, free_at = target, begin + length
    return {"start": start, "moves": moves}
