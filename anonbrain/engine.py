"""Anon Brain core engine: gameplay clip + post image -> vertical MP4.

The post can be a single image or a sequence of reveal frames. Voice and
music are mixed at the volumes chosen in the app.
"""

import functools
import json
import random
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

# Default output: vertical 1080p for TikTok / Shorts / Reels
WIDTH = 1080
HEIGHT = 1920
FPS = 30


LAST_ENCODER = "cpu"      # which encoder the last render() actually used
HOLD = "loop=loop=-1:size=1:start=0"    # repeat a still picture's one frame forever
# catches the rare peak when voice and music line up, instead of letting it crackle
# (-1 dB ceiling; it only touches those peaks, so the mix you set stays as it is)
LIMITER = "alimiter=limit=0.891:level=0:latency=1:attack=5:release=80"


class EngineError(Exception):
    """A problem the user can fix (missing file, missing FFmpeg, etc.)."""


def _tool(name: str) -> str:
    """The FFmpeg that ships with the app, or else the one installed on the PC."""
    from .appinfo import find_tool
    path = find_tool(name)
    if not path:
        raise EngineError(
            f"{name} wasn't found. Reinstall Anon Brain, or install FFmpeg "
            f"(open Command Prompt and run: winget install ffmpeg)."
        )
    return path


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # no console flashing up on Windows
_renders: set = set()     # FFmpeg renders in progress (stopped if the app quits)
_stopping = False


def stop_renders():
    """Stop any render that's still going, and don't start new ones (the app is
    closing)."""
    global _stopping
    _stopping = True
    for proc in list(_renders):
        try:
            proc.kill()
        except OSError:
            pass


def run_tool(args: list, text: bool = True, **kw) -> subprocess.CompletedProcess:
    """Run FFmpeg (or another helper program) quietly and collect what it prints."""
    return subprocess.run([str(a) for a in args], capture_output=True, text=text,
                          creationflags=NO_WINDOW, **kw)


@functools.lru_cache(maxsize=64)
def _probe(path: str, stamp: float) -> dict:
    r = run_tool([_tool("ffprobe"), "-v", "error", "-show_entries",
                  "format=duration:stream=codec_type,color_space,height", "-of", "json", path])
    if r.returncode != 0:
        raise EngineError(f"Couldn't read the video '{Path(path).name}'. "
                          "Is it a valid video file?")
    return json.loads(r.stdout or "{}")


def probe(video: Path) -> dict:
    """What FFprobe says about a video (asked once per file, then remembered)."""
    p = Path(video)
    try:
        stamp = p.stat().st_mtime
    except OSError:
        raise EngineError(f"File not found: {p}") from None
    return _probe(str(p), stamp)


def get_duration(video: Path) -> float:
    """Length of a video (or audio) file in seconds."""
    try:
        return float(probe(video)["format"]["duration"])
    except (KeyError, ValueError):
        raise EngineError(f"Couldn't read the video '{Path(video).name}'. "
                          "Is it a valid video file?") from None


def _video_stream(video: Path) -> dict:
    return next((s for s in probe(video).get("streams", []) if s.get("codec_type") == "video"),
                {})


def color_matrix(video: Path) -> str:
    """"bt709" or "bt601": how the gameplay's colors are coded. Overlays (the post,
    captions, your handle) are converted the same way, so their colors come out exact."""
    try:
        st = _video_stream(video)
    except EngineError:
        return "bt709"
    space = (st.get("color_space") or "").lower()
    if space in ("bt470bg", "smpte170m", "bt601"):
        return "bt601"
    if space.startswith("bt709"):
        return "bt709"
    return "bt709" if int(st.get("height") or 1080) >= 600 else "bt601"


# output tags for each, so phones and browsers show the colors as intended
COLOR_TAGS = {"bt709": ["-colorspace", "bt709", "-color_primaries", "bt709",
                        "-color_trc", "bt709", "-color_range", "tv"],
              "bt601": ["-colorspace", "smpte170m", "-color_primaries", "smpte170m",
                        "-color_trc", "smpte170m", "-color_range", "tv"]}


def has_audio(video: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(video).get("streams", []))


