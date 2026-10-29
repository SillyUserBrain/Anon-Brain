"""Read the text out of a post screenshot (works offline).

Returns both the readable text (for the editable text box) and the position
of every line in the image, which the line-by-line reveal uses.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import wordninja

_ocr = None
_lm = wordninja.DEFAULT_LANGUAGE_MODEL

# Words the space-repair step must never split apart
KEEP_WORDS = {
    "anon", "anons", "lmao", "lmfao", "kek", "kekd", "tfw", "mfw", "mrw", "op", "gf", "bf",
    "ngl", "smh", "imo", "imho", "lol", "lel", "irl", "tbh", "idk", "ikr", "rn", "af",
    "reddit", "redditor", "4chan", "chud", "normie", "normies", "based", "cringe",
}

# Lines that are post furniture, not the post itself (never read aloud)
JUNK_PATTERNS = [
    r"^:?\s*anonymous\b",                       # 4chan name field
    r"\d{2}/\d{2}/\d{2}",                        # 4chan date
    r"\bno\.\s*\d{5,}",                          # post number
    r"^\(?\d+(\.\d+)?\s*[kKmM]?B\b",             # "12 KB JPG"
    r"\.(jpe?g|png|gif|webm|mp4)\b",            # file names
    r"^>>\d+",                                   # reply links
    r"^(r|u)/\w+",                               # reddit sub / user
    r"^posted by\b",
    r"^\d+(\.\d+)?k?\s*(comments?|upvotes?|points?|votes?)\b",
    r"^(reply|share|award|report|save|vote)s?$",
    r"^\d+\s*(h|hr|d|mo|y|min)s?\s*ago$",
    r"^[^\w]{0,6}$",                             # stray symbols (numbers are kept)
]


@dataclass
class OcrLine:
    text: str
    left: int
    top: int
    right: int
    bottom: int
    narrated: bool = True   # False for header junk like names and dates
    green: bool = False     # greentext color (4chan quotes)


@dataclass
class PostText:
    lines: list[OcrLine] = field(default_factory=list)
    text: str = ""          # cleaned, paragraph-joined text for the text box


def _engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


# --- space repair from the picture ---------------------------------------------
# OCR often drops spaces ("tome" for "to me"). The picture still shows them:
# the gap between two words is several times wider than between two letters.
# We cut the line into word-shaped pieces of ink and share the letters out
# between the pieces so each piece gets the letters that fit its width.

# Rough letter widths (Arial, 1/1000 em); anything else counts as 556
_W = {**{c: 556 for c in "abdeghnopqu0123456789?#$"},
      **{c: 500 for c in "ckvxyzsJ"}, **{c: 222 for c in "ijl'|"},
      **{c: 278 for c in "ftI.,:;!/[]\\ "}, "r": 333, "m": 833, "w": 722, "-": 333,
      "(": 333, ")": 333, '"': 355, ">": 584, "<": 584, "M": 833, "W": 944}


def _cw(c: str) -> float:
    if c in _W:
        return _W[c]
    return 667 if c.isupper() else 556


def _ink_words(gray, box):
    """Word-sized blobs of ink in a line box: ([(start, end), ...], text height)."""
    import numpy as np
    x0, y0, x1, y1 = box
    crop = gray[max(y0, 0):y1, max(x0, 0):x1]
    if crop.size == 0 or crop.shape[1] < 4:
        return None
    bg, dark = np.median(crop), np.percentile(crop, 2)
    if bg - dark < 30:
        return None
    if np.mean(crop < bg) > 0.5:          # light text on a dark background
        crop = 255 - crop
        bg, dark = np.median(crop), np.percentile(crop, 2)
    ink = crop < bg - max(20, 0.3 * (bg - dark))
    rows = np.where(ink.any(1))[0]
    cols = ink.any(0)
    xs = np.where(cols)[0]
    if len(rows) == 0 or len(xs) == 0:
        return None
    h = rows[-1] - rows[0] + 1
    gap_min = max(3, 0.22 * h)            # word gaps are wider than this
    words, start, run = [], xs[0], 0
    for x in range(xs[0], xs[-1] + 1):
        if cols[x]:
            if run >= gap_min:
                words.append((start, x - run))
                start = x
            run = 0
        else:
            run += 1
    words.append((start, xs[-1] + 1))
    return words, h


def _can_cut(a: str, b: str) -> float | None:
    """Cost of a new space between characters a and b (None = never)."""
    if a.isalpha() and b.isalpha():
        return 0.12
    if (a in ",.!?;:" and b.isalpha()) or (a.isalpha() and b.isdigit()) \
            or (a.isdigit() and b.isalpha()):
        return 0.04
    return None


def respace(text: str, found) -> str:
    """Put spaces where the picture shows word gaps.

    Each piece of text between spaces is matched to one or more blobs of
    ink, so its predicted width fits the blobs. OCR's own spaces are kept
    unless they clearly don't fit; a new space only goes between letters."""
    if not found:
        return text
    words, h = found
    chars = [c for c in text if c != " "]
    n, m = len(words), len(chars)
    if n < 2 or m < 2:
        return text
    had_space = set()          # char index that had a space before it
    k = 0
    for c in text:
        if c == " ":
            had_space.add(k)
        else:
            k += 1
    cum = [0.0]
    for c in chars:
        cum.append(cum[-1] + _cw(c))
    scale = sum(b - a for a, b in words) / cum[-1]
    gap_min = max(3, 0.22 * h)
    cut_cost = [0.0] * (m + 1)
    for i in range(1, m):
        if i in had_space:
            cut_cost[i] = -0.05
        else:
            c = _can_cut(chars[i - 1], chars[i])
            cut_cost[i] = c if c is not None else None
    INF = float("inf")
    best = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    MAX_MERGE, MAX_CHARS = 4, 30
    for q in range(n):
        for p in range(m):
            base = best[q][p]
            if base == INF or (p and cut_cost[p] is None):
                continue
            base += cut_cost[p] if p else 0.0
            merge = 0.0
            for j in range(q + 1, min(n, q + MAX_MERGE) + 1):
                if j > q + 1:     # joining two blobs: costs more the wider the gap
                    gap = words[j - 1][0] - words[j - 2][1]
                    merge += 0.25 * gap / gap_min
                span = words[j - 1][1] - words[q][0]
                for i in range(p + 1, min(m, p + MAX_CHARS) + 1):
                    if j == n and i != m:
                        continue
                    err = (scale * (cum[i] - cum[p]) - span) / max(span, h)
                    cost = base + merge + err * err
                    if cost < best[j][i]:
                        best[j][i], back[j][i] = cost, (q, p)
    if best[n][m] == INF or best[n][m] / n > 0.3:   # doesn't fit: trust the OCR
        return text
    cuts, j, i = set(), n, m
    while j:
        j, i = back[j][i]
        cuts.add(i)
    cuts.discard(0)
    out = []
    for i, c in enumerate(chars):
        if i in cuts:
            out.append(" ")
        out.append(c)
    return "".join(out).strip()


