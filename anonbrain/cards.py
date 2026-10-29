"""Draw clean post cards (4chan or Reddit style) from a post's text.

Used when you paste a link instead of a screenshot. Because we draw the card
ourselves, the text is exact and we know where every line sits, so the line
reveal lines up perfectly (no OCR needed).

draw_4chan(post, out) / draw_reddit(post, out, theme) -> (png path, PostText)
"""

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .ocr import OcrLine, PostText

S = 2   # drawn at 2x for crisp text after scaling

_FONT_FILES = {
    "regular": ["arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"],
    "bold": ["arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "ui": ["segoeui.ttf", "NotoSans-Regular.ttf", "DejaVuSans.ttf"],
    "ui_bold": ["segoeuib.ttf", "NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
}
_FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/liberation"),
              Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/truetype/noto"),
              Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
_cache: dict = {}


def font(kind: str, px: int) -> ImageFont.FreeTypeFont:
    key = (kind, px)
    if key not in _cache:
        f = None
        for name in _FONT_FILES[kind]:
            for d in _FONT_DIRS:
                if (d / name).exists():
                    f = ImageFont.truetype(str(d / name), px)
                    break
            if f:
                break
        _cache[key] = f or ImageFont.load_default(px)
    return _cache[key]


# emoji and other symbols the post fonts can't draw (they'd show as boxes)
_NO_GLYPH = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F\u200D]")


def clean(text: str) -> str:
    return _NO_GLYPH.sub("", text).replace("\t", "    ")


def wrap(text: str, f, width_for_line) -> list[str]:
    """Word-wrap one paragraph. width_for_line(i) gives the room on line i."""
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w) if cur else w
        if f.getlength(trial) <= width_for_line(len(lines)):
            cur = trial
            continue
        if cur:
            lines.append(cur)
            cur = ""
        while f.getlength(w) > width_for_line(len(lines)):     # very long word: break it
            k = len(w)
            while k > 1 and f.getlength(w[:k]) > width_for_line(len(lines)):
                k -= 1
            lines.append(w[:k])
            w = w[k:]
        cur = w
    lines.append(cur)
    return lines


@dataclass
class Para:
    """One line of the post as written (it may wrap onto several on screen)."""
    text: str
    kind: str = "text"        # text / green / quote (>>123 link) / title
    spoken: bool = True


@dataclass
class Post:
    """A post ready to draw, from 4chan or Reddit."""
    site: str                       # "4chan" or "reddit"
    author: str = "Anonymous"
    when: str = ""                  # date text shown in the header
    number: str = ""                # 4chan post number
    subject: str = ""               # 4chan subject / Reddit title
    paras: list[Para] = field(default_factory=list)
    image: bytes | None = None      # thumbnail / picture
    image_info: str = ""            # "364 KB PNG"
    community: str = ""             # board or subreddit
    score: str = ""                 # Reddit score
    comments: str = ""              # Reddit comment count
    is_comment: bool = False        # Reddit comment (not the post itself)
    is_op: bool = False
    id: str = ""                    # for picking posts

    def preview(self, n=90) -> str:
        t = " / ".join(p.text for p in self.paras if p.spoken)
        t = (self.subject + " — " + t) if self.subject and t else (self.subject or t)
        return t[:n] + ("…" if len(t) > n else "")


def _open_image(data: bytes | None, max_w: int, max_h: int):
    if not data:
        return None
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None
    k = min(max_w / im.width, max_h / im.height, 3.0)
    return im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)


def _post_text(lines: list[OcrLine], paras_out: list[str]) -> PostText:
    return PostText(lines=lines, text="\n".join(paras_out))


# --- 4chan ----------------------------------------------------------------------
YOTSUBA = {"bg": (240, 224, 214), "border": (217, 191, 183), "text": (128, 0, 0),
           "name": (17, 119, 67), "subject": (204, 17, 5), "green": (120, 153, 34),
           "quote": (221, 0, 0), "muted": (128, 0, 0), "page": (255, 255, 238)}


