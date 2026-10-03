"""The decision ladder: software is designed from the outside in.

A note about something to be built is asked about in order — first what it
is, who it is for and which platform it runs on; then how it is put together;
then its parts; and only then the details. Each rung is a short list of
decisions. The model is only ever pointed at the open decisions of the lowest
unfinished rung, so it cannot ask "which library?" while nobody has said
whether this is a phone app or a server.

When every decision is made the note has reached the product phase: it holds
enough to start building, and the writer is told so.

Nothing here talks to a model or the disk: it is the rulebook the assistant,
the prompt and the panel all read from.
"""
import re

from server.vault import fold, plain, split_frontmatter

# (level id, label, ((decision id, label, what deciding it means), ...))
LEVELS = (
    ("kapsam", "Kapsam", (
        ("amac", "Amaç", "tek cümlede hangi sorunu çözüyor"),
        ("kullanici", "Kullanıcı", "kim kullanacak: yalnız sen, bir ekip, herkes"),
        ("platform", "Platform", "web, masaüstü, mobil, komut satırı, kütüphane ya da servis"),
        ("calisma", "Çalışma ortamı", "çevrimiçi mi çevrimdışı mı; veri cihazda mı sunucuda mı"),
    )),
    ("mimari", "Mimari", (
        ("parcalar", "Ana parçalar", "istemci, sunucu, depolama, arka plan işi gibi büyük parçalar"),
        ("veri", "Veri", "hangi veri tutuluyor, nerede duruyor, sahibi kim"),
        ("iletisim", "İletişim", "parçalar birbiriyle nasıl konuşuyor: API, olay, kuyruk, dosya"),
        ("dis", "Dış bağımlılıklar", "kullanılacak dış servisler ve sistemler"),
    )),
    ("bilesen", "Bileşenler", (
        ("sorumluluk", "Sorumluluklar", "her parçanın tek işi ne"),
        ("arayuz", "Arayüzler", "parçalar arasındaki sözleşme: hangi çağrı, hangi veri"),
        ("hata", "Hata durumu", "bir parça çökerse ya da yanıt vermezse ne olur"),
    )),
    ("detay", "Detay", (
        ("teknoloji", "Teknoloji", "dil, çatı, kütüphane seçimleri ve nedenleri"),
        ("kenar", "Uç durumlar", "en önemli sınır ve kenar durumları"),
        ("test", "Doğrulama", "nasıl test edilip doğrulanacak"),
        ("dagitim", "Dağıtım", "nasıl kurulacak, dağıtılacak, güncellenecek"),
    )),
)

# The rung's own question for each decision: asked when the model gives none
# usable, so the order never depends on the model behaving.
ASK = {
    "amac": "Tek cümleyle: bu yazılım hangi sorunu çözecek?",
    "kullanici": "Bunu kim kullanacak: yalnız sen mi, bir ekip mi, herkes mi?",
    "platform": "Hangi platformda olacak: web, masaüstü, mobil, komut satırı, kütüphane ya da servis?",
    "calisma": "Çevrimiçi mi çevrimdışı mı çalışacak; veri cihazda mı, sunucuda mı duracak?",
    "parcalar": "Ana parçaları neler olacak: istemci, sunucu, depolama, arka plan işi?",
    "veri": "Hangi veriyi tutacak, nerede duracak, sahibi kim olacak?",
    "iletisim": "Parçalar birbiriyle nasıl konuşacak: API mi, olay mı, kuyruk mu, dosya mı?",
    "dis": "Hangi dış servislere ya da sistemlere bağlanacak?",
    "sorumluluk": "Her parçanın tek sorumluluğu ne olacak?",
    "arayuz": "Parçalar arasındaki sözleşme ne: hangi çağrı, hangi veri?",
    "hata": "Bir parça çökerse ya da yanıt vermezse ne olacak?",
    "teknoloji": "Hangi dil, çatı ve kütüphaneleri kullanacaksın, neden?",
    "kenar": "Dikkat edilmesi gereken en önemli uç durumlar neler?",
    "test": "Doğru çalıştığını nasıl doğrulayacaksın?",
    "dagitim": "Nasıl kurulacak, dağıtılacak ve güncellenecek?",
}

