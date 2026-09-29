"""A stand-in model: the OpenAI chat-completions shape, answered without a model.

Concept Trail gives each job its own system prompt; this reads which job a
request is from that prompt and answers in the form the job's parser expects:
decision-ladder lines drawn from the note itself, curiosity questions, a chat
that understands a full answer and asks again on a short one, text for the
note, the rest of a line, a master prompt with every section, a course
correction plan. It is predictable rather than clever — which is what a test
wants, and enough to click through every screen of the app.

    model = FakeModel(delay=0.3).start()      # model.base_url -> http://127.0.0.1:<port>
    ...
    model.stop()
"""
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from server import ladder
from server.vault import fold

MODEL_ID = "sahte-model"

# phrases that settle a decision when the note has them; the value given back
# is the note's own sentence, so the app's grounding check accepts it
KNOWN = {
    "kullanici": ("ailem", "sadece ben", "yalnızca ben", "ekip", "herkes", "my family", "only i ", "only me",
                  "familie", "nur ich"),
    "platform": ("telefon", "web", "tarayıcı", "masaüstü", "phone app", "browser", "desktop", "handy", "app"),
    "calisma": ("internet yokken", "çevrimdışı", "bulut", "sunucu", "without internet", "offline", "cloud",
                "server", "ohne internet"),
    "parcalar": ("react native", "istemci", "client"),
    "veri": ("sqlite", "veritaban", "database", "veriler"),
    "iletisim": ("senkron", "eşitle", "sync"),
    "dis": ("google drive", "api", "dropbox"),
}
LEADS = {"LANGUAGE:": "en", "SPRACHE:": "de", "IDIOMA:": "es", "LANGUE :": "fr"}
CONTINUE = {"tr": " ve bunu olabildiğince sade tutar.", "en": " and keeps it as simple as possible.",
            "de": " und hält es so einfach wie möglich.", "es": " y lo mantiene lo más simple posible.",
            "fr": " et le garde aussi simple que possible."}
SEARCH_TERMS = (
    (("bitki", "sula", "plant"), "plant watering reminder, houseplant care, watering schedule",
     "plant-care, reminder, gardening", "reminders, notifications, schedules", "An app that reminds you to water your plants."),
    (("harcama", "fiş", "expense", "receipt"), "expense tracker, receipt scanner, family budget",
     "expense-tracker, receipt-scanner, budgeting", "receipt OCR, offline storage, family sharing",
     "A phone app that scans receipts to track family expenses."),
    (("kitap", "book"), "book swap, community library, book exchange", "book-exchange, library, community",
     "catalog, lending log", "A neighbourhood shelf for swapping books."),
)
SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
# words too common to ask about
FILLER = {"istiyorum", "olacak", "olsun", "yapmak", "olmalı", "kullanacak", "herkes", "bunun", "şeyin", "kadar",
          "because", "should", "would", "which", "there", "their", "about", "möchte", "werden"}


def language_of(system: str) -> str:
    for lead, code in LEADS.items():
        if lead in system[:400]:
            return code
    return "tr"


def note_sentences(text: str) -> list[str]:
    """The note's sentences, without frontmatter, headings and list marks."""
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        line = re.sub(r"^[-*+]\s+|^\d+[.)]\s+", "", line)
        out += [s.strip() for s in SENTENCE.findall(line) if len(s.strip()) > 3]
    return out


def ladder_reply(user: str, lang: str) -> str:
    """One line per open decision: the note's own sentence where the note
    says it, else the rung's question."""
    match = re.search(r"AÇIK KARARLAR[^:]*:\s*(.+)", user)
    if not match:
        return "NET"
    open_ids = [d.strip() for d in match.group(1).split(",") if d.strip()]
    note = user.split("[YOL HARİTASI]", 1)[0]
    sentences = note_sentences(note)
    lines = []
    for decision in open_ids:
        value = None
        if decision == "amac" and sentences:
            value = sentences[0]
        for phrase in KNOWN.get(decision, ()):
            found = next((s for s in sentences if fold(phrase) in fold(s)), None)
            if found:
                value = found
                break
        lines.append(f"{decision}: {value.rstrip('.')}" if value else f"{decision}: {ladder.ask(decision, lang)}")
    return "\n".join(lines)


# a line of [MEVCUT SORU DALLARI] about a question the writer has answered:
# its id, and the rest of the line (the question, then the answer)
ANSWERED_BRANCH = re.compile(r"^- ([A-Za-z0-9_-]+)(?: \(üst soru: [^)]*\))? \[cevaplandı[^\]]*\]: (.*)$", re.M)