def draw_4chan(post: Post, out: Path, width: int = 400) -> tuple[Path, PostText]:
    c = YOTSUBA
    W = width * S
    pad = 10 * S
    body = font("regular", 15 * S)
    bold = font("bold", 14 * S)
    small = font("regular", 11 * S)
    lh = int(15 * S * 1.32)

    thumb = _open_image(post.image, 110 * S, 110 * S)
    # header: subject, name, date, number (wraps if the card is narrow)
    parts = []
    if post.subject:
        parts.append((post.subject, bold, c["subject"]))
    parts.append((post.author or "Anonymous", bold, c["name"]))
    parts.append((post.when, small, c["text"]))
    parts.append((f"No.{post.number}" if post.number else "", small, c["text"]))
    placed, x, hy = [], pad, pad // 2 + 2 * S
    for txt, f, col in parts:
        if not txt:
            continue
        w = int(f.getlength(txt))
        if x > pad and x + w > W - pad:
            x, hy = pad, hy + lh
        placed.append((txt, f, col, x, hy, w))
        x += w + 8 * S
    head_h = hy + lh + 6 * S - pad // 2
    text_x = pad
    if thumb:
        text_x = pad + thumb.width + 18 * S
    thumb_bottom = head_h + pad + (thumb.height + 16 * S if thumb else 0)

    # lay out the text first (width depends on whether we're beside the picture)
    layout = []   # (para, [visual lines], y of first line)
    y = head_h + pad
    for para in post.paras:
        f = body
        lines = wrap(clean(para.text), f, lambda i, y0=y: (
            W - pad - (text_x if (y0 + i * lh) < thumb_bottom else pad)))
        layout.append((para, lines, y))
        y += lh * max(1, len(lines))
    H = max(y, thumb_bottom) + pad

    im = Image.new("RGB", (W, H), c["bg"])
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W - 1, H - 1], outline=c["border"], width=S)
    ocr: list[OcrLine] = []

    for txt, f, col, x, hy, w in placed:
        d.text((x, hy + (3 * S if f is small else 0)), txt, font=f, fill=col)
        ocr.append(OcrLine(txt, x, hy, x + w, hy + lh, narrated=False))

    if thumb:
        ty = head_h + pad
        im.paste(thumb, (pad, ty))
        if post.image_info:
            iw = int(small.getlength(post.image_info))
            ix = pad + (thumb.width - iw) // 2
            d.text((ix, ty + thumb.height + 3 * S), post.image_info, font=small, fill=c["muted"])

    spoken = []
    for para, lines, y0 in layout:
        col = c["green"] if para.kind == "green" else c["quote"] if para.kind == "quote" \
            else c["text"]
        for i, line in enumerate(lines):
            ly = y0 + i * lh
            lx = text_x if ly < thumb_bottom else pad
            d.text((lx, ly), line, font=body, fill=col)
            w = int(body.getlength(line))
            if para.kind == "quote":
                d.line([(lx, ly + lh - 4 * S), (lx + w, ly + lh - 4 * S)], fill=col, width=S)
            if line.strip():
                ocr.append(OcrLine(line, lx, ly, lx + w, ly + lh,
                                   narrated=para.spoken, green=para.kind == "green"))
        if para.spoken and para.text.strip():
            spoken.append(clean(para.text).strip())

    out = Path(out)
    im.save(out)
    return out, _post_text(ocr, spoken)


# --- Reddit ----------------------------------------------------------------------
REDDIT = {
    "dark": {"bg": (26, 26, 27), "text": (215, 218, 220), "muted": (129, 131, 132),
             "title": (215, 218, 220), "accent": (255, 69, 0), "border": (52, 53, 54),
             "quote_bar": (79, 188, 255)},
    "light": {"bg": (255, 255, 255), "text": (26, 26, 27), "muted": (120, 124, 126),
              "title": (34, 34, 34), "accent": (255, 69, 0), "border": (220, 220, 220),
              "quote_bar": (0, 121, 211)},
}


def _reddit_layout(post: Post, c: dict, width: int):
    W = width * S
    pad = 16 * S
    small = font("ui", 12 * S)
    body = font("ui", 16 * S)
    title_f = font("ui_bold", 20 * S)
    lh_small, lh, lh_title = int(12 * S * 1.5), int(16 * S * 1.45), int(20 * S * 1.3)
    inner = W - 2 * pad

    head = (f"r/{post.community}  •  " if post.community and not post.is_comment else "") + \
        f"u/{post.author}" + (f"  •  {post.when}" if post.when else "")
    y = pad
    blocks = [("head", [head], y, small, c["muted"], lh_small, False)]
    y += lh_small + 6 * S
    spoken = []
    if post.subject and not post.is_comment:
        tl = wrap(clean(post.subject), title_f, lambda i: inner)
        blocks.append(("title", tl, y, title_f, c["title"], lh_title, True))
        spoken.append(clean(post.subject).strip())
        y += lh_title * len(tl) + 8 * S
    for para in post.paras:
        indent = 14 * S if para.kind == "green" else 0      # Reddit "> quote"
        pl = wrap(clean(para.text), body, lambda i, ind=indent: inner - ind)
        blocks.append(("quote" if indent else "body", pl, y, body, c["text"], lh, para.spoken))
        if para.spoken and para.text.strip():
            spoken.append(clean(para.text).strip())
        y += lh * len(pl) + (4 * S if para.text.strip() else 0)
    pic = _open_image(post.image, inner, int(inner * 1.25))
    pic_y = y + 4 * S
    if pic:
        y = pic_y + pic.height + 10 * S
    foot = []
    if post.score:
        foot.append(f"▲ {post.score}" if not post.is_comment else f"▲ {post.score} points")
    if post.comments:
        foot.append(f"{post.comments} comments")
    if foot:
        blocks.append(("foot", ["     ".join(foot)], y + 4 * S, small, c["muted"], lh_small, False))
        y += lh_small + 8 * S
    H = y + pad
    return W, H, pad, blocks, pic, pic_y, inner, spoken