# the same questions for a writer who wants the assistant in another language
ASK_IN = {
    "en": {
        "amac": "In one sentence: what problem will this software solve?",
        "kullanici": "Who will use it: only you, a team, or everyone?",
        "platform": "Which platform will it run on: web, desktop, mobile, command line, a library or a service?",
        "calisma": "Will it work online or offline; will the data live on the device or on a server?",
        "parcalar": "What will its main parts be: client, server, storage, background jobs?",
        "veri": "What data will it keep, where will it live, and who will own it?",
        "iletisim": "How will the parts talk to each other: an API, events, a queue, files?",
        "dis": "Which external services or systems will it connect to?",
        "sorumluluk": "What will be the single responsibility of each part?",
        "arayuz": "What is the contract between the parts: which calls, which data?",
        "hata": "What happens when a part crashes or stops responding?",
        "teknoloji": "Which language, framework and libraries will you use, and why?",
        "kenar": "Which edge cases matter most?",
        "test": "How will you verify that it works correctly?",
        "dagitim": "How will it be installed, deployed and updated?",
    },
    "de": {
        "amac": "In einem Satz: Welches Problem soll diese Software lösen?",
        "kullanici": "Wer wird sie nutzen: nur du, ein Team oder alle?",
        "platform": "Auf welcher Plattform soll sie laufen: Web, Desktop, Mobil, Kommandozeile, Bibliothek oder Dienst?",
        "calisma": "Soll sie online oder offline arbeiten; liegen die Daten auf dem Gerät oder auf einem Server?",
        "parcalar": "Was werden die Hauptteile sein: Client, Server, Speicher, Hintergrundaufgaben?",
        "veri": "Welche Daten werden gespeichert, wo liegen sie und wem gehören sie?",
        "iletisim": "Wie sprechen die Teile miteinander: API, Ereignisse, Warteschlange, Dateien?",
        "dis": "Mit welchen externen Diensten oder Systemen wird sie verbunden?",
        "sorumluluk": "Was ist die eine Aufgabe jedes Teils?",
        "arayuz": "Was ist der Vertrag zwischen den Teilen: welche Aufrufe, welche Daten?",
        "hata": "Was passiert, wenn ein Teil abstürzt oder nicht antwortet?",
        "teknoloji": "Welche Sprache, welches Framework und welche Bibliotheken wirst du nutzen, und warum?",
        "kenar": "Welche Grenzfälle sind am wichtigsten?",
        "test": "Wie wirst du prüfen, dass sie richtig funktioniert?",
        "dagitim": "Wie wird sie installiert, ausgeliefert und aktualisiert?",
    },
    "es": {
        "amac": "En una frase: ¿qué problema resolverá este software?",
        "kullanici": "¿Quién lo usará: solo tú, un equipo o todo el mundo?",
        "platform": "¿En qué plataforma funcionará: web, escritorio, móvil, línea de comandos, biblioteca o servicio?",
        "calisma": "¿Funcionará con o sin conexión; los datos estarán en el dispositivo o en un servidor?",
        "parcalar": "¿Cuáles serán sus partes principales: cliente, servidor, almacenamiento, tareas en segundo plano?",
        "veri": "¿Qué datos guardará, dónde estarán y de quién serán?",
        "iletisim": "¿Cómo se comunicarán las partes: API, eventos, cola, archivos?",
        "dis": "¿A qué servicios o sistemas externos se conectará?",
        "sorumluluk": "¿Cuál será la única responsabilidad de cada parte?",
        "arayuz": "¿Cuál es el contrato entre las partes: qué llamadas, qué datos?",
        "hata": "¿Qué pasa si una parte falla o deja de responder?",
        "teknoloji": "¿Qué lenguaje, framework y bibliotecas usarás, y por qué?",
        "kenar": "¿Qué casos límite son los más importantes?",
        "test": "¿Cómo comprobarás que funciona correctamente?",
        "dagitim": "¿Cómo se instalará, desplegará y actualizará?",
    },
    "fr": {
        "amac": "En une phrase : quel problème ce logiciel va-t-il résoudre ?",
        "kullanici": "Qui va l'utiliser : toi seul, une équipe ou tout le monde ?",
        "platform": "Sur quelle plateforme tournera-t-il : web, bureau, mobile, ligne de commande, bibliothèque ou service ?",
        "calisma": "Fonctionnera-t-il en ligne ou hors ligne ; les données seront-elles sur l'appareil ou sur un serveur ?",
        "parcalar": "Quelles seront ses parties principales : client, serveur, stockage, tâches de fond ?",
        "veri": "Quelles données gardera-t-il, où seront-elles et à qui appartiendront-elles ?",
        "iletisim": "Comment les parties communiqueront-elles : API, événements, file d'attente, fichiers ?",
        "dis": "À quels services ou systèmes externes se connectera-t-il ?",
        "sorumluluk": "Quelle sera la responsabilité unique de chaque partie ?",
        "arayuz": "Quel est le contrat entre les parties : quels appels, quelles données ?",
        "hata": "Que se passe-t-il si une partie plante ou ne répond plus ?",
        "teknoloji": "Quels langage, framework et bibliothèques utiliseras-tu, et pourquoi ?",
        "kenar": "Quels cas limites comptent le plus ?",
        "test": "Comment vérifieras-tu qu'il fonctionne correctement ?",
        "dagitim": "Comment sera-t-il installé, déployé et mis à jour ?",
    },
}


