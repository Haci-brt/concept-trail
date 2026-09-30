"""A stand-in model: the OpenAI chat-completions shape, answered without a model.

Concept Trail gives each job its own system prompt; this reads which job a
request is from that prompt and answers in the form the job's parser expects:
decision-ladder lines drawn from the note itself, curiosity questions, a chat
that understands a full answer, asks again on a short one, offers options to
a writer who does not know and takes the one they pick, text for the note,
the rest of a line, a master prompt with every section, a course correction
plan — and, when asked to (extras=True), the model's own suggestion through
the pass's lens and a research proposal. It is predictable rather than
clever — which is what a test wants, and enough to click through every
screen of the app.

    model = FakeModel(delay=0.3).start()      # model.base_url -> http://127.0.0.1:<port>
    ...
    model.stop()

GET /calls lists the latest requests: the job, the model name it was sent to
(REMOTE_MODEL_ID when it came through the provider bound as remote) and the
note it was about.
"""
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from server import ladder
from server.vault import fold, plain

MODEL_ID = "sahte-model"
# the same stand-in bound as a remote provider (python -m testkit --uzak): the
# name its requests carry is the only thing that tells them apart
REMOTE_MODEL_ID = "sahte-uzak-model"

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
PUNCT = ".,;:!?()«»\"'“”"

# the model's own suggestion, one for each lens (server/ladder.py LENSES):
# what two things the note says ({a}, {b}) lead to together
SUGGESTIONS = {
    "tr": {
        "mimar": "«{a}» ile «{b}» aynı kayıtlara dokunacağı için ekranlar veriye tek bir kayıt katmanı "
                 "üzerinden ulaşmalı.",
        "urun": "İlk sürüm yalnız «{a}» işini uçtan uca yapmalı; «{b}» ile ilgili geri kalan her şey ikinci "
                "sürüme kalmalı.",
        "guvenlik": "«{a}» ve «{b}» bir araya gelince kayıtlar cihazda şifreli durmalı ve silinen bir kayıt "
                    "yedekten de silinmeli.",
        "gelistirici": "«{a}» ve «{b}» için gerçek hesaba bağlanmadan sahte verilerle çalışan bir deneme modu "
                       "olmalı.",
    },
    "en": {
        "mimar": "“{a}” and “{b}” touch the same records, so every screen should reach the data through one "
                 "storage layer.",
        "urun": "The first version should do “{a}” end to end; everything else about “{b}” waits for the second.",
        "guvenlik": "With “{a}” and “{b}” together, records should stay encrypted on the device and a deleted "
                    "record should leave the backup too.",
        "gelistirici": "“{a}” and “{b}” need a demo mode that runs on made-up data without a real account.",
    },
}
# what the model asks to research: a capability others have already solved,
# chosen by what the note is about — (tr, en) topic and reason
RESEARCH = (
    (("bitki", "sula", "plant", "water"),
     ("zamanlanmış hatırlatma bildirimleri", "Uygulama kapalıyken de zamanında haber vermek hazır çözülmüş bir iş."),
     ("scheduled reminder notifications", "Firing on time while the app is closed is a solved problem.")),
    (("harcama", "fiş", "expense", "receipt"),
     ("fiş fotoğrafından tutar okuma", "Fişten tutarı ve tarihi okuyan hazır OCR kütüphaneleri var."),
     ("reading totals from receipt photos", "Ready OCR libraries read the total and the date off a receipt.")),
    (("internet yokken", "çevrimdışı", "offline", "without internet"),
     ("iki cihaz arası çevrimdışı senkron", "Bağlantı yokken yapılan değişiklikleri birleştirmek hazır çözülmüş bir iş."),
     ("offline sync between two devices", "Merging changes made without a connection is a solved problem.")),
)
OTHER_RESEARCH = (("benzer uygulamaların veri modeli", "Aynı işi yapan projelerin neyi nasıl sakladığını görmek "
                   "ilk kararları hızlandırır."),
                  ("data model of similar apps", "How similar projects store their data speeds up the first decisions."))

# the options the chat offered, as the app keeps them: "- " lines, the
# "FİKİR:" tag already taken off
OPTION_LINE = re.compile(r"^\s*[-*•]\s+(.+?)\s*$", re.M)
# how a writer takes one of them (matched on plain()): by its place, or the
# one the model said it would choose
BY_PLACE = ((re.compile(r"\b(ilk|birinci|first)"), 0), (re.compile(r"\b(ikinci|second)"), 1),
            (re.compile(r"\b(ucuncu|third)"), 2), (re.compile(r"\b(sonuncu|last)\b"), -1))
AS_ADVISED = re.compile(r"\b(onerdig|sectig|dedig|tavsiye|o olsun|o olur|tamam|aynen)|\b(olur|evet|ok|okay|yes)\b")


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


def note_phrases(note: str, count: int = 2) -> list[str]:
    """Short phrases in the note's own words, each from a sentence of its own
    (two long words side by side in one clause, else one long word): what a
    suggestion says it follows from, so the app's check that both are in the
    note holds."""
    sentences = note_sentences(note)
    phrases = []
    for sentence in sentences:
        words = sentence.split()
        pairs = ((a.strip(PUNCT), b.strip(PUNCT)) for a, b in zip(words, words[1:]) if a == a.rstrip(PUNCT))
        pair = next((f"{a} {b}" for a, b in pairs
                     if min(len(a), len(b)) >= 5 and not {fold(a), fold(b)} & FILLER
                     and ladder.grounded(f"{a} {b}", note)), None)
        if pair:
            phrases.append(pair)
        if len(phrases) == count:
            return phrases
    words = sorted({w.strip(PUNCT) for s in sentences for w in s.split()}, key=lambda w: (-len(w), w))
    for word in words:
        if len(phrases) == count:
            break
        if len(word) >= 6 and fold(word) not in FILLER and ladder.grounded(word, note) \
                and not any(fold(word) in fold(p) for p in phrases):
            phrases.append(word)
    return phrases