def reddit_height(post: Post, width: int = 420) -> tuple[int, int]:
    """(width, height) the card would be, without drawing it."""
    W, H, *_ = _reddit_layout(post, REDDIT["dark"], width)
    return W, H


def draw_reddit(post: Post, out: Path, theme: str = "dark",
                width: int = 420) -> tuple[Path, PostText]:
    c = REDDIT.get(theme, REDDIT["dark"])
    W, H, pad, blocks, pic, pic_y, inner, spoken = _reddit_layout(post, c, width)
    im = Image.new("RGB", (W, H), c["bg"])
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=10 * S, outline=c["border"], width=S)
    ocr = []
    for kind, lines, y0, f, col, step, said in blocks:
        x = pad + (14 * S if kind == "quote" else 0)
        if kind == "quote":
            d.rectangle([pad, y0, pad + 3 * S, y0 + step * len(lines)], fill=c["quote_bar"])
        for i, line in enumerate(lines):
            ly = y0 + i * step
            d.text((x, ly), line, font=f, fill=col)
            if line.strip():
                w = int(f.getlength(line))
                ocr.append(OcrLine(line, x, ly, x + w, ly + step, narrated=said))
    if pic:
        im.paste(pic, (pad + (inner - pic.width) // 2, pic_y))
    im.save(out)
    return Path(out), _post_text(ocr, spoken)


def draw(post: Post, out: Path, reddit_theme: str = "dark") -> tuple[Path, PostText]:
    if post.site == "reddit":
        return draw_reddit(post, out, reddit_theme)
    return draw_4chan(post, out)


# --- long posts: split into pages that each fit on screen --------------------------
_SENT = re.compile(r"(?<=[.!?…])[\"')\]]*\s+(?=\S)")


def _sentences(text: str) -> list[str]:
    parts, last = [], 0
    for m in _SENT.finditer(text):
        parts.append(text[last:m.start()].strip() + text[m.start():m.end()].strip())
        last = m.end()
    parts.append(text[last:].strip())
    return [p for p in parts if p]


def paginate(post: Post, max_ratio: float, width: int = 420) -> list[Post]:
    """Split a Reddit post into several cards, each no taller than max_ratio x its
    width. Breaks between paragraphs, or between sentences inside a long one.
    Page 1 keeps the title; the last page shows the upvotes and comments."""
    import copy
    base = copy.copy(post)

    def page(i, paras, last):
        p = copy.copy(base)
        p.paras = paras
        if i > 0:
            p.subject, p.community, p.image = "", "", None
        if not last:
            p.score, p.comments = "", ""
        return p

    def fits(p) -> bool:
        w, h = reddit_height(p, width)
        return h <= w * max_ratio

    if fits(post):
        return [post]
    units = []                      # (para index, text, kind, spoken)
    for k, para in enumerate(post.paras):
        bits = _sentences(para.text) if para.text.strip() else [para.text]
        for b in bits:
            units.append((k, b, para.kind, para.spoken))

    def paras_of(us):
        out = []
        for k, text, kind, spoken in us:
            if out and out[-1][0] == k:
                out[-1][1].text += " " + text
            else:
                out.append((k, Para(text, kind, spoken)))
        while out and not out[-1][1].text.strip():
            out.pop()
        return [p for _, p in out]

    pages, cur = [], []
    for u in units:
        trial = cur + [u]
        if cur and not fits(page(len(pages), paras_of(trial), True)):
            pages.append(cur)
            cur = [u] if u[1].strip() else []
        else:
            cur = trial
    if cur:
        pages.append(cur)
    out = [page(i, paras_of(us), i == len(pages) - 1) for i, us in enumerate(pages)]
    n = len(out)
    for i, p in enumerate(out):
        p.when = (post.when + "  •  " if post.when and i == 0 else "") + f"{i + 1}/{n}"
        p.id = f"{post.id}_p{i + 1}"
    return [p for p in out if p.paras or p.subject]