def ask(decision: str, language: str = "tr") -> str:
    """The rung's own question, in the language the assistant writes in."""
    return ASK_IN.get(language, {}).get(decision) or ASK[decision]


# words that turn up in almost any answer whatever the note says: they cannot
# be what ties a claimed decision to the note
GENERIC_STEMS = {"uygu", "kull", "sist", "otom", "yazi", "olar", "olac", "yapm", "degi",
                 "tama", "sade", "yaln", "seki", "icin", "gibi", "olan", "ciha", "cali",
                 "veri", "notl",
                 # and the little words every sentence has
                 "bir", "ile", "her", "cok", "ama", "daha", "hem", "icin", "gore", "kada"}

DECISIONS = {decision: (level, label, hint)
             for level, _, items in LEVELS for decision, label, hint in items}
DECISION_IDS = tuple(DECISIONS)
LEVEL_LABELS = {level: label for level, label, _ in LEVELS}
PRODUCT = "urun"
PHASE_LABELS = {**LEVEL_LABELS, PRODUCT: "Ürün evresi"}

# `tur: fikir` in the frontmatter: a note that is not about building software
IDEA_TYPES = ("fikir", "genel", "not", "gunluk", "günlük")

def _key(text: str) -> str:
    return "".join(ch for ch in plain(str(text)) if ch.isalnum())


_LOOKUP = {**{_key(d): d for d in DECISION_IDS},
           **{_key(label): d for d, (_, label, _) in DECISIONS.items()}}


def normalize_decision(raw: str) -> str | None:
    """The model may write the id, the label, or the label in Turkish letters."""
    return _LOOKUP.get(_key(raw))


def _stems(text: str) -> set[str]:
    words = "".join(ch if ch.isalnum() else " " for ch in plain(str(text))).split()
    # four letters: Turkish roots are short and the suffixes pile up after
    # them ("aile" / "ailem" / "ailemin")
    return {w[:4] for w in words if len(w) >= 3}


def grounded(value: str, note: str) -> bool:
    """Is a decision the model claims actually in the note? At least one of
    its content words has to be: "Web uygulaması" for a note that never says
    web is a guess, "Mobil telefon uygulaması" for a note about a telefon
    uygulaması is not. This misses a paraphrase ("sadece ben" -> "yalnız
    yazar") — the cost of that is one question the writer answers in a word;
    the cost of a guess is the ladder skipping the platform."""
    claimed = _stems(value) - GENERIC_STEMS
    return bool(claimed & _stems(note))


