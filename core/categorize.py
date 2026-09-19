"""Icon/label lookup for assistant events, used by the history panel."""

_BY_TYPE = {
    "question": ("❓", "Soru"),
    "edit": ("✏️", "Düzenleme Önerisi"),
    "resolved": ("✅", "Tamamlandı"),
    "checked": ("👁️", "İncelendi"),
}


def icon_and_label(event: dict) -> tuple[str, str]:
    return _BY_TYPE.get(event.get("type"), ("💡", "Not"))
