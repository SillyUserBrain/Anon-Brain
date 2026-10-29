"""Video formats, quality presets and where the post sits on screen.

The post's position is stored as fractions of the frame, so the same layout
works at any quality:  {"x": centre x, "y": centre y, "w": width}  (0..1).
The Layout screen and the renderer both use place_post(), so what you see
in the phone preview is exactly what ends up in the video.
"""

import hashlib
from pathlib import Path

FORMATS = {
    "9:16": {"name": "Vertical", "ratio": (9, 16),
             "uses": "TikTok · YouTube Shorts · Instagram Reels · Snapchat"},
    "4:5": {"name": "Portrait", "ratio": (4, 5),
            "uses": "Instagram and Facebook feed posts"},
    "1:1": {"name": "Square", "ratio": (1, 1),
            "uses": "Instagram feed · X / Twitter · Facebook"},
    "16:9": {"name": "Widescreen", "ratio": (16, 9),
             "uses": "Regular YouTube videos · X / Twitter · Twitch"},
}
DEFAULT_FORMAT = "9:16"

RESOLUTIONS = {
    "720p": (720, "Small files, quickest to make"),
    "1080p": (1080, "Recommended. What most apps play"),
    "1440p": (1440, "Extra sharp"),
    "4K": (2160, "Huge files, slowest to make"),
}
DEFAULT_RESOLUTION = "1080p"

MAX_POST_HEIGHT = 0.96       # the post never gets taller than this much of the frame
MIN_POST_WIDTH = 0.15


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def output_size(fmt: str, resolution: str) -> tuple[int, int]:
    """Pixel size, e.g. ("9:16", "1080p") -> (1080, 1920)."""
    a, b = FORMATS.get(fmt, FORMATS[DEFAULT_FORMAT])["ratio"]
    short = RESOLUTIONS.get(resolution, RESOLUTIONS[DEFAULT_RESOLUTION])[0]
    if a <= b:
        return _even(short), _even(short * b / a)
    return _even(short * a / b), _even(short)


def aspect(fmt: str) -> float:
    a, b = FORMATS.get(fmt, FORMATS[DEFAULT_FORMAT])["ratio"]
    return a / b


def margins(fmt: str) -> dict:
    """Space to leave when snapping to an edge (fractions of the frame).
    Vertical videos keep clear of the caption and buttons apps draw on top."""
    if fmt == "9:16":
        return {"top": 0.12, "bottom": 0.21, "side": 0.045}
    return {"top": 0.06, "bottom": 0.06, "side": 0.05}


def place_post(W: float, H: float, img_w: float, img_h: float, box: dict):
    """Where the post goes in a W x H frame: (x, y, width, height)."""
    ratio = img_h / max(img_w, 1)
    pw = min(max(box.get("w", 0.9), MIN_POST_WIDTH), 1.0) * W
    ph = pw * ratio
    if ph > H * MAX_POST_HEIGHT:
        ph = H * MAX_POST_HEIGHT
        pw = ph / ratio
    x = min(max(box.get("x", 0.5) * W - pw / 2, 0), W - pw)
    y = min(max(box.get("y", 0.5) * H - ph / 2, 0), H - ph)
    return x, y, pw, ph


def snap(fmt: str, where: str, box: dict, img_aspect: float) -> dict:
    """Move the post to 'top', 'center' or 'bottom' (always centred left-right)."""
    fa = aspect(fmt)
    m = margins(fmt)
    w = box.get("w", 0.9)
    h = min(w * fa / img_aspect, MAX_POST_HEIGHT)      # post height as a fraction
    w = h * img_aspect / fa
    if where == "top":
        y = m["top"] + h / 2
    elif where == "bottom":
        y = 1 - m["bottom"] - h / 2
    else:
        y = 0.5
    y = min(max(y, h / 2), 1 - h / 2)
    return {"x": 0.5, "y": round(y, 4), "w": round(w, 4)}


def fit_width(fmt: str, box: dict, img_aspect: float) -> dict:
    """As wide as possible while keeping the side margins."""
    w = 1 - 2 * margins(fmt)["side"]
    return clamp({**box, "w": w, "x": 0.5}, fmt, img_aspect)


def default_box(fmt: str, img_aspect: float) -> dict:
    """The 'Reset' layout: big and near the top for vertical, centred otherwise."""
    fa = aspect(fmt)
    m = margins(fmt)
    max_h = 0.68 if fmt == "9:16" else 0.84
    w = min(1 - 2 * m["side"], max_h * img_aspect / fa)
    return snap(fmt, "top" if fmt == "9:16" else "center", {"w": w}, img_aspect)


