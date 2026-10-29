"""ElevenLabs narration.

The API key is stored in Windows Credential Manager (via `keyring`), never in
a plain file, so it stays private even if you share the app folder.

Generated narration is cached by (text, voice, model), so previewing and then
rendering the same post only spends your ElevenLabs characters once.
"""

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import keyring
import requests

from .engine import EngineError, get_duration
from .settings import cache_dir

API = "https://api.elevenlabs.io/v1"
KEYRING_SERVICE = "Anon Brain"
KEYRING_USER = "elevenlabs_api_key"

MODELS = {
    "eleven_multilingual_v2": "Multilingual v2 (best quality)",
    "eleven_turbo_v2_5": "Turbo v2.5 (faster, half the credits)",
    "eleven_flash_v2_5": "Flash v2.5 (fastest, half the credits)",
}

NO_VOICE = "__none__"
WORDS_PER_SECOND = 2.7   # reading pace used when there's no voice


class VoiceError(EngineError):
    pass


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Narration:
    audio: Path | None     # None = no voice (silent, timed text only)
    words: list[Word]
    length: float          # seconds
    lines: list = field(default_factory=list)   # (start, end) seconds of each line read


# --- API key -----------------------------------------------------------------
def get_key() -> str:
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
    except Exception:
        return ""


def set_key(key: str):
    key = key.strip()
    if key:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:
            pass


def _headers(key: str | None = None) -> dict:
    key = key if key is not None else get_key()
    if not key:
        raise VoiceError("No ElevenLabs API key yet. Add one in Settings (gear icon).")
    return {"xi-api-key": key}


def _check(resp: requests.Response):
    if resp.ok:
        return
    try:
        detail = resp.json().get("detail")
        msg = detail.get("message") if isinstance(detail, dict) else str(detail)
    except ValueError:
        msg = resp.text[:200]
    if resp.status_code == 401:
        raise VoiceError(f"ElevenLabs rejected the API key. ({msg})")
    if resp.status_code == 429:
        raise VoiceError("ElevenLabs is busy or you hit a rate limit. Try again in a moment.")
    raise VoiceError(f"ElevenLabs error {resp.status_code}: {msg}")


# --- voices ------------------------------------------------------------------
def list_voices(key: str | None = None) -> list[dict]:
    """[{id, name, category, preview_url}], sorted with your own voices first."""
    try:
        r = requests.get(f"{API}/voices", headers=_headers(key), timeout=20)
    except requests.RequestException:
        raise VoiceError("Couldn't reach ElevenLabs. Check your internet connection.")
    _check(r)
    voices = [{"id": v["voice_id"], "name": v.get("name", "?"),
               "category": v.get("category", ""), "preview_url": v.get("preview_url")}
              for v in r.json().get("voices", [])]
    order = {"cloned": 0, "generated": 1, "professional": 2}
    return sorted(voices, key=lambda v: (order.get(v["category"], 3), v["name"].lower()))


def test_key(key: str) -> int:
    """Returns how many voices the key can see; raises VoiceError if it's bad."""
    return len(list_voices(key))


# --- narration ---------------------------------------------------------------
def _words_from_alignment(al: dict) -> list[Word]:
    words, cur, start, end = [], "", None, 0.0
    for ch, s, e in zip(al["characters"], al["character_start_times_seconds"],
                        al["character_end_times_seconds"]):
        if ch.isspace():
            if cur:
                words.append(Word(cur, start, end))
            cur, start = "", None
        else:
            if start is None:
                start = s
            cur += ch
            end = e
    if cur:
        words.append(Word(cur, start, end))
    return words


