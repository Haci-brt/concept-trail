"""The master prompt: everything known about a note, written up as build
instructions that leave nothing open — and kept with the note."""
import json

import pytest

from core import llm_client
from server.assistant import Assistant
from server.masterprompt import MasterPrompts, research_digest
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

NOTE = "---\netiket: [tarif]\n---\n# Aile tarif defteri\n\nWeb'den tarif içe aktarma ve haftalık plan.\n"


class Broker:
    def publish(self, kind, data):
        pass


class FakeProvider:
    label = "Test"
    model = "test/model"


@pytest.fixture
def master(tmp_path):
    vault = Vault(tmp_path / "vault")
    assistant = Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                          ProviderRegistry(path=tmp_path / "providers.json"))
    assistant.provider_for = lambda role, rel=None: FakeProvider()
    return MasterPrompts(vault, assistant.notes, assistant)


def add(master, rel, kind, text, **fields):
    return master.notes.add_node(rel, kind, text, **fields)


# ---------------------------------------------------------------- what goes in
def test_the_material_holds_the_note_the_decisions_and_the_conversations(master):
    rel = master.vault.create_note("", "tarif", NOTE)
    answered = add(master, rel, "question", "Plan hangi gün başlar?", status="resolved")
    add(master, rel, "chat-user", "Pazartesi.", parent_id=answered["id"])
    add(master, rel, "summary", "Plan pazartesi başlar, günde iki öğün.", parent_id=answered["id"], status="approved")
    add(master, rel, "question", "Çocuklar tarif düzenleyebilsin mi?", status="open")
    add(master, rel, "question", "Eski soru", status="dismissed")
    add(master, rel, "summary", "Tarifler blokzincirde saklansın.", status="rejected")

    material, stats = master.material(rel)

    assert "etiket:" not in material                       # frontmatter is not the design
    assert "Web'den tarif içe aktarma" in material
    assert "[KARARLAR]" in material
    assert "Sonuç: Plan pazartesi başlar" in material      # the approved outcome, not the chat
    assert "[CEVAP BEKLEYEN SORULAR — kararı sen ver" in material
    assert "Çocuklar tarif düzenleyebilsin mi?" in material
    assert "Eski soru" not in material
    assert "bunları yapma]\n- Tarifler blokzincirde saklansın." in material
    assert stats == {"made": 0, "total": 15, "phase": "kapsam", "phase_label": "Kapsam",
                     "waiting": 1, "answered": 1, "research": False}


def test_unsaved_text_from_the_editor_wins_over_the_file(master):
    rel = master.vault.create_note("", "tarif", NOTE)
    material, _ = master.material(rel, "# Aile tarif defteri\n\nYeni cümle.\n")
    assert "Yeni cümle." in material and "haftalık plan" not in material


def test_research_is_background_only_when_it_finished():
    assert research_digest({"status": "running"}) == ""
    digest = research_digest({
        "status": "done", "verdict": {"verdict": "Mealie ve Tandoor benzer."},
        "deep": {"projects": [{"repo": "mealie-recipes/mealie", "stars": 9000, "summary": "Tarif yöneticisi.",
                               "weak": ["İçe aktarma bazı sitelerde bozuk"]}],
                 "arguments": [{"text": "İçe aktarmada önizleme göster."}]},
        "tools": [{"name": "recipe-scrapers", "why": "Yüzlerce siteden tarif okur.", "recommended": True},
                  {"name": "başka", "why": "önerilmedi", "recommended": False}],
    })
    assert "Rakip mealie-recipes/mealie (9000 yıldız): Tarif yöneticisi. Zayıf yanları: İçe aktarma" in digest
    assert "Rakipten ders: İçe aktarmada önizleme göster." in digest
    assert "recipe-scrapers" in digest and "başka" not in digest


# ---------------------------------------------------------------- nothing open
def test_open_lines_are_found_but_quoted_ui_copy_and_code_are_not():
    text = "\n".join([
        "# Yapım talimatı",                           # 0
        "## Veri",                                    # 1
        "- Hangi veritabanı kullanılacak?",           # 2  a question
        '- Silme onayı: "Tarif silinsin mi?"',        # 3  UI copy
        "- Kimlik doğrulama yöntemi: TBD",            # 4  put off
        "```",                                        # 5
        "curl localhost:8000/ara?q=un",               # 6
        "```",                                        # 7
        "- Yedekleme sonra karar verilecek.",         # 8  put off
        "- Veritabanı: SQLite 3.45.",                 # 9
        "- Dağıtım yöntemi kullanıcıya sorulmalı.",   # 10 put off
    ])
    assert llm_client.unresolved_lines(text) == [2, 4, 8, 10]


def test_the_fix_pass_replaces_only_the_lines_it_was_asked_about(monkeypatch):
    text = "## Veri\n  - Hangi veritabanı?\n- Önbellek: Redis.\n"
    monkeypatch.setattr(llm_client, "_complete", lambda *a, **k:
                        "1: - Veritabanı: SQLite 3.45 — tek dosya, kurulum istemez.\n2: - Önbellek yok.")
    fixed, count = llm_client.fix_master_prompt(text)
    assert count == 1
    assert fixed.splitlines() == ["## Veri", "  - Veritabanı: SQLite 3.45 — tek dosya, kurulum istemez.",
                                  "- Önbellek: Redis."]