def mirror_spans(duration: float, seed: int = 0) -> list[tuple[float, float]]:
    """For "random" mirroring: the stretches that are flipped. Normal and flipped take
    turns, each lasting 1.5 to 3.5 seconds, so the switches never fall into a beat."""
    rng = random.Random(seed or 1)
    spans, t, flipped = [], 0.0, False
    while t < duration:
        length = rng.uniform(1.5, 3.5)
        if flipped:
            spans.append((round(t, 3), round(min(t + length, duration), 3)))
        t += length
        flipped = not flipped
    return spans


def mirror_chain(mode: str, duration: float, seed: int, src: str, out: str) -> str:
    """Filter text that mirrors [src] into [out]."""
    if mode == "on":
        return f";[{src}]hflip[{out}]"
    if mode == "random":
        spans = mirror_spans(duration, seed)
        if spans:
            when = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in spans)
            return (f";[{src}]split[{out}n][{out}m];[{out}m]hflip[{out}f]"
                    f";[{out}n][{out}f]overlay=enable='{when}'[{out}]")
    return f";[{src}]null[{out}]"


def pick_start(clip_length: float, segment_length: float, rng=random) -> float:
    """Random start time so the segment fits inside the clip.

    If the clip is shorter than the segment, start at 0 (the clip will loop).
    """
    room = clip_length - segment_length
    return 0.0 if room <= 0 else round(rng.uniform(0, room), 2)