_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
         "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _say_number(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + "hundred" + ("" if n % 100 == 0 else "and" + _say_number(n % 100))
    if n < 10000 and n % 1000 and 1100 <= n < 2100:          # years: 1999 = nineteen ninety nine
        return _say_number(n // 100) + _say_number(n % 100)
    if n < 1_000_000:
        return _say_number(n // 1000) + "thousand" + ("" if n % 1000 == 0 else _say_number(n % 1000))
    return "".join(_ONES[int(d)] for d in str(n))


def spoken_letters(word: str) -> float:
    """Roughly how long a word takes to say, in letters ('14' -> 'fourteen' = 8).
    Pauses after commas and full stops count too."""
    core = re.sub(r"[^A-Za-z0-9.%$']", "", word)
    total = 0.0
    for part in re.findall(r"\d+|[A-Za-z']+|[.%$]", core):
        if part.isdigit():
            total += len(_say_number(int(part)) if len(part) < 7 else part * 5)
        elif part == ".":
            total += 3 if re.search(r"\d\.\d", core) else 0     # "1.5" -> "point"
        elif part == "%":
            total += 7
        elif part == "$":
            total += 6
        elif part.isupper() and len(part) <= 4 and part not in ("I", "A"):
            total += 3 * len(part)                                # "LMAO" spelled out
        else:
            total += len(part)
    total = max(total, 2)
    if re.search(r"[,;:]$", word):
        total += 4
    elif re.search(r"[.!?]$", word):
        total += 7
    return total


def estimate_words(text: str, start: float = 0.0) -> list[Word]:
    """Timings at a natural reading pace (used when the voice has no timestamps)."""
    words, t = [], start
    for w in text.split():
        dur = max(0.18, spoken_letters(w) / (5.0 * WORDS_PER_SECOND))
        words.append(Word(w, t, t + dur))
        t += dur
    return words


def speech_bounds(audio: Path) -> tuple[float, float] | None:
    """When the talking actually starts and stops in a recording (skips the
    silence voices leave at each end)."""
    import numpy as np

    from .engine import _tool, run_tool
    r = run_tool([_tool("ffmpeg"), "-v", "error", "-i", audio, "-ac", "1", "-ar",
                  "16000", "-f", "s16le", "-"], text=False)
    if r.returncode != 0 or len(r.stdout) < 3200:
        return None
    x = np.frombuffer(r.stdout, np.int16).astype(np.float32)
    win = 160                                            # 10 ms
    n = len(x) // win
    energy = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(1))
    loud = np.where(energy > max(energy.max() * 0.06, 120))[0]
    if len(loud) == 0:
        return None
    return loud[0] * win / 16000, (loud[-1] + 1) * win / 16000


def _fit_words(text: str, length: float, audio: Path | None = None) -> list[Word]:
    """Spread estimated word timings over a recording with no timestamps:
    over just the part where there's speech, sized by how long each word
    takes to say."""
    words = estimate_words(text)
    if not words or words[-1].end <= 0:
        return words
    a, b = 0.0, length
    if audio is not None:
        bounds = speech_bounds(audio)
        if bounds and bounds[1] - bounds[0] > 0.2:
            a, b = bounds
    k = (b - a) / words[-1].end
    return [Word(w.text, a + w.start * k, a + w.end * k) for w in words]


def _tag(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def _elevenlabs_line(text: str, voice_id: str, model: str,
                     prev: str, nxt: str) -> tuple[Path, list[Word]]:
    tag = _tag("el", voice_id, model, text)  # neighbours left out so edits don't re-charge
    mp3, meta = cache_dir() / f"{tag}.mp3", cache_dir() / f"{tag}.json"
    if mp3.exists() and meta.exists():
        return mp3, [Word(**w) for w in json.loads(meta.read_text(encoding="utf-8"))]
    body = {"text": text, "model_id": model}
    if prev:
        body["previous_text"] = prev   # keeps the tone flowing between lines
    if nxt:
        body["next_text"] = nxt
    try:
        r = requests.post(
            f"{API}/text-to-speech/{voice_id}/with-timestamps",
            params={"output_format": "mp3_44100_128"},
            headers={**_headers(), "Content-Type": "application/json"},
            json=body, timeout=180,
        )
    except requests.RequestException:
        raise VoiceError("Couldn't reach ElevenLabs. Check your internet connection.")
    _check(r)
    data = r.json()
    mp3.write_bytes(base64.b64decode(data["audio_base64"]))
    al = data.get("alignment") or data.get("normalized_alignment")
    words = _words_from_alignment(al) if al else _fit_words(text, get_duration(mp3), mp3)
    meta.write_text(json.dumps([w.__dict__ for w in words]), encoding="utf-8")
    return mp3, words


def _free_line(text: str, voice_id: str, status) -> tuple[Path, list[Word]]:
    from . import free_tts
    wav = cache_dir() / f"{_tag('free', voice_id, text)}.wav"
    if not wav.exists():
        tmp = wav.with_suffix(".tmp.wav")
        free_tts.synthesize(text, voice_id, tmp, status=status)
        tmp.replace(wav)
    return wav, _fit_words(text, get_duration(wav), wav)


def _custom_line(text: str, v: dict, status) -> tuple[Path, list[Word]]:
    from . import custom_voices
    tag = _tag("custom", v["id"], v.get("file", ""), v.get("url", ""), v.get("voice", ""),
               v.get("model", ""), v.get("a", ""), v.get("b", ""), v.get("mix", ""),
               v.get("pick", ""), text)
    wav = cache_dir() / f"{tag}.wav"
    if not wav.exists():
        tmp = wav.with_suffix(".tmp.wav")
        custom_voices.synthesize(v, text, tmp, status)
        tmp.replace(wav)
    return wav, _fit_words(text, get_duration(wav), wav)


def _join_audio(parts: list[Path], pause: float, out: Path):
    """Glue the line recordings together with `pause` seconds of silence between."""
    from .engine import _tool, run_tool
    cmd = [_tool("ffmpeg"), "-y", "-loglevel", "error"]
    for p in parts:
        cmd += ["-i", str(p)]
    chains, labels = [], ""
    for i in range(len(parts)):
        pad = f",apad=pad_dur={pause:.3f}" if i < len(parts) - 1 and pause > 0 else ""
        chains.append(f"[{i}:a]aresample=44100,aformat=sample_fmts=s16:channel_layouts=mono{pad}[a{i}]")
        labels += f"[a{i}]"
    graph = ";".join(chains) + f";{labels}concat=n={len(parts)}:v=0:a=1[out]"
    cmd += ["-filter_complex", graph, "-map", "[out]", str(out)]
    r = run_tool(cmd)
    if r.returncode != 0:
        raise VoiceError("Couldn't join the narration audio:\n" + r.stderr[-800:])


VOICE_LUFS = -16.0      # every voice is brought to about this loudness
VOICE_PEAK = -1.5       # ...without its peaks going over this (dBTP)


def loudness(audio: Path) -> tuple[float, float] | None:
    """(integrated loudness LUFS, true peak dBTP) of a recording, or None."""
    from .engine import _tool, run_tool
    r = run_tool([_tool("ffmpeg"), "-hide_banner", "-nostats", "-i", audio,
                  "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    try:
        d = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
        i, tp = float(d["input_i"]), float(d["input_tp"])
    except (ValueError, KeyError):
        return None
    return (i, tp) if i > -70 else None        # silence: nothing to level


def level_voice(src: Path, out: Path):
    """Copy of the narration at a steady loudness, so ElevenLabs, the free voices and
    your own voices all sit at the same level against the music. One fixed gain for
    the whole recording: nothing is squashed or pumped."""
    import shutil

    from .engine import _tool, run_tool
    m = loudness(src)
    gain = 0.0
    if m is not None:
        # a few dB of the sharpest peaks may be caught by a limiter; never more than 6
        gain = min(VOICE_LUFS - m[0], VOICE_PEAK - m[1] + 6.0, 12.0)
        gain = max(gain, -12.0)
    if abs(gain) < 0.3:
        shutil.copyfile(src, out)
        return
    chain = f"volume={gain:.2f}dB"
    if m is not None and m[1] + gain > VOICE_PEAK:
        ceiling = 10 ** (VOICE_PEAK / 20)
        chain += f",alimiter=limit={ceiling:.3f}:attack=3:release=60:level=0:latency=1"
    r = run_tool([_tool("ffmpeg"), "-y", "-loglevel", "error", "-i", src, "-af", chain, out])
    if r.returncode != 0:
        shutil.copyfile(src, out)


def _tempo(audio: Path, speed: float) -> Path:
    """The same recording sped up (or slowed down) without changing the pitch."""
    from .engine import _tool, run_tool
    out = cache_dir() / f"{_tag('tempo', audio.name, round(speed, 3))}.wav"
    if not out.exists():
        r = run_tool([_tool("ffmpeg"), "-y", "-loglevel", "error", "-i", audio,
                      "-filter:a", f"atempo={speed:.3f}", out])
        if r.returncode != 0:
            raise VoiceError("Couldn't change the voice speed:\n" + r.stderr[-400:])
    return out


def is_paid(voice_id: str) -> bool:
    """ElevenLabs (costs credits) as opposed to voices that run on your PC."""
    if voice_id in ("", NO_VOICE) or is_free(voice_id):
        return False
    if voice_id.startswith("custom:"):
        from . import custom_voices
        v = custom_voices.get(voice_id)
        return bool(v and v["kind"] == "elevenlabs")
    return True


def is_cached(text: str, voice_id: str, model: str) -> bool:
    """Every line of this ElevenLabs narration was made before (so it's free)."""
    if voice_id.startswith("custom:"):
        from . import custom_voices
        v = custom_voices.get(voice_id)
        voice_id = v["voice_id"] if v else voice_id
    for line in (l.strip() for l in text.splitlines() if l.strip()):
        tag = _tag("el", voice_id, model, line)
        if not (cache_dir() / f"{tag}.mp3").exists():
            return False
    return True


def estimate_length(text: str, pause: float, speed: float = 1.0) -> tuple[float, float]:
    """(total, speaking) seconds for a narration we haven't made yet."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    talk = sum(estimate_words(l)[-1].end for l in lines if l.split()) / max(speed, 0.1)
    return talk + pause * max(0, len(lines) - 1) + 0.3, talk


def is_free(voice_id: str) -> bool:
    return voice_id.startswith("free:")


def narrate(text: str, voice_id: str, model: str = "eleven_multilingual_v2",
            pause: float = 0.35,
            status: Callable[[str, float], None] = lambda m, f: None,
            speed: float = 1.0) -> Narration:
    """Read `text` aloud, one line at a time, with `pause` seconds between lines.

    Each line is cached on its own, so changing the pause (or editing one
    line) doesn't re-generate, or re-pay for, the rest.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        raise VoiceError("There's no text to read.")

    speed = min(max(float(speed or 1.0), 0.5), 2.0)
    if voice_id in ("", NO_VOICE):
        words, t, spans = [], 0.0, []
        for line in lines:
            lw = [Word(w.text, t + (w.start - t) / speed, t + (w.end - t) / speed)
                  for w in estimate_words(line, t)]
            words += lw
            spans.append((t, lw[-1].end))
            t = lw[-1].end + pause
        return Narration(None, words, t - pause + 0.3, spans)

    custom = None
    if voice_id.startswith("custom:"):
        from . import custom_voices
        custom = custom_voices.get(voice_id)
        if custom is None:
            raise VoiceError("That voice was removed. Pick another voice in step 4.")
    parts, words, t, spans = [], [], 0.0, []
    for i, line in enumerate(lines):
        status(f"Making the voice: line {i + 1} of {len(lines)}…", i / len(lines))
        if is_free(voice_id):
            audio, lw = _free_line(line, voice_id, status)
        elif custom is not None and custom["kind"] != "elevenlabs":
            audio, lw = _custom_line(line, custom, status)
        else:
            el_id = custom["voice_id"] if custom is not None else voice_id
            audio, lw = _elevenlabs_line(line, el_id, model,
                                         lines[i - 1] if i else "",
                                         lines[i + 1] if i + 1 < len(lines) else "")
        if abs(speed - 1.0) > 0.005:
            audio = _tempo(audio, speed)
            lw = [Word(w.text, w.start / speed, w.end / speed) for w in lw]
        length = get_duration(audio)
        words += [Word(w.text, w.start + t, w.end + t) for w in lw]
        spans.append((t, t + length))
        parts.append(audio)
        t += length + pause

    out = cache_dir() / f"{_tag('mix3', voice_id, model, pause, round(speed, 3), *lines)}.wav"
    if not out.exists():
        part = out.with_name(out.stem + "_raw.wav")
        _join_audio(parts, pause, part)
        level_voice(part, out)
        try:
            part.unlink()
        except OSError:
            pass
    return Narration(out, words, get_duration(out), spans)