def clamp(box: dict, fmt: str, img_aspect: float) -> dict:
    """Keep the stored numbers inside the frame (what place_post shows)."""
    fa = aspect(fmt)
    x, y, pw, ph = place_post(fa, 1.0, img_aspect, 1.0, box)
    return {"x": round((x + pw / 2) / fa, 4), "y": round(y + ph / 2, 4), "w": round(pw / fa, 4)}


def describe(fmt: str, resolution: str) -> str:
    w, h = output_size(fmt, resolution)
    return f"{FORMATS[fmt]['name']} {fmt} · {resolution} ({w} × {h})"


# --- post style: rounded corners, shadow, border -------------------------------
# Corners are quarter ellipses. `amount` 0..1 sets their radii as a share of
# half the width / height, so 1.0 is a full oval (a circle for a square post).
# The border sits outside the post; its outer corners are the inner radii plus
# the border thickness. Sizes are in pixels at 1080p and scale with the video.

BORDER_PERIOD = 4.0   # seconds for an animated border to go round once

BORDER_STYLES = {
    "solid": {"name": "Solid color", "animated": False},
    "spin": {"name": "Color spin", "animated": True,
             "tip": "Your three app colors chasing round the border"},
    "rainbow": {"name": "Rainbow", "animated": True,
                "tip": "Every color, spinning round"},
    "shimmer": {"name": "Shimmer", "animated": True,
                "tip": "A bright glint sweeping round your main color"},
}


def border_stops(style: str, colors: list[str]) -> list[tuple[float, str]]:
    """Gradient colors round the border (position 0..1, counter-clockwise)."""
    p, s, t = (colors + ["#ffffff"] * 3)[:3]
    if style == "spin":
        return [(0, p), (0.33, s), (0.66, t), (1, p)]
    if style == "rainbow":
        hues = ["#ff3b3b", "#ff9a1f", "#ffe11f", "#3bd64a", "#1fd6e6", "#3b6bff", "#c03bff",
                "#ff3b3b"]
        return [(i / 7, c) for i, c in enumerate(hues)]
    if style == "shimmer":
        return [(0, p), (0.38, p), (0.47, "#ffffff"), (0.5, "#ffffff"), (0.59, p),
                (0.88, p), (0.94, "#ffffff"), (1, p)]
    return [(0, p), (1, p)]


def unit(W: float, H: float) -> float:
    """1 'pixel at 1080p' in this frame."""
    return min(W, H) / 1080


def corner_radii(w: float, h: float, amount: float) -> tuple[float, float]:
    amount = min(max(amount, 0.0), 1.0)
    return amount * w / 2, amount * h / 2


def outer_radii(rx: float, ry: float, b: float, amount: float) -> tuple[float, float]:
    """Corner radii of the border's outside edge (square posts keep square corners)."""
    return (rx + b, ry + b) if amount > 0.004 else (0.0, 0.0)


def shape_mask(w: int, h: int, rx: float, ry: float, supersample: int = 4):
    """White rounded shape on black, w x h, corners with radii rx, ry."""
    from PIL import Image, ImageDraw
    k = supersample
    W, H = max(int(w), 1) * k, max(int(h), 1) * k
    rx, ry = min(rx * k, W / 2), min(ry * k, H / 2)
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    if rx < 0.5 or ry < 0.5:
        d.rectangle([0, 0, W, H], fill=255)
    else:
        d.rectangle([rx, 0, W - rx, H], fill=255)
        d.rectangle([0, ry, W, H - ry], fill=255)
        for x0, y0 in ((0, 0), (W - 2 * rx, 0), (0, H - 2 * ry), (W - 2 * rx, H - 2 * ry)):
            d.ellipse([x0, y0, x0 + 2 * rx, y0 + 2 * ry], fill=255)
    return m.resize((max(int(w), 1), max(int(h), 1)), Image.LANCZOS)


_masks: dict = {}


def round_mask(w: int, h: int, amount: float, supersample: int = 4):
    """Alpha mask for the post with rounded corners (cached: reveal frames
    all share one size)."""
    key = (w, h, round(amount, 4), supersample)
    if key not in _masks:
        if len(_masks) > 8:
            _masks.clear()
        _masks[key] = shape_mask(w, h, *corner_radii(w, h, amount), supersample)
    return _masks[key].copy()


