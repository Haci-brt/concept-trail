"""The writer's language choices, kept beside the provider settings.

ui_language is the interface (the page translates itself; the server keeps
it so every window opens in the same language); assistant_language is what
the model writes in — questions, suggestions, answers, text for the note.
"""
import json
from pathlib import Path

from server.errors import ApiError
from server.providers import config_dir

LANGUAGES = ("tr", "en", "de", "es", "fr")
DEFAULTS = {"ui_language": "tr", "assistant_language": "tr"}


class Preferences:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "preferences.json"
        self.data = dict(DEFAULTS)
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        for key in DEFAULTS:
            if stored.get(key) in LANGUAGES:
                self.data[key] = stored[key]

    def public(self) -> dict:
        return {**self.data, "languages": list(LANGUAGES)}

    def update(self, changes: dict) -> dict:
        unknown = set(changes) - set(DEFAULTS)
        if unknown:
            raise ApiError(400, f"Bilinmeyen ayar: {', '.join(sorted(unknown))}")
        for key, value in changes.items():
            if value not in LANGUAGES:
                raise ApiError(400, "Bilinmeyen dil.")
            self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return self.public()