def test_nothing_open_costs_no_second_call(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("no call expected")
    monkeypatch.setattr(llm_client, "_complete", fail)
    assert llm_client.fix_master_prompt("## A\n- Tamam.") == ("## A\n- Tamam.", 0)


def test_the_models_own_decisions_are_listed_from_their_section():
    text = ("## 17. Bitti sayılma ölçütü\n- Testler geçer.\n## 18. Varsayımlar\n"
            "- Karar: SQLite — Neden: tek kullanıcı.\n1. Karar: FastAPI — Neden: notta Python var.\n")
    assert llm_client.master_assumptions(text) == ["Karar: SQLite — Neden: tek kullanıcı.",
                                                   "Karar: FastAPI — Neden: notta Python var."]
    assert llm_client.master_assumptions("## 18. Assumptions\n* Decision: SQLite") == ["Decision: SQLite"]
    assert llm_client.master_assumptions("## Varsayımlar\n- **Karar:** SQLite — **Neden:** tek dosya.") == [
        "Karar: SQLite — Neden: tek dosya."]


def test_a_reply_wrapped_whole_in_a_code_block_is_unwrapped(monkeypatch):
    monkeypatch.setattr(llm_client, "_complete", lambda *a, **k: "```markdown\n# Başlık\n\nMetin\n```")
    assert llm_client.master_prompt("malzeme") == "# Başlık\n\nMetin"


# ---------------------------------------------------------------- the stream
@pytest.mark.anyio
async def test_the_prompt_streams_then_is_kept_with_the_note(master, monkeypatch):
    rel = master.vault.create_note("", "tarif", NOTE)
    body = "# Tarif — Yapım talimatı\n" + "\n".join(f"## {i}. Bölüm\n- Madde {i}." for i in range(18))
    body += "\n## 18. Varsayımlar\n- Karar: SQLite — Neden: tek kullanıcı.\n- Hangi port?"
    seen = {}

    def write(material, language, provider, on_chunk, on_usage):
        seen["language"] = language
        on_chunk(body[:40])
        return body

    monkeypatch.setattr(llm_client, "master_prompt", write)
    monkeypatch.setattr(llm_client, "_complete", lambda *a, **k: f"{len(body.splitlines()) - 1}: - Port: 8000.")

    updates = [u async for u in master.stream(rel, "en")]

    kinds = [u["type"] for u in updates]
    assert kinds[0] == "start" and "done" == kinds[-1] and "checking" in kinds
    assert updates[0]["provider"] == "Test · test/model"
    done = updates[-1]
    assert seen["language"] == "en"
    assert done["text"].endswith("- Port: 8000.") and done["fixed"] == 1 and done["open"] == 0
    assert done["assumptions"] == ["Karar: SQLite — Neden: tek kullanıcı.", "Port: 8000."]
    assert done["sections"] == 19
    assert master.last(rel)["text"] == done["text"]          # there again without paying twice
    assert rel not in master.running


@pytest.mark.anyio
async def test_a_second_press_while_writing_is_refused(master):
    rel = master.vault.create_note("", "tarif", NOTE)
    master.running.add(rel)
    updates = [u async for u in master.stream(rel)]
    assert updates == [{"type": "error", "message": "Bu not için master prompt zaten hazırlanıyor."}]


def test_the_master_role_follows_the_research_judgements_until_bound(tmp_path):
    base = {"label": "OpenRouter", "base_url": "https://openrouter.ai/api", "kind": "remote", "health": "models"}
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({"providers": [{**base, "id": "mini", "model": "openai/gpt-4o-mini"},
                                              {**base, "id": "deep", "model": "deepseek/deepseek-v4-flash"}],
                                "roles": {"analysis": ["mini"], "compare": ["deep", "mini"]}}), encoding="utf-8")
    reg = ProviderRegistry(path)
    assert reg.roles["master"] == ["deep", "mini"]


def test_the_long_call_asks_openrouter_for_its_fastest_host_and_nothing_else():
    from server.providers import Provider
    routed = llm_client.fastest_route(Provider(id="or", label="OpenRouter", base_url="https://openrouter.ai/api",
                                               model="deepseek/deepseek-v4-flash", extras={"reasoning": {"enabled": False}}))
    assert routed.id == "or" and routed.model == "deepseek/deepseek-v4-flash"
    assert routed.extras == {"reasoning": {"enabled": False}, "provider": {"sort": "throughput"}}
    chosen = Provider(id="or", label="OpenRouter", base_url="https://openrouter.ai/api", extras={"provider": {"order": ["x"]}})
    assert llm_client.fastest_route(chosen) is chosen          # someone configured routing: left alone
    local = Provider(id="yerel", label="Yerel", base_url="http://127.0.0.1:8899")
    assert llm_client.fastest_route(local) is local