# What a value has to be about to answer these decisions at all. Measured on
# DeepSeek V4 Flash: a café note's "Süt azalınca uyarsın" was filed as the
# working environment and "müşteri telefondan sipariş verecek" as the
# platform, so the whole first rung counted as decided and never got asked.
TOPIC_WORDS = {
    "kullanici": ("kisi", "kullanic", "ben", "biz", "kendim", "yalniz", "ekip", "takim", "aile", "musteri",
                  "calisan", "personel", "ogrenci", "herkes", "halk", "sirket", "kurum", "user", "team",
                  "family", "customer", "staff", "only me", "myself", "everyone", "nutzer", "usuario",
                  "utilisateur"),
    "platform": ("web", "site", "tarayici", "masaust", "desktop", "mobil", "telefon", "android", "ios",
                 "iphone", "tablet", "komut", "terminal", "cli", "kutuphane", "library", "servis", "service",
                 "api", "bot", "eklenti", "extension", "browser", "windows", "linux", "mac", "konsol",
                 "phone", "computer", "pc", "app store", "play store"),
    "calisma": ("cevrimici", "cevrimdisi", "internet", "online", "offline", "cihaz", "yerel", "local",
                "sunucu", "server", "bulut", "cloud", "senkron", "sync", "ag ", "network", "wifi",
                "baglanti", "bilgisayar", "telefonda", "lokal"),
}


def fits(decision: str, value: str) -> bool:
    """Does the value talk about what the decision asks? Only the decisions
    with a closed vocabulary are checked; the rest are the model's to judge."""
    words = TOPIC_WORDS.get(decision)
    if not words:
        return True
    text = plain(value)
    # at a word's start: "yapılacak" holds "api" and is no platform
    return any(re.search(r"\b" + re.escape(word.strip()), text) for word in words)


def note_mode(content: str) -> str:
    """'yazilim' unless the note says otherwise: this is a notebook for people
    designing software, so the ladder is the default and `tur: fikir` the
    way out for a note that is not about building anything."""
    meta = split_frontmatter(content or "")[0]
    declared = _key(meta.get("tur") or meta.get("tip") or "")
    return "fikir" if declared in {_key(t) for t in IDEA_TYPES} else "yazilim"


BRIEF_TYPES = {"master-prompt", "master prompt", "masterprompt"}


def is_brief(content: str) -> bool:
    """A master prompt saved as a note: the assistant's own output, not an
    idea — asked about, it started the ladder over ("Bunu kim kullanacak?")."""
    meta = split_frontmatter(content or "")[0]
    return _key(meta.get("tur") or meta.get("tip") or "") in {_key(t) for t in BRIEF_TYPES}


def state(decided: dict | None) -> dict:
    """Where the note stands: every rung, which decisions are made, the rung
    the questions should come from next, and the phase."""
    decided = decided or {}
    levels, current = [], None
    for level, label, items in LEVELS:
        rows = [{"id": d, "label": lab, "hint": hint, "decided": d in decided,
                 "by": (decided.get(d) or {}).get("by"),
                 "value": (decided.get(d) or {}).get("value")} for d, lab, hint in items]
        done = all(row["decided"] for row in rows)
        if current is None and not done:
            current = level
        levels.append({"id": level, "label": label, "decisions": rows, "done": done})
    made = sum(1 for d in DECISION_IDS if d in decided)
    open_now = [] if current is None else [
        row["id"] for lvl in levels if lvl["id"] == current for row in lvl["decisions"]
        if not row["decided"]]
    phase = current or PRODUCT
    return {"levels": levels, "current": current, "open": open_now, "phase": phase,
            "phase_label": PHASE_LABELS[phase], "made": made, "total": len(DECISION_IDS)}


def may_ask(decision: str, ladder: dict) -> bool:
    """Only an open decision of the current rung may be asked about. A question
    about a deeper rung is the model skipping ahead; one about a decision
    already made is asking again."""
    return decision in ladder["open"]