def idea_reply(user: str, lang: str) -> str:
    """Two curiosity questions about words the writer just wrote — and, as the
    real models did (kaan.md), a third that digs into the latest answer,
    naming the question it follows up. Whether that one is asked is the
    server's call: once per question, never below a follow-up."""
    part = user.split("[YENİ EKLENEN]", 1)[-1]
    words = sorted({w.strip(".,;:!?()«»\"'") for w in part.split() if len(w) >= 5} - FILLER, key=len, reverse=True)
    first, second = (words + ["bu fikir", "bu fikir"])[:2]
    answered = ANSWERED_BRANCH.findall(user.split("[YENİ EKLENEN]", 1)[0])
    follow = ""
    if answered:
        branch, rest = answered[-1]
        said = rest.split("Kullanıcının son yanıtı:", 1)[-1].split(" | ", 1)[0]
        detail = max((w.strip(".,;:!?()«»\"'") for w in said.split()), key=len, default="") or "bu"
        follow = (f"\nSORU[derinlestirme][{branch}]: «{detail}» dediğin şeyin ayrıntısı tam olarak ne olacak?"
                  if lang == "tr" else
                  f"\nSORU[derinlestirme][{branch}]: When you said “{detail}”, what exactly would the detail be?")
    if lang == "tr":
        return (f"SORU[derinlestirme]: «{first}» dediğin şeyi bir adım öteye taşısan ilk neyi değiştirirdin?\n"
                f"SORU[alternatif]: «{second}» yerine bambaşka bir yol seçseydin ne olurdu?{follow}")
    return (f"SORU[derinlestirme]: If you took “{first}” one step further, what would change first?\n"
            f"SORU[alternatif]: What if you chose a different path instead of “{second}”?{follow}")


def master_reply(user: str) -> str:
    """Every section of the build brief, with a decision or two in each."""
    title = (re.search(r"^#\s+(.+)$", user, re.M) or [None, "Uygulama"])[1].strip()
    sections = ["0. Ajan için çalışma kuralları", "1. Ürün özeti", "2. Kullanıcılar ve temel senaryolar",
                "3. Kapsam (bu sürümde var / yok)", "4. Platform ve çalışma ortamı", "5. Teknoloji yığını",
                "6. Mimari", "7. Veri modeli", "8. Arayüzler ve API sözleşmeleri", "9. Ekranlar ve kullanıcı akışları",
                "10. Hata durumları ve uç durumlar", "11. Güvenlik, gizlilik ve yapılandırma", "12. Klasör yapısı",
                "13. Uygulama planı (kilometre taşları)", "14. Test planı ve kabul kriterleri",
                "15. Kurulum, çalıştırma ve dağıtım", "16. Kodlama kuralları", "17. Bitti sayılma ölçütü"]
    out = [f"# {title} — Yapım talimatı", ""]
    for section in sections:
        out += [f"## {section}", "", f"- {title} için bu bölümde en sade ve yaygın seçim uygulanır.", ""]
    out += ["## 18. Varsayımlar (notta olmayan, senin verdiğin kararlar)", "",
            "- Karar: Veriler cihazda SQLite ile tutulur — Neden: notta sunucu istenmiyor.",
            "- Karar: Arayüz tek ekranla başlar — Neden: ilk sürüm en küçük çalışan hâl olmalı."]
    return "\n".join(out)


def search_terms_reply(user: str) -> str:
    text = fold(user)
    for keys, anahtar, konu, bilesen, ozet in SEARCH_TERMS:
        if any(fold(k) in text for k in keys):
            break
    else:
        anahtar, konu, bilesen, ozet = ("note taking app, idea notebook", "note-taking, productivity",
                                        "markdown editor, search", "A notebook for developing ideas.")
    return f"ANAHTAR: {anahtar}\nKONU: {konu}\nBILESEN: {bilesen}\nOZET: {ozet}"