def _concat_list(frames: list[tuple[Path, float]], duration: float, folder: Path,
                 name: str = "post_frames.txt") -> Path:
    """FFmpeg 'concat' file that shows each reveal frame from its start time."""
    lines = ["ffconcat version 1.0"]
    for i, (path, start) in enumerate(frames):
        end = frames[i + 1][1] if i + 1 < len(frames) else duration
        p = Path(path).resolve().as_posix().replace("'", "'\\''")
        lines += [f"file '{p}'", f"duration {max(end - start, 0.001):.4f}"]
    lines.append(lines[-2])  # concat needs the last file twice
    out = folder / name
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def render(gameplay: Path, post: Path | list[tuple[Path, float]], output: Path,
           duration: float = 30.0, start: float | None = None,
           voice: Path | None = None, voice_delay: float = 0.0, voice_volume: float = 1.0,
           music: Path | None = None, music_volume: float = 0.2, music_start: float = 0.0,
           keep_game_audio: bool = False, game_volume: float = 1.0,
           fps: int = FPS, mirror: str = "off", fit: str = "fill", mirror_seed: int = 0,
           hook: Path | None = None, hook_until: float = 2.8,
           size: tuple[int, int] = (WIDTH, HEIGHT), post_box: dict | None = None,
           post_round: float = 0.0, shadow: float = 0.0,
           border: float = 0.0, border_style: str = "solid", border_color: str = "#ffffff",
           border_colors: list[str] | None = None, slide: dict | None = None,
           brand: dict | None = None, card_in: float = 0.0, encoder: str = "cpu",
           show_post: bool = True, post_until: float | None = None,
           captions: dict | None = None,
           scale: float = 1.0, fast: bool = False,
           progress: Callable[[float], None] | None = None) -> Path:
    """Build the vertical video.

    gameplay      - any landscape or portrait video
    post          - one image, or reveal frames [(image, start_seconds), ...]
    output        - where to save the .mp4
    duration      - video length in seconds
    start         - where in the gameplay to start; None = random spot
    voice         - narration audio, starting `voice_delay` seconds in
    music         - background music (loops, fades out at the end)
    *_volume      - 1.0 = original loudness
    hook          - title-card image shown in the middle until `hook_until` seconds
    size          - output width and height in pixels
    post_box      - where the post goes, {"x", "y", "w"} as fractions (see layout.py)
    post_round    - 0 = square corners .. 1 = oval / circle
    shadow        - drop shadow strength 0..1 (0 = none)
    border        - border thickness in pixels at 1080p (0 = none)
    border_style  - "solid" (border_color) or an animated style from layout.BORDER_STYLES,
                    which uses border_colors (the app's three colors)
    slide         - slide-down reveal plan from reveal.slide_plan(): the post is cropped
                    and the crop glides down to each line as it's read
    brand         - {"watermark": {...}, "endcard": {...}} text overlays (see brand.py)
    card_in       - fade the post in over this many seconds (later posts in a thread)
    fps           - frames per second of the video (24, 30 or 60)
    mirror        - "off", "on" (flipped left-right) or "random" (flips back and forth
                    every couple of seconds; mirror_seed picks the pattern)
    fit           - "fill" (crop the video to fill the frame) or "blur" (the whole video,
                    over a blurred copy of itself: good for wide movie clips)
    keep_game_audio, game_volume - the clip's own sound, at this volume
    show_post     - False = no post image at all (captions only)
    post_until    - fade the post out at this many seconds (then captions take over)
    captions      - {"words": [...], "style": {...}} big on-screen words (see captions.py)
    encoder       - "cpu", "nvidia", "amd" or "intel" (graphics cards fall back to the
                    CPU automatically if they fail); the one used is left in LAST_ENCODER
    scale, fast   - smaller, quicker render (used for previews)
    progress      - called with 0.0 .. 1.0 while rendering
    """
    from PIL import Image

    from .layout import default_box, place_post
    W = int(size[0] * scale) // 2 * 2
    H = int(size[1] * scale) // 2 * 2
    gameplay, output = Path(gameplay), Path(output)
    if not show_post or post is None:
        frames = []
    else:
        frames = [(Path(post), 0.0)] if isinstance(post, (str, Path)) else list(post)
    for f in [gameplay] + [p for p, _ in frames] + [x for x in (voice, music) if x]:
        if not Path(f).exists():
            raise EngineError(f"File not found: {f}")
    output.parent.mkdir(parents=True, exist_ok=True)

    show = bool(frames)
    iw, ih = 1, 1
    if show:
        with Image.open(frames[0][0]) as im:
            iw, ih = im.size
    if post_box is None:
        post_box = default_box("9:16" if W < H else "16:9" if W > H else "1:1", iw / ih)
    px, py, pw, ph = place_post(W, H, iw, ih, post_box)
    PW, PH = max(2, int(round(pw))), max(2, int(round(ph)))
    PX, PY = int(round(px)), int(round(py))

    clip_length = get_duration(gameplay)
    matrix = color_matrix(gameplay)
    # an overlay picture (RGBA) -> video colors, with the gameplay's color coding
    yuva = (f"scale=out_color_matrix={matrix}:out_range=tv,format=yuva420p"
            if matrix == "bt709" else "format=yuva420p")
    if start is None:
        start = pick_start(clip_length, duration)
    loop = clip_length - start < duration  # clip too short -> loop it

    with tempfile.TemporaryDirectory() as tmp:
        if post_round > 0.004:
            # rounded corners: transparent copies of each reveal frame
            from .layout import round_image
            done = {}
            for i, (path, t) in enumerate(frames):
                if path not in done:
                    done[path] = round_image(path, Path(tmp) / f"round_{i:03d}.png", post_round)
                frames[i] = (done[path], t)
        cmd = [_tool("ffmpeg"), "-y", "-loglevel", "error", "-nostats", "-progress", "pipe:1"]
        if loop:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-ss", str(start), "-i", str(gameplay)]
        if not show:
            pass
        elif len(frames) == 1:
            cmd += ["-framerate", str(fps), "-i", str(frames[0][0])]
        else:
            cmd += ["-f", "concat", "-safe", "0", "-i", str(_concat_list(frames, duration, Path(tmp)))]

        # Fill the frame with gameplay (crop the sides, no black bars)
        sliding = show and bool(slide and slide.get("moves"))
        # (frame rate first and crop before scaling: no work spent on frames or
        #  pixels that are thrown away)
        crop_fill = f"crop='min(iw,ih*{W}/{H})':'min(ih,iw*{H}/{W})',scale={W}:{H},setsar=1"
        if fit == "blur":
            # the whole picture, centred, over a soft blown-up copy of itself
            bw_, bh_ = max(2, W // 12) // 2 * 2, max(2, H // 12) // 2 * 2
            video = (f"[0:v]fps={fps},split[gb][gf]"
                     f";[gb]crop='min(iw,ih*{W}/{H})':'min(ih,iw*{H}/{W})',scale={bw_}:{bh_},"
                     f"boxblur=4:2,scale={W}:{H},eq=brightness=-0.08,setsar=1[gbb]"
                     f";[gf]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[gff]"
                     f";[gbb][gff]overlay=x=(W-w)/2:y=(H-h)/2,format=yuv420p[base0]")
        else:
            video = f"[0:v]fps={fps},{crop_fill},format=yuv420p[base0]"
        video += mirror_chain(mirror, duration, mirror_seed, "base0", "base")
        video += (";[base]" + ("split[bg][plain]" if sliding else "null[bg]" if show else "null[v1]"))
        cur, n = "bg", 2 if show else 1

        def still(path):
            """A picture input. It's read once; HOLD (in the filter) repeats it in memory,
            instead of decoding the PNG again for every frame of the video."""
            nonlocal n
            cmd.extend(["-framerate", str(fps), "-i", str(path)])
            n += 1
            return n - 1

        fin = f",fade=t=in:st=0:d={card_in:.2f}:alpha=1" if card_in > 0 else ""
        if post_until is not None and show:     # the post leaves, captions take over
            fin += f",fade=t=out:st={max(post_until - 0.3, 0):.2f}:d=0.3:alpha=1"
        # post style (sizes scale with the video)
        from . import layout as L
        u = L.unit(W, H)
        b = max(1, int(round(border * u))) if border > 0 else 0
        rx, ry = L.corner_radii(PW, PH, post_round)
        orx, ory = L.outer_radii(rx, ry, b, post_round) if b else (rx, ry)
        animated = b and L.BORDER_STYLES.get(border_style, {}).get("animated", False)
        # Shadow and a solid border never change, so they're baked into one still
        if show and (shadow > 0 or (b and not animated)):
            from PIL import Image
            if shadow > 0:
                layer, pad, _ = L.shadow_image(PW + 2 * b, PH + 2 * b, orx, ory, shadow, u)
            else:
                pad = 0
                layer = Image.new("RGBA", (PW + 2 * b, PH + 2 * b), (0, 0, 0, 0))
            if b and not animated:
                layer.alpha_composite(L.solid_border(PW, PH, b, post_round, border_color),
                                      (pad, pad))
            layer.save(Path(tmp) / "style.png")
            i = still(Path(tmp) / "style.png")
            video += (f";[{i}:v]format=rgba,{yuva},{HOLD}{fin}[sl];[{cur}][sl]overlay=x={PX - b - pad}:y={PY - b - pad}"
                      f":eof_action=repeat[st]")
            cur = "st"
        if show and animated:
            # a small color wheel, spun, then the border-sized middle cut out of it
            size = 512
            L.gradient_wheel(border_style, border_colors or [border_color], size).save(
                Path(tmp) / "wheel.png")
            L.ring_mask(PW, PH, b, post_round).save(Path(tmp) / "ring.png")
            g, r = still(Path(tmp) / "wheel.png"), still(Path(tmp) / "ring.png")
            bw, bh = PW + 2 * b, PH + 2 * b
            # the spin repeats every BORDER_PERIOD seconds: work out one turn, then
            # replay it from memory (if that fits in about 300 MB)
            turn = int(round(L.BORDER_PERIOD * fps))
            cycle = f",loop=loop=-1:size={turn}:start=0" \
                if bw * bh * 2.5 * turn < 300e6 and not fast else ""
            k = size / ((bw * bw + bh * bh) ** 0.5 + 4)
            cw, ch = max(2, int(bw * k)), max(2, int(bh * k))
            video += (f";[{g}:v]format=rgb24,{HOLD},rotate=a='2*PI*t/{L.BORDER_PERIOD}':c=black,"
                      f"crop={cw}:{ch},scale={bw}:{bh},format=rgba[wh]"
                      f";[{r}:v]format=gray,{HOLD}[rg];[wh][rg]alphamerge,{yuva}{cycle}{fin}[bd]"
                      f";[{cur}][bd]overlay=x={PX - b}:y={PY - b}:eof_action=repeat[bo]")
            cur = "bo"
        # The post, at the size and spot chosen on the Layout screen
        if show:
            hold = f",{HOLD}" if len(frames) == 1 else ""
            video += (f";[1:v]format=rgba,scale={PW}:{PH}:flags=lanczos,{yuva}{hold},fps={fps}{fin}[post]"
                      f";[{cur}][post]overlay=x={PX}:y={PY}:eof_action=repeat"
                      + ("[card]" if sliding else "[v1]"))
        if sliding:
            # Slide-down reveal: show the card only above a soft edge that
            # glides down line by line. A tall mask (white over black) slides
            # up behind a frame-sized window to move the edge.
            import numpy as np
            from PIL import Image
            k = PH / ih

            def fy(y_img):
                return PY + y_img * k

            edge0 = fy(slide["start"])
            terms, prev = [], edge0
            moves = list(slide["moves"])
            if moves:   # finally uncover the rest (bottom of the post, border, shadow)
                b_end = moves[-1][0] + moves[-1][1]
                moves.append((b_end + 0.15, 0.6, None))
            for begin, length, y_img in moves:
                y = H + 2 if y_img is None else fy(y_img)
                if y <= prev:
                    continue
                c = f"clip((t-{begin:.3f})/{length:.3f},0,1)"
                terms.append(f"{y - prev:.2f}*{c}*{c}*(3-2*{c})")
                prev = y
            edge = f"{edge0:.2f}" + "".join("+" + t for t in terms)
            # Only the card's own area changes, so the masking works on that patch
            # (not the whole frame): the card patch gets the sliding mask as its
            # transparency and goes back over the plain gameplay.
            sp = pad if shadow > 0 else 0
            rx0, ry0 = max(0, PX - b - sp), max(0, PY - b - sp)
            rx0, ry0 = rx0 - rx0 % 2, ry0 - ry0 % 2
            rx1, ry1 = min(W, PX + PW + b + sp), min(H, PY + PH + b + sp)
            rx1, ry1 = min(W, rx1 + rx1 % 2), min(H, ry1 + ry1 % 2)
            RW, RH = rx1 - rx0, ry1 - ry0
            # soft edge sits just above the line: never spills onto the next one
            feather = max(2, int(6 * u))
            col = np.zeros((2 * H, 1), np.float32)
            col[:H] = 255
            col[H - feather:H, 0] = np.linspace(255, 0, feather)
            Image.fromarray(np.repeat(col, 4, 1).astype("uint8"), "L").resize(
                (RW, 2 * H), Image.NEAREST).save(Path(tmp) / "slide_mask.png")
            m = still(Path(tmp) / "slide_mask.png")
            video += (f";[{m}:v]format=gray,{HOLD},"
                      f"crop={RW}:{RH}:0:'max(0,min({2 * H - RH},{H}-({edge})+{ry0}))'[mk]"
                      f";[card]crop={RW}:{RH}:{rx0}:{ry0}[cr];[cr][mk]alphamerge[cm]"
                      f";[plain][cm]overlay=x={rx0}:y={ry0}:format=yuv420[v1]")
        if hook:
            cmd += ["-framerate", str(fps), "-i", str(hook)]
            out_at = max(hook_until - 0.35, 0.3)
            hook_scale = min(W, H) / 1080 * 0.94       # same look at any size
            video += (f";[{n}:v]scale=iw*{hook_scale:.3f}:-1,format=rgba,{yuva},{HOLD},"
                      f"fade=t=in:st=0:d=0.25:alpha=1,fade=t=out:st={out_at:.2f}:d=0.35:alpha=1[hk];"
                      f"[v1][hk]overlay=x=(W-w)/2:y=(H-h)/2:enable='lte(t,{hook_until:.2f})'"
                      f":shortest=0:eof_action=pass[v2]")
            last = "v2"
            n += 1
        else:
            last = "v1"
        # captions: big words in time with the voice
        if captions and captions.get("words"):
            from .captions import build_frames as caption_frames
            cframes, ch = caption_frames(captions, W, H, Path(tmp) / "captions")
            if len(cframes) > 1:
                cmd += ["-f", "concat", "-safe", "0", "-i",
                        str(_concat_list(cframes, duration, Path(tmp), "caption_frames.txt"))]
                y = float((captions.get("style") or {}).get("y", 0.5)) * H - ch / 2
                y = int(min(max(y, 0), H - ch))
                video += (f";[{n}:v]format=rgba,{yuva},fps={fps}[cp]"
                          f";[{last}][cp]overlay=x=0:y={y}:eof_action=pass[vc]")
                n += 1
                last = "vc"
        # your handle, and the end card ("Follow for part 2") over the last seconds
        wm = (brand or {}).get("watermark")
        if wm:
            i = still(wm["png"])
            video += (f";[{i}:v]format=rgba,scale=iw*{scale:.4f}:-1,{yuva},{HOLD}[wm]"
                      f";[{last}][wm]overlay=x={wm['x'] * W:.1f}-w/2:y={wm['y'] * H:.1f}-h/2"
                      f":eof_action=repeat[bw]")
            last = "bw"
        end = (brand or {}).get("endcard")
        if end:
            t0 = end["start"]
            if end.get("dim", 0) > 0:
                video += (f";color=c=black@{end['dim']:.2f}:s={W}x{H}:r={fps},format=rgba,"
                          f"fade=t=in:st={t0:.2f}:d=0.4:alpha=1[dm]"
                          f";[{last}][dm]overlay=enable='gte(t,{t0:.2f})':shortest=0[be0]")
                last = "be0"
            i = still(end["png"])
            video += (f";[{i}:v]format=rgba,scale=iw*{scale:.4f}:-1,{yuva},{HOLD},"
                      f"fade=t=in:st={t0:.2f}:d=0.4:alpha=1[ec]"
                      f";[{last}][ec]overlay=x={end['x'] * W:.1f}-w/2:y={end['y'] * H:.1f}-h/2"
                      f":enable='gte(t,{t0:.2f})':eof_action=repeat[be]")
            last = "be"
        video += f";[{last}]format=yuv420p[v]"

        audio = []
        if voice:
            cmd += ["-i", str(voice)]
            ms = int(voice_delay * 1000)
            audio.append(f"[{n}:a]adelay={ms}:all=1,volume={voice_volume:.3f}[a{n}]")
            n += 1
        if music:
            cmd += ["-stream_loop", "-1", "-ss", f"{music_start:.2f}", "-i", str(music)]
            fade = max(duration - 1.5, 0)
            audio.append(f"[{n}:a]volume={music_volume:.3f},"
                         f"afade=t=out:st={fade:.2f}:d=1.5[a{n}]")
            n += 1
        if keep_game_audio and has_audio(gameplay):
            audio.append(f"[0:a]volume={game_volume:.3f},aresample=44100[a0]")
        labels = "".join(part[part.rindex("["):] for part in audio)
        filters = video
        if audio:
            filters += ";" + ";".join(audio)
            filters += (f";{labels}amix=inputs={len(audio)}:normalize=0:duration=longest,"
                        f"aresample=44100,aformat=channel_layouts=stereo,{LIMITER},apad[aout]")

        cmd += ["-filter_complex", filters, "-map", "[v]"]
        if audio:
            cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
        from .encoders import video_args
        global LAST_ENCODER
        tries = [encoder] + (["cpu"] if encoder != "cpu" else [])
        for kind in tries:
            full = cmd + ["-t", f"{duration:.3f}", *video_args(kind, fast), *COLOR_TAGS[matrix],
                          "-movflags", "+faststart", str(output)]
            err_path = Path(tmp) / "ffmpeg_errors.txt"
            with open(err_path, "w") as err:
                proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=err, text=True,
                                        creationflags=NO_WINDOW)
                _renders.add(proc)
                try:
                    for line in proc.stdout:
                        if progress and line.startswith("out_time_us="):
                            try:
                                progress(min(int(line.split("=")[1]) / 1e6 / duration, 1.0))
                            except ValueError:
                                pass
                    proc.wait()
                finally:
                    _renders.discard(proc)
            if _stopping:
                raise EngineError("Stopped because the app is closing.")
            if proc.returncode == 0:
                LAST_ENCODER = kind
                break
            if kind == "cpu":
                raise EngineError("FFmpeg failed:\n" + err_path.read_text().strip()[-1500:])
            # the graphics card didn't manage it: same video on the processor
    if progress:
        progress(1.0)
    return output
