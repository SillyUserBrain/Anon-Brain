"""Text cleanup: turns internet shorthand into words the AI voice can read.

The table is fully editable in Settings. It's saved per user in
%APPDATA%\\AnonBrain\\cleanup.json.
"""

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .settings import data_dir, write_json

STARTER = [
    ("tfw", "that feeling when"), ("mfw", "my face when"), ("mrw", "my reaction when"),
    ("tfw no gf", "that feeling when no girlfriend"), ("be me", "be me"),
    ("op", "O P"), ("anon", "anon"), ("kek", "kek"), ("lel", "lel"),
    ("lol", "lol"), ("lmao", "lmao"), ("lmfao", "lmao"), ("rofl", "rolling on the floor laughing"),
    ("ngl", "not gonna lie"), ("tbh", "to be honest"), ("tbf", "to be fair"),
    ("imo", "in my opinion"), ("imho", "in my humble opinion"), ("iirc", "if I remember correctly"),
    ("afaik", "as far as I know"), ("idk", "I don't know"), ("idc", "I don't care"),
    ("ikr", "I know right"), ("irl", "in real life"), ("smh", "shaking my head"),
    ("fml", "f my life"), ("wtf", "what the f"), ("omg", "oh my god"), ("btw", "by the way"),
    ("fyi", "for your information"), ("rn", "right now"), ("af", "as heck"),
    ("ffs", "for f's sake"), ("jfc", "jesus f christ"), ("nvm", "never mind"),
    ("pls", "please"), ("plz", "please"), ("thx", "thanks"), ("ty", "thank you"),
    ("np", "no problem"), ("bc", "because"), ("cuz", "because"), ("w/", "with"),
    ("w/o", "without"), ("gf", "girlfriend"), ("bf", "boyfriend"), ("bff", "best friend"),
    ("mc", "main character"), ("npc", "N P C"), ("irl", "in real life"),
    ("aita", "am I the a-hole"), ("wibta", "would I be the a-hole"), ("nta", "not the a-hole"),
    ("yta", "you're the a-hole"), ("esh", "everyone sucks here"), ("tifu", "today I f'd up"),
    ("tl;dr", "too long didn't read"), ("tldr", "too long didn't read"), ("edit:", "edit:"),
    ("eta", "edited to add"), ("ama", "ask me anything"), ("eli5", "explain like I'm five"),
    ("til", "today I learned"), ("dm", "D M"), ("dms", "D Ms"), ("pm", "P M"),
    ("uni", "uni"), ("hs", "high school"), ("gpa", "G P A"), ("wfh", "work from home"),
    ("mil", "mother in law"), ("sil", "sister in law"), ("bil", "brother in law"),
    ("so", "so"), ("s/o", "significant other"), ("ex", "ex"), ("tho", "though"),
    ("ur", "your"), ("u", "you"), ("ok", "okay"),
    ("hbu", "how about you"), ("wyd", "what are you doing"),
    ("gg", "good game"), ("ez", "easy"), ("afk", "away from keyboard"), ("brb", "be right back"),
]
# Entries where the word is ambiguous in normal English are kept out of the
# starter list by mapping them to themselves (e.g. "so", "ex", "uni").
STARTER = [(s, f) for s, f in STARTER if s != f]
# de-duplicate, keeping the first
_seen = set()
STARTER = [(s, f) for s, f in STARTER if not (s in _seen or _seen.add(s))]


@dataclass
class Entry:
    short: str
    full: str
    created: float


class CleanupTable:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "cleanup.json"
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.entries = self._dedupe([Entry(**e) for e in raw])
        except (OSError, ValueError, TypeError):
            self.entries = self.starter()
            self.save()

    @staticmethod
    def starter() -> list[Entry]:
        base = 1_700_000_000.0
        return [Entry(s, f, base + i) for i, (s, f) in enumerate(STARTER)]

    @staticmethod
    def _key(short: str) -> str:
        return " ".join(short.lower().split())

    def _dedupe(self, entries: list[Entry]) -> list[Entry]:
        """Keep the first entry for each shorthand (case-insensitive)."""
        seen, out = set(), []
        for e in entries:
            k = self._key(e.short)
            if k and k in seen:
                continue
            if k:
                seen.add(k)
            out.append(e)
        return out

    def find(self, short: str, exclude: Entry | None = None) -> Entry | None:
        """Existing entry with this shorthand (ignoring case and extra spaces)."""
        k = self._key(short)
        if not k:
            return None
        for e in self.entries:
            if e is not exclude and self._key(e.short) == k:
                return e
        return None

    def save(self):
        write_json(self.path, [asdict(e) for e in self.entries], indent=1)

    def add(self, short: str = "", full: str = "") -> Entry:
        e = Entry(short, full, time.time())
        self.entries.append(e)
        return e

    def sorted(self, mode: str = "newest") -> list[Entry]:
        if mode == "az":
            return sorted(self.entries, key=lambda e: e.short.lower())
        return sorted(self.entries, key=lambda e: e.created, reverse=True)

    def reset_to_starter(self):
        self.entries = self.starter()
        self.save()

    def apply(self, text: str) -> str:
        """Text the voice will actually read."""
        out_lines = []
        for line in text.splitlines():
            line = re.sub(r">>\d+", "", line)               # reply links
            line = re.sub(r"https?://\S+", "", line)         # links
            line = re.sub(r"^\s*>+\s*", "", line)            # greentext arrows
            if not line.strip():
                continue
            out_lines.append(line.strip())
        out = "\n".join(out_lines)

        # One pass, longest shorthand first ("tfw no gf" wins over "tfw"),
        # so a replacement is never expanded a second time.
        table = {self._key(e.short): e.full.strip() for e in self.entries
                 if self._key(e.short) and e.full.strip()}
        if not table:
            return out
        alts = sorted(table, key=len, reverse=True)
        pattern = r"(?<![\w'])(" + "|".join(
            r"\s+".join(re.escape(w) for w in k.split()) for k in alts) + r")(?![\w'])"
        return re.sub(pattern, lambda m: table[self._key(m.group(1))], out, flags=re.IGNORECASE)