def answer(messages: list[dict]) -> str:
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    lang = language_of(system)
    if "Yalnızca 'tamam' yaz." in user:
        return "tamam"                                             # the connection check
    if "autocomplete" in system:
        words = user.rsplit("Words before the cursor: ", 1)[-1]
        # the note's language decides, as with a real model
        code = lang
        if lang == "tr" and not re.search(r"[çğıöşüÇĞİÖŞÜ]", words):
            code = "de" if re.search(r"\b(ich|und|die|der|das)\b", words, re.I) else \
                "en" if re.search(r"\b(the|and|to|is|it|a)\b", words, re.I) else "tr"
        return words + CONTINUE[code]
    if "GENİŞTEN DARA" in system:
        return ladder_reply(user, lang)
    if "SORU[derinlestirme]" in system:
        return idea_reply(user, lang)
    if "İki şey arıyorsun" in system:
        return "YOK"
    if "TEK bir soru sordun" in system and "[BU TUR]" in system:
        return ("FİKİR:\n- Ortak bir klasör: kolay kurulur, ama aynı dosyaya iki araç birden yazabilir.\n"
                "- Bir görev listesi: herkes kendi işini alır, ama listeyi biri güncel tutmalı.\n"
                "Bu proje için görev listesini seçerdim, çünkü iki araç aynı anda çalışacak. Hangisi sana uyar?")
    if "TEK bir soru sordun" in system:
        return f"ANLADIM\nNOT: {user.strip()}" if len(user.split()) >= 3 else \
            "SORU: Bunu biraz daha açar mısın? Bir örnek verebilir misin?"
    if "SANA soru soruyor" in system:
        return "Kısaca: bu senin notunun amacına bağlı; bir örnekle düşünmek işe yarar.\nBenim sorum hâlâ duruyor."
    if "sohbette netleşen" in system:
        said = [line.split(":", 1)[1].strip() for line in user.splitlines() if line.startswith("Kullanıcı:")]
        return f"- {said[-1]}" if said else "- Konuşulan karar nota eklendi."
    if "yeni yön düzeltmesi" in system:
        return json.dumps({"ozet": "Yeni yöne göre devam ediyoruz; mevcut kararlar korunuyor.", "guncelle": {},
                           "kararlar": [], "sorular": [], "oneriler": [],
                           "yeni_sorular": ["Bu yeni yönde ilk hangi adımı atacaksın?"]}, ensure_ascii=False)
    if "MASTER PROMPT yazmak" in system:
        return master_reply(user)
    if "numaralı satırlar" in system:
        return "\n".join(f"{n}: - Karar: en sade seçenek kullanılır." for n in re.findall(r"^(\d+):", user, re.M))
    if "GitHub'da aratmak için" in system:
        return search_terms_reply(user)
    return "YOK"


class FakeModel:
    """The server, on its own thread. delay: seconds before each answer, so
    the app's spinners and streaming can be seen."""

    def __init__(self, delay: float = 0.0, host: str = "127.0.0.1", port: int = 0):
        self.delay = delay
        self.calls: list[dict] = []
        model = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status: int, body: bytes, kind: str = "application/json"):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/health"):
                    self._send(200, b'{"status":"ok"}')
                elif "/models" in self.path:
                    self._send(200, json.dumps({"data": [{"id": MODEL_ID}]}).encode())
                elif self.path.startswith("/calls"):
                    self._send(200, json.dumps(model.calls[-50:], ensure_ascii=False).encode())
                else:
                    self._send(404, b'{"error":"yok"}')

            def do_POST(self):
                if "/chat/completions" not in self.path:
                    self._send(404, b'{"error":"yok"}')
                    return
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                messages = payload.get("messages") or []
                text = answer(messages)
                model.calls.append({"at": time.time(), "system": next((m["content"][:80] for m in messages
                                                                      if m["role"] == "system"), ""),
                                    "reply": text[:200]})
                if model.delay:
                    time.sleep(model.delay)
                usage = {"prompt_tokens": sum(len(m.get("content") or "") for m in messages) // 4,
                         "completion_tokens": len(text) // 4}
                if not payload.get("stream"):
                    body = {"id": "sahte", "object": "chat.completion", "model": MODEL_ID, "usage": usage,
                            "choices": [{"index": 0, "finish_reason": "stop",
                                         "message": {"role": "assistant", "content": text}}]}
                    self._send(200, json.dumps(body, ensure_ascii=False).encode())
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for i in range(0, len(text), 24):
                        chunk = {"choices": [{"index": 0, "delta": {"content": text[i:i + 24]}}]}
                        self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                        self.wfile.flush()
                        if model.delay:
                            time.sleep(min(0.03, model.delay / 10))
                    done = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage}
                    self.wfile.write(f"data: {json.dumps(done)}\n\ndata: [DONE]\n\n".encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.server.daemon_threads = True
        self.thread = None

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "FakeModel":
        self.thread = threading.Thread(target=self.server.serve_forever, name="sahte-model", daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
