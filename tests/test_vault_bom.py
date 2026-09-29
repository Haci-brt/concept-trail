"""A note saved with a byte-order mark (some Windows editors write one) keeps
its frontmatter — above all `gizli: true`, which keeps it off remote models."""
from server.assistant import Assistant
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault, split_frontmatter


class Broker:
    def publish(self, *args):
        pass


def test_a_bom_does_not_hide_the_frontmatter(tmp_path):
    vault = Vault(tmp_path / "vault")
    (vault.root / "gizli.md").write_bytes("﻿---\ngizli: true\ntur: fikir\n---\n# Maaş planı\n".encode("utf-8"))
    note = vault.read_note("gizli.md")
    assert note["content"].startswith("---")
    assert split_frontmatter(note["content"])[0].get("tur") == "fikir"
    assistant = Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                          ProviderRegistry(path=tmp_path / "providers.json"))
    assert assistant.is_private("gizli.md") is True