# "Her model kendi tanımlanmış gözüyle bakarak sorgulayacak": each pass one of
# these looks at the note, in turn, and offers what it sees (llm_client.
# offer_extras). Not the ladder's questions: told to ask "through a lens", the
# model stopped reading decisions the note states (14/14 -> 8/14, GPT-4o-mini).
LENSES = (
    ("mimar", "Mimar", "parçaların nasıl bir araya geldiğine, veri akışına ve büyümeye"),
    ("urun", "Ürün", "kullanıcının gerçek ihtiyacına, en küçük değerli sürüme ve kapsam dışına"),
    ("guvenlik", "Güvenlik ve işletim", "verinin nerede durduğuna, kimin eriştiğine, hata ve kesintiye"),
    ("gelistirici", "Geliştirici", "yapılabilirliğe, bağımlılıklara, test edilebilirliğe ve bakıma"),
)
LENS_LABELS = {lens_id: label for lens_id, label, _ in LENSES}


def lens_line(lens) -> str:
    lens_id, label, focus = lens
    return (f"\n\n[BAKIŞ AÇISI] Bu turda {label} gözüyle bak: {focus} dikkat et. "
            f"ÖNERİ bu gözden gelsin.")


def roadmap(ladder: dict) -> str:
    """The block the model reads: finished rungs in one line, the current rung
    in full, the rest by name only — it has no business there yet."""
    lines = ["[YOL HARİTASI]"]
    for index, level in enumerate(ladder["levels"], start=1):
        if level["done"]:
            made = ", ".join(f"{row['label']}: {row['value']}" if row.get("value") else row["label"]
                             for row in level["decisions"])
            lines.append(f"{index}. {level['label']}: TAMAM ({made})")
        elif level["id"] == ladder["current"]:
            lines.append(f"{index}. {level['label']}: ŞU ANKİ SEVİYE")
            for row in level["decisions"]:
                # what was decided, not only that it was: the next question of
                # the rung branches on the answer ("sadece Android" -> offline?)
                mark = ("AÇIK" if not row["decided"] else
                        f"karar verildi: {row['value']}" if row.get("value") else "karar verildi")
                lines.append(f"   - {row['id']} ({row['label']}: {row['hint']}) — {mark}")
        else:
            lines.append(f"{index}. {level['label']}: sırası gelmedi, sorma")
    if ladder["current"] is None:
        lines.append("Bütün kararlar verildi: not ürün evresinde. Yeni karar sorusu sorma.")
    else:
        lines.append(f"AÇIK KARARLAR (her biri için bir satır yaz): {', '.join(ladder['open'])}")
    return "\n".join(lines)


def brief(ladder: dict) -> str:
    """Every decision in one block, for prompts other than the ladder's own:
    what is decided (with its value) and what is still open, on every rung —
    a competitor can teach something about the deployment as well as the scope."""
    decided, open_ = [], []
    for level in ladder["levels"]:
        for row in level["decisions"]:
            if row["decided"]:
                decided.append(f"{row['id']} ({row['label']}): {row.get('value') or 'notta yazıyor'}")
            else:
                open_.append(f"{row['id']} ({row['label']}: {row['hint']})")
    return ("[KARARLAR]\nVerilmiş: " + ("; ".join(decided) or "henüz yok")
            + "\nAçık: " + ("; ".join(open_) or "yok"))


def transition(before: dict, after: dict) -> dict | None:
    """What changed in a way the writer should hear about: a rung finished, or
    the note reached the product phase. Going back (a decision taken away)
    is not announced."""
    if before["phase"] == after["phase"]:
        return None
    order = [level for level, _, _ in LEVELS] + [PRODUCT]
    if order.index(after["phase"]) < order.index(before["phase"]):
        return None
    if after["phase"] == PRODUCT:
        return {"phase": PRODUCT, "title": "Ürün evresi",
                "body": (f"Bu not ürün evresine geldi: {after['total']} kararın hepsi verildi — "
                         "kapsam, mimari, bileşenler ve detaylar belli. Yapmaya başlamak için "
                         "yeterli bilgi notta.")}
    done = [lvl["label"] for lvl in after["levels"] if lvl["done"]]
    return {"phase": after["phase"], "title": f"{done[-1]} netleşti" if done else "Yeni seviye",
            "body": f"Sıradaki seviye: {after['phase_label']}. Sorular artık buradan gelecek."}