# --- space repair from words --------------------------------------------------
def _cost(words):
    return sum(_lm._wordcost.get(w.lower(), 50.0) for w in words)


def _split_word(w: str) -> str:
    if w.lower() in KEEP_WORDS or len(w) < 3:
        return w
    if len(w) < 7 and w.lower() in _lm._wordcost:   # a real short word: leave it
        return w
    best = wordninja.split(w)
    if w[0] == "l":  # OCR often reads a capital I as a lowercase l
        alt = wordninja.split("I" + w[1:])
        if _cost(alt) < _cost(best):
            best = alt
    if len(best) <= 1:
        return best[0] if best and best[0].lower() != w.lower() else w
    return " ".join(best)


def repair_spacing(line: str) -> str:
    s = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", line)
    s = re.sub(r"([,.!?;:])(?=[A-Za-z]|\"[A-Za-z])", r"\1 ", s)
    s = re.sub(r"[A-Za-z']+", lambda m: _split_word(m.group(0)), s)
    # lone l -> I, lam -> I am, l'm -> I'm
    s = re.sub(r"\bl\b", "I", s)
    s = re.sub(r"\b[lI]am\b", "I am", s)
    s = re.sub(r"\bl'(m|ve|ll|d)\b", r"I'\1", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _english_cost(line: str) -> float:
    """How unlikely the words are (lower = more like normal English)."""
    total = 0.0
    for w in re.findall(r"[A-Za-z]+", line.lower()):
        total += 8.0 if w in KEEP_WORDS else _lm._wordcost.get(w, 30.0 + 2 * len(w))
    return total


def best_reading(raw: str, found) -> str:
    """Spaces from the picture, unless that reads clearly worse than the
    dictionary-only guess (e.g. when OCR dropped a letter)."""
    by_picture = repair_spacing(respace(raw, found))
    by_words = repair_spacing(raw)
    if by_picture == by_words:
        return by_picture
    return by_picture if _english_cost(by_picture) <= _english_cost(by_words) + 4 else by_words


def is_junk(text: str) -> bool:
    t = text.strip().lower()
    return any(re.search(p, t, re.IGNORECASE) for p in JUNK_PATTERNS)


# --- main --------------------------------------------------------------------
def _is_green(rgb, box) -> bool:
    """Greentext (4chan quote color, a muted olive green)."""
    import numpy as np
    x0, y0, x1, y1 = box
    crop = rgb[max(y0, 0):y1, max(x0, 0):x1].reshape(-1, 3).astype(float)
    if len(crop) == 0:
        return False
    lum = crop.mean(1)
    ink = crop[lum <= np.percentile(lum, 12)]
    if len(ink) < 8 or np.median(lum) - lum.min() < 40:
        return False
    r, g, b = ink.mean(0)
    return g >= r - 6 and (r + g) / 2 - b > 22


def read_post(image: Path) -> PostText:
    import numpy as np
    from PIL import Image
    with Image.open(image) as im:
        im = im.convert("RGB")
    # Small screenshots read much better a little bigger
    scale = 2 if max(im.size) < 1600 else 1
    if scale > 1:
        im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
    rgb = np.asarray(im)
    gray = np.asarray(im.convert("L")).astype(float)
    result, _ = _engine()(rgb)
    if not result:
        return PostText()

    lines = []
    for box, txt, _conf in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        b = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
        text = best_reading(txt, _ink_words(gray, b))
        lines.append(OcrLine(text, *(int(round(v / scale)) for v in b),
                             green=_is_green(rgb, b)))

    # Reading order: top to bottom, left to right for lines at the same height
    lines.sort(key=lambda l: (l.top, l.left))
    rows = []
    for l in lines:
        if rows and abs(l.top - rows[-1][0].top) < (l.bottom - l.top) * 0.5:
            rows[-1].append(l)
        else:
            rows.append([l])
    lines = [l for row in rows for l in sorted(row, key=lambda l: l.left)]

    for l in lines:
        l.narrated = not is_junk(l.text)

    # Every line on screen is its own line, like the post shows it. The one
    # exception is greentext that wrapped: a green line that doesn't start
    # with ">" right under another green line continues that quote.
    body = [l for l in lines if l.narrated]
    heights = sorted(l.bottom - l.top for l in body) or [30]
    h = heights[len(heights) // 2]
    out, prev = [], None
    for l in body:
        wrapped = (prev is not None and l.green and prev.green
                   and not l.text.startswith(">") and l.top - prev.bottom < h * 0.9)
        if wrapped:
            out[-1] += " " + l.text
        else:
            out.append(l.text)
        prev = l

    return PostText(lines=lines, text="\n".join(out))
