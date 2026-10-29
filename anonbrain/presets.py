"""Saved looks ("My TikTok style"): layout, style, reveal, voice, music and brand.

Stored in %APPDATA%\\AnonBrain\\presets.json as {name: {setting: value}}.
Applying one copies its values into the settings; the pages then reload.
"""

import json
import time

from .settings import DEFAULTS, data_dir, write_json

KEYS = [
    # layout + style
    "format", "resolution", "fps", "mirror", "fit", "game_volume", "layouts", "post_round", "post_shadow", "post_shadow_strength",
    "post_border", "post_border_width", "post_border_style", "post_border_color",
    # post
    "reveal", "reveal_style", "hook_spoken", "reddit_theme", "post_display", "captions",
    # voice + music
    "last_voice_id", "line_pause", "voice_speed", "voice_volume", "music_volume", "last_music", "music_start",
    "music_mode", "music_folder", "repeat_songs",
    "target_platform", "min_length",
    # brand
    "watermark", "endcard", "brand_pos",
    # gameplay
    "skip_boring", "reuse_footage",
]


class Presets:
    def __init__(self):
        self.path = data_dir() / "presets.json"
        try:
            self.items: dict = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.items = {}

    def _save(self):
        write_json(self.path, self.items, indent=2)

    def names(self) -> list[str]:
        return sorted(self.items, key=lambda n: -self.items[n].get("_saved", 0))

    def get(self, name: str) -> dict | None:
        p = self.items.get(name)
        return {k: v for k, v in p.items() if not k.startswith("_")} if p else None

    def save(self, name: str, settings) -> str:
        name = name.strip() or "My preset"
        self.items[name] = {k: settings[k] for k in KEYS} | {"_saved": time.time()}
        self._save()
        return name

    def delete(self, name: str):
        self.items.pop(name, None)
        self._save()

    def rename(self, old: str, new: str) -> str:
        new = new.strip()
        if new and old in self.items and new != old:
            self.items[new] = self.items.pop(old)
            self._save()
        return new or old

    def apply(self, name: str, settings) -> bool:
        p = self.get(name)
        if p is None:
            return False
        settings.values.update(p)
        settings.save()
        return True


class Values:
    """Settings with a preset laid over them (read-only, same [] access)."""

    def __init__(self, settings, preset: dict | None):
        self.values = {**settings.values, **(preset or {})}

    def __getitem__(self, key):
        return self.values.get(key, DEFAULTS.get(key))
