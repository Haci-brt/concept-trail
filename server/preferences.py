"""The writer's language choices, kept beside the provider settings.

ui_language is the interface (the page translates itself; the server keeps
it so every window opens in the same language); assistant_language is what
the model writes in — questions, suggestions, answers, text for the note.
"""
import json
from pathlib import Path

from server.errors import ApiError
from server.providers import config_dir
from server.store import read_json

LANGUAGES = ("tr", "en", "de", "es", "fr")
DEFAULTS = {"ui_language": "tr", "assistant_language": "tr"}
# yes/no choices: setup_dismissed — the writer closed the first-start wizard,
# so it does not open by itself again (it stays one click away)
FLAGS = {"setup_dismissed": False}


class Preferences:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "preferences.json"
        self.data = {**DEFAULTS, **FLAGS}
        stored = read_json(self.path) or {}     # a damaged file is set aside, not overwritten
        for key in DEFAULTS:
            if stored.get(key) in LANGUAGES:
                self.data[key] = stored[key]
        for key in FLAGS:
            if isinstance(stored.get(key), bool):
                self.data[key] = stored[key]

    def public(self) -> dict:
        return {**self.data, "languages": list(LANGUAGES)}

    def update(self, changes: dict) -> dict:
        unknown = set(changes) - set(DEFAULTS) - set(FLAGS)
        if unknown:
            raise ApiError(400, f"Bilinmeyen ayar: {', '.join(sorted(unknown))}")
        for key, value in changes.items():
            if key in FLAGS:
                if not isinstance(value, bool):
                    raise ApiError(400, "Bu ayar evet ya da hayır olmalı.")
            elif value not in LANGUAGES:
                raise ApiError(400, "Bilinmeyen dil.")
            self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return self.public()
