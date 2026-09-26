"""The decision ladder: broad before narrow, and a clear signal at the end."""
from server import ladder
from server.ladder import (DECISION_IDS, may_ask, normalize_decision, note_mode, roadmap, state,
                           transition)


def decided(*ids):
    return {d: {"by": "not"} for d in ids}


KAPSAM = ("amac", "kullanici", "platform", "calisma")
MIMARI = ("parcalar", "veri", "iletisim", "dis")
BILESEN = ("sorumluluk", "arayuz", "hata")
DETAY = ("teknoloji", "kenar", "test", "dagitim")


# ---------------------------------------------------------------- order
def test_a_new_note_starts_at_scope_and_platform():
    s = state({})
    assert s["current"] == "kapsam" and s["phase"] == "kapsam"
    assert "platform" in s["open"]
    assert s["made"] == 0 and s["total"] == 15


def test_the_next_rung_opens_only_when_this_one_is_finished():
    s = state(decided("amac", "kullanici", "platform"))
    assert s["current"] == "kapsam" and s["open"] == ["calisma"]
    s = state(decided(*KAPSAM))
    assert s["current"] == "mimari" and s["open"] == list(MIMARI)


def test_a_detail_cannot_be_asked_while_the_platform_is_open():
    s = state(decided("amac"))
    assert may_ask("platform", s)
    assert not may_ask("teknoloji", s)       # skipping ahead
    assert not may_ask("amac", s)            # already decided


def test_a_decision_made_early_is_simply_not_asked_later():
    # the writer already said "Python" — that detail is known before its rung
    s = state(decided(*KAPSAM, *MIMARI, *BILESEN, "teknoloji"))
    assert s["current"] == "detay" and "teknoloji" not in s["open"]


# ---------------------------------------------------------------- the product phase
def test_every_decision_made_means_the_product_phase():
    s = state(decided(*DECISION_IDS))
    assert s["current"] is None and s["phase"] == "urun" and s["open"] == []
    assert s["phase_label"] == "Ürün evresi"


def test_reaching_the_product_phase_is_announced():
    change = transition(state(decided(*DECISION_IDS[:-1])), state(decided(*DECISION_IDS)))
    assert change["phase"] == "urun" and "ürün evresine geldi" in change["body"]


def test_finishing_a_rung_is_announced_with_what_comes_next():
    change = transition(state(decided("amac", "kullanici", "platform")), state(decided(*KAPSAM)))
    assert change["title"] == "Kapsam netleşti" and "Mimari" in change["body"]


def test_nothing_is_announced_when_nothing_changed_or_a_decision_was_taken_back():
    s = state(decided(*KAPSAM))
    assert transition(s, s) is None
    assert transition(s, state(decided("amac"))) is None


# ---------------------------------------------------------------- what the model reads
def test_the_roadmap_shows_the_current_rung_in_full_and_hides_the_rest():
    text = roadmap(state(decided("amac")))
    assert "Kapsam: ŞU ANKİ SEVİYE" in text
    assert "platform (Platform:" in text and "AÇIK" in text
    assert "Mimari: sırası gelmedi, sorma" in text
    assert "teknoloji" not in text             # a deeper rung's ids are not even named
    assert text.strip().endswith("kullanici, platform, calisma")


def test_the_roadmap_says_when_there_is_nothing_left_to_decide():
    assert "ürün evresinde" in roadmap(state(decided(*DECISION_IDS)))


# ---------------------------------------------------------------- reading the model
def test_the_model_may_name_a_decision_by_id_label_or_turkish_letters():
    assert normalize_decision("platform") == "platform"
    assert normalize_decision("Çalışma ortamı") == "calisma"
    assert normalize_decision("  Dış bağımlılıklar ") == "dis"
    assert normalize_decision("KULLANICI") == "kullanici"
    assert normalize_decision("hangi-kütüphane") is None


# ---------------------------------------------------------------- which notes climb it
def test_every_note_is_a_software_note_unless_it_says_otherwise():
    assert note_mode("# Senkron\n\nNotlar iki cihazda duracak.") == "yazilim"
    assert note_mode("---\ntur: fikir\n---\n# Kafe") == "fikir"
    assert note_mode("---\ntur: günlük\n---\n# Bugün") == "fikir"
    assert note_mode("---\ntur: yazilim\n---\n# Plan") == "yazilim"


def test_the_decision_ids_fit_the_question_tag():
    # SORU[<id>]: — the tag only takes letters, so no id may carry anything else
    assert all(d.isalpha() and d.isascii() for d in DECISION_IDS)
    assert len(set(DECISION_IDS)) == len(DECISION_IDS) == 15
    assert [lvl for lvl, _, _ in ladder.LEVELS] == ["kapsam", "mimari", "bilesen", "detay"]


# ---------------------------------------------------------------- grounding what the model claims
def test_a_claimed_decision_must_be_in_the_note():
    """Live: the 4B model 'decided' the platform of a note that never names one."""
    vague = "# Kod inceleme botu\n\nPull request'leri otomatik inceleyen bir sey yapmak istiyorum.\n"
    assert not ladder.grounded("Web uygulaması", vague)
    assert not ladder.grounded("Çevrimiçi, sunucuda çalışır", vague)
    assert ladder.grounded("Pull request'lerin kalitesini değerlendirmek", vague)


def test_turkish_suffixes_do_not_hide_a_real_match():
    mobile = "# Harcama\n\nFisleri fotografla ceken bir telefon uygulamasi. Ailem de kullanacak.\n"
    assert ladder.grounded("Aile içindeki kişiler", mobile)
    assert ladder.grounded("Mobil telefon uygulaması", mobile)


def test_generic_words_alone_do_not_ground_a_claim():
    """Words any answer contains ("bir", "uygulama", "kullanıcı") match any note;
    they cannot be what ties a claim to it."""
    note = "# Not\n\nKullanıcı için bir uygulama yapacağım.\n"
    assert not ladder.grounded("bir uygulama olacak", note)
    assert not ladder.grounded("kullanıcı uygulaması", note)
    assert ladder.grounded("bir masaüstü uygulaması", "# Not\n\nMasaüstünde çalışacak.\n")


def test_every_decision_has_its_own_question():
    assert set(ladder.ASK) == set(DECISION_IDS)
    assert all(q.endswith("?") for q in ladder.ASK.values())
