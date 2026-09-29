"""The sample vault: one note for each thing worth trying.

A note already there is never overwritten — what you wrote while testing
stays until the environment is reset (python -m testkit --sifirla).
"""
import json
import random
from datetime import datetime
from pathlib import Path

NOTES = {
    "Beni oku.md": """# Test ortamına hoş geldin

Bu kasa yalnız deneme için; gerçek notların ve ayarların etkilenmez. Yanıtları sahte bir
model veriyor: anahtar, ücret ve internet gerekmez (araştırma hariç).

Her notun ne için olduğu:

- **Bitki hatırlatıcı** — karar merdiveni: Ctrl+Enter'a bas, sağda sorular çıksın; birine cevap ver.
- **Harcama takibi** — kapsamı büyük ölçüde verilmiş bir not: merdiven mimari basamağında.
- **Kitap takası** — `tur: fikir` notu: karar merdiveni yerine merak soruları.
- **Expense tracker** — İngilizce not: dil ayarını İngilizceye alıp dene.
- **Maaş planı** — `gizli: true` notu: uzak modellere hiç gitmez.
- **Uzun not** — 25 bin karakter: yazarken takılma var mı?
- **Büyük ağaç** — 120 düğümlü fikir ağacı: yakınlaş, uzaklaş, kaydır, yıldız sürükle.

Adım adım kontrol listesi: depodaki docs/TEST.md.
""",
    "Bitki hatırlatıcı.md": """# Bitki hatırlatıcı

Bitkilerimi sulamayı sürekli unutuyorum. Bana zamanı gelince haber veren basit bir şey istiyorum.
""",
    "Harcama takibi.md": """# Harcama takibi

Fişleri fotoğrafla çeken bir telefon uygulaması yapmak istiyorum. Ailem de kullanacak.
İnternet yokken de çalışmalı, veriler telefonda dursun.

## Mimari

İstemci React Native ile yazılacak, ayrı bir sunucu olmayacak. Veriler telefondaki SQLite'ta
duracak. Yedek için Google Drive'a bağlanacak.
""",
    "Kitap takası.md": """---
tur: fikir
---
# Kitap takası

Apartmanın girişine bir raf koymak istiyorum: herkes okuduğu kitabı bırakır, istediğini alır.
Kitaplar bir deftere yazılsın; kim ne getirdi, kim ne aldı. Çocuk kitapları için ayrı bir köşe olsun.
""",
    "Expense tracker.md": """# Expense tracker

I want to build a phone app that photographs receipts. My family will use it too.
It must work without internet, and the data should stay on the phone.
""",
    "Maaş planı.md": """---
gizli: true
---
# Maaş planı

Bu not gizli: asistan onu yalnız bu bilgisayarda çalışan bir modele gösterir, araştırılmaz.
Aylık gelirimi ve sabit giderlerimi bir tabloda toplamak istiyorum.
""",
}

LONG_SECTION = ("## Bölüm {i}\n\nBu bölüm uygulamanın {i}. parçasını anlatıyor: kullanıcı bir fiş fotoğrafı çeker, "
                "uygulama tutarı ve tarihi okur, kategoriye ayırır ve aylık özete ekler. Aile üyeleri kendi "
                "harcamalarını ayrı görür; ortak harcamalar paylaşılır.\n\n- madde bir\n- madde iki\n\n")


def _big_tree(count: int = 120, seed: int = 5) -> dict:
    """A note's worth of questions, answers, chats and proposals — enough stars
    to try the tree at scale."""
    rnd = random.Random(seed)
    now = datetime.now().isoformat(timespec="seconds")
    nodes, questions = [], []
    kinds = ["derinlestirme", "alternatif", "sonuc", "kapsam", "ilham"]
    for i in range(count):
        roll = rnd.random()
        if roll < 0.55 or not questions:
            parent = rnd.choice(questions)["id"] if questions and rnd.random() < 0.6 else None
            node = {"id": f"q{i}", "parentId": parent, "type": "question", "created": now,
                    "text": f"Bölüm {i % 40} nasıl çalışacak, kim kullanacak?", "section": f"Bölüm {i % 40}",
                    "status": rnd.choice(["open", "resolved", "resolved"]), "kind": rnd.choice(kinds)}
            questions.append(node)
        elif roll < 0.8:
            node = {"id": f"c{i}", "parentId": rnd.choice(questions)["id"], "created": now,
                    "type": rnd.choice(["chat-user", "chat-assistant"]), "text": f"Sohbet mesajı {i}"}
        else:
            node = {"id": f"s{i}", "parentId": rnd.choice(questions)["id"], "type": "summary", "created": now,
                    "text": f"Nota eklenecek öneri {i}", "status": rnd.choice(["pending", "approved"])}
        nodes.append(node)
    return {"version": 2, "counter": count, "nodes": nodes, "analyzed_text": "", "last_question": "",
            "direction": None, "direction_history": []}


def seed_vault(vault: Path) -> list[str]:
    """Write the sample notes that are missing; return their names."""
    vault = Path(vault)
    vault.mkdir(parents=True, exist_ok=True)
    written = []
    notes = dict(NOTES)
    notes["Uzun not.md"] = "# Uzun not\n\n" + "".join(LONG_SECTION.format(i=i) for i in range(1, 121))
    tree_text = "---\ntur: fikir\n---\n# Büyük ağaç\n\n" + "".join(
        f"## Bölüm {i}\n\nBu bölümde fikrin {i}. parçası konuşuluyor.\n\n" for i in range(40))
    notes["Büyük ağaç.md"] = tree_text
    for name, text in notes.items():
        path = vault / name
        if not path.exists():
            path.write_text(text, encoding="utf-8")
            written.append(name)
    state = vault / ".assistant" / "notes" / "Büyük ağaç.md.json"
    if not state.exists():
        state.parent.mkdir(parents=True, exist_ok=True)
        tree = _big_tree()
        tree["analyzed_text"] = tree_text
        state.write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
    return written


def bind_fake_model(config_base: Path, base_url: str) -> Path:
    """Point every job of the app at the stand-in model (under
    FIKIR_CONFIG_DIR=config_base); return the providers file."""
    from server.providers import ROLES
    path = Path(config_base) / "ConceptTrail" / "providers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"providers": [{"id": "sahte", "label": "Sahte model (test)", "base_url": base_url, "model": "sahte-model",
                           "kind": "local", "health": "models", "timeout": 30.0}],
            "roles": {role: ["sahte"] for role in ROLES}}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