def extras_reply(user: str, lang: str) -> str:
    """The model's own suggestion, seen through this pass's lens, and a
    research proposal: the ÖNERİ and ARAŞTIR lines the app's parser takes."""
    note = re.split(r"\[YOL HARİTASI\]|\[BAKIŞ AÇISI\]", user, maxsplit=1)[0]
    lens = next((lens_id for lens_id, label, _ in ladder.LENSES if f"Bu turda {label} gözüyle" in user), "mimar")
    code = "tr" if lang == "tr" else "en"
    lines = []
    phrases = note_phrases(note)
    if len(phrases) == 2:
        a, b = (p[:40] for p in phrases)
        lines.append(f"ÖNERİ: {SUGGESTIONS[code][lens].format(a=a, b=b)} | {a} + {b}")
    text = fold(note)
    tr, en = next(((tr, en) for keys, tr, en in RESEARCH if any(fold(k) in text for k in keys)), OTHER_RESEARCH)
    topic, why = tr if code == "tr" else en
    lines.append(f"ARAŞTIR: {topic} | {why}")
    return "\n".join(lines)


def _stems(text: str) -> set[str]:
    return {w[:4] for w in re.findall(r"\w+", plain(text)) if len(w) >= 4}


def chosen_option(messages: list[dict]) -> str | None:
    """The option the writer's last message takes — "ilkini yapalım",
    "önerdiğin olsun", "tamam" — when the model's turn just before it offered
    some. A long message is an answer of its own, not a pick."""
    said = [m for m in messages if m["role"] in ("user", "assistant")]
    if len(said) < 2 or said[-1]["role"] != "user" or said[-2]["role"] != "assistant":
        return None
    offered = said[-2]["content"] or ""
    options = OPTION_LINE.findall(offered)
    reply = plain(said[-1]["content"] or "")
    if len(options) < 2 or len(reply.split()) > 8:
        return None
    for pattern, index in BY_PLACE:
        if pattern.search(reply) and index < len(options):
            return options[index]
    if not AS_ADVISED.search(reply):
        return None
    # the one the model said it would choose: its name comes back in the lines after the options
    advice = _stems(" ".join(line for line in offered.splitlines() if not OPTION_LINE.match(line)))
    scores = [len(_stems(option.split(":", 1)[0]) & advice) for option in options]
    return options[scores.index(max(scores))]


def as_decision(option: str, lang: str) -> str:
    """"- Bir görev listesi: herkes kendi işini alır" as a line for the note."""
    name, _, detail = option.replace("**", "").partition(":")
    name, detail = name.strip(), detail.strip().rstrip(".")
    lead = "Karar" if lang == "tr" else "Decision"
    return f"{lead}: {name} — {detail}." if detail else f"{lead}: {name}."


def note_title(messages: list[dict]) -> str:
    """The note a request is about, by its heading — for /calls."""
    ordered = [m for m in messages if m["role"] != "system"] + [m for m in messages if m["role"] == "system"]
    for message in ordered:
        found = re.search(r"^#\s+(.+)$", message.get("content") or "", re.M)
        if found:
            return found.group(1).strip()[:80]
    return ""


def answer(messages: list[dict], extras_given: set[str] | None = None) -> str:
    """extras_given: the note texts that have had their suggestion and research
    proposal — each gets them once, so a sandbox does not fill up with them.
    None: that job is answered "YOK", as the browser tests expect."""
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
        note = re.split(r"\[YOL HARİTASI\]|\[BAKIŞ AÇISI\]", user, maxsplit=1)[0].strip()
        if extras_given is None or note in extras_given:
            return "YOK"
        extras_given.add(note)
        return extras_reply(user, lang)
    if "TEK bir soru sordun" in system and "[BU TUR]" in system:
        return ("FİKİR:\n- Ortak bir klasör: kolay kurulur, ama aynı dosyaya iki araç birden yazabilir.\n"
                "- Bir görev listesi: herkes kendi işini alır, ama listeyi biri güncel tutmalı.\n"
                "Bu proje için görev listesini seçerdim, çünkü iki araç aynı anda çalışacak. Hangisi sana uyar?")
    if "TEK bir soru sordun" in system:
        picked = chosen_option(messages)
        if picked:
            return f"ANLADIM\nNOT: {as_decision(picked, lang)}"
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
    the app's spinners and streaming can be seen. extras: also offer the
    model's own suggestion and a research proposal, once per note text (the
    sandbox does; the browser tests leave it off, so their panels hold only
    what they ask for)."""

    def __init__(self, delay: float = 0.0, host: str = "127.0.0.1", port: int = 0, extras: bool = False):
        self.delay = delay
        self.calls: list[dict] = []
        self.extras_given: set[str] | None = set() if extras else None
        self.lock = threading.Lock()
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
                with model.lock:
                    text = answer(messages, model.extras_given)
                    model.calls.append({"at": time.time(), "model": payload.get("model") or "",
                                        "note": note_title(messages),
                                        "system": next(((m["content"] or "")[:80] for m in messages
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