def round_image(src: Path, dst: Path, amount: float) -> Path:
    """Copy of `src` with rounded (transparent) corners, saved as PNG."""
    from PIL import Image, ImageChops
    with Image.open(src) as im:
        im = im.convert("RGBA")
        mask = round_mask(im.width, im.height, amount)
        im.putalpha(ImageChops.multiply(im.getchannel("A"), mask))
        im.save(dst)
    return dst


def ring_mask(pw: int, ph: int, b: int, amount: float):
    """The border: a (pw+2b) x (ph+2b) mask, white where the border is."""
    from PIL import ImageChops
    rx, ry = corner_radii(pw, ph, amount)
    orx, ory = outer_radii(rx, ry, b, amount)
    outer = shape_mask(pw + 2 * b, ph + 2 * b, orx, ory)
    inner = shape_mask(pw + 2 * b, ph + 2 * b, 0, 0).point(lambda v: 0)
    inner.paste(shape_mask(pw, ph, rx, ry), (b, b))
    return ImageChops.subtract(outer, inner)


def solid_border(pw: int, ph: int, b: int, amount: float, color: str):
    from PIL import Image
    ring = ring_mask(pw, ph, b, amount)
    im = Image.new("RGBA", ring.size, color)
    im.putalpha(ring)
    return im


def gradient_wheel(style: str, colors: list[str], size: int = 512):
    """Square conic gradient for an animated border (spun by the renderer)."""
    import numpy as np
    from PIL import Image
    stops = border_stops(style, colors)
    pos = np.array([p for p, _ in stops])
    rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for _, c in stops], float)
    y, x = np.mgrid[0:size, 0:size] + 0.5
    ang = np.arctan2(-(y - size / 2), x - size / 2)          # counter-clockwise from +x
    t = (ang / (2 * np.pi)) % 1.0
    out = np.stack([np.interp(t, pos, rgb[:, i]) for i in range(3)], -1)
    return Image.fromarray(out.astype("uint8"), "RGB")


def shadow_params(strength: float, u: float) -> tuple[float, float, float]:
    """(blur radius, drop, opacity) for shadow strength 0..1 at unit u."""
    s = min(max(strength, 0.0), 1.0)
    return u * (8 + 26 * s), u * (4 + 14 * s), 0.38 + 0.5 * s


def shadow_image(ow: float, oh: float, orx: float, ory: float, strength: float, u: float):
    """Soft shadow for a shape of ow x oh. Returns (RGBA image, pad, drop):
    place its top-left at (shape_x - pad, shape_y - pad)."""
    from PIL import Image, ImageFilter
    blur, drop, alpha = shadow_params(strength, u)
    pad = int(blur * 2.6 + drop) + 2
    ow, oh = max(int(round(ow)), 1), max(int(round(oh)), 1)
    m = Image.new("L", (ow + 2 * pad, oh + 2 * pad), 0)
    m.paste(shape_mask(ow, oh, orx, ory, 2), (pad, pad + int(round(drop))))
    m = m.filter(ImageFilter.GaussianBlur(blur))
    m = m.point(lambda v: int(v * alpha))
    im = Image.new("RGBA", m.size, (0, 0, 0, 255))
    im.putalpha(m)
    return im, pad, drop


def corner_label(amount: float, img_aspect: float) -> str:
    if amount <= 0.004:
        return "Square"
    if amount >= 0.995:
        return "Circle" if abs(img_aspect - 1) < 0.04 else "Oval"
    return f"{round(amount * 100)}%"


# --- a still from the gameplay for the preview ----------------------------------
def grab_frame(video: Path, out_dir: Path, at: float = 0.3) -> Path | None:
    """Save one frame from `at` (fraction) through the video. Cached per file."""
    from .engine import _tool, get_duration, run_tool
    video = Path(video)
    try:
        key = hashlib.md5(f"{video.resolve()}|{video.stat().st_mtime}".encode()).hexdigest()[:12]
    except OSError:
        return None
    out = Path(out_dir) / f"still_{key}.jpg"
    if out.exists():
        return out
    try:
        t = get_duration(video) * at
    except Exception:
        t = 1.0
    r = run_tool([_tool("ffmpeg"), "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
                  "-i", video, "-frames:v", "1", "-vf", "scale=-2:720", "-q:v", "4", out],
                 text=False)
    return out if r.returncode == 0 and out.exists() else None
