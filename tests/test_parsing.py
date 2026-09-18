"""Reading the model's reply, and deciding what to send it.

The parser is the app's airlock: whatever a local checkpoint emits — an
unclosed reasoning block, a half-written edit, three questions on one line —
must come out as something the rest of the app can trust.
"""
from core.llm_client import (HEAD_CONTEXT_CHARS, MAX_CONTEXT_CHARS, MAX_QUESTIONS,
                             note_context, parse_chat_reply, parse_response)
from server.vault import fold, split_frontmatter


# ---------------------------------------------------------------- questions
def test_a_tagged_question_keeps_its_kind():
    result = parse_response("SORU[derinlestirme]: Kaydı kim dinleyecek?")
    assert result == {"type": "questions",
                      "questions": [{"text": "Kaydı kim dinleyecek?", "kind": "derinlestirme"}]}


def test_separate_questions_stay_separate():
    raw = ("SORU[alternatif]: Yazmak yerine sesli not denedin mi?\n"
           "SORU[sonuc]: Bir ay sonra elinde ne olacak?")
    questions = parse_response(raw)["questions"]
    assert [q["kind"] for q in questions] == ["alternatif", "sonuc"]
    assert len(questions) == 2


def test_the_same_question_twice_is_kept_once():
    raw = "SORU: Neden iki dakika?\nSORU: Neden iki dakika?"
    assert len(parse_response(raw)["questions"]) == 1


def test_no_more_questions_than_the_cap():
    raw = "\n".join(f"SORU: {i}. soru burada?" for i in range(10))
    assert len(parse_response(raw)["questions"]) == MAX_QUESTIONS


def test_an_unknown_kind_falls_back_to_a_plain_question():
    assert parse_response("SORU[sacmalik]: Peki ya sonra?")["questions"][0]["kind"] == "soru"


def test_an_untagged_line_is_still_taken_as_a_question():
    assert parse_response("Kayıtları kim dinleyecek?")["questions"][0]["text"] == "Kayıtları kim dinleyecek?"


# ---------------------------------------------------------------- silence
def test_an_unclosed_think_block_is_never_shown_as_a_question():
    # a checkpoint that runs out of tokens mid-reasoning used to dump the whole
    # reasoning trace into the HUD as if it were a question
    raw = "<think>Kullanıcı arşivden söz ediyor, belki klasörleme sorulabilir"
    assert parse_response(raw) == {"type": "net"}


def test_net_and_empty_replies_say_nothing():
    assert parse_response("NET")["type"] == "net"
    assert parse_response("   ")["type"] == "net"
    assert parse_response("?")["type"] == "net"          # too short to be anything


# ---------------------------------------------------------------- edits
def test_a_complete_edit_is_parsed():
    raw = ("DUZENLEME\nORIJINAL: iki dakika konusacagim\n"
           "ONERI: her gün iki dakika konuşacağım\nNEDEN: Türkçe karakterler eksik")
    assert parse_response(raw) == {"type": "edit", "original": "iki dakika konusacagim",
                                   "replacement": "her gün iki dakika konuşacağım",
                                   "reason": "Türkçe karakterler eksik"}


def test_an_edit_missing_its_replacement_is_dropped_not_guessed():
    assert parse_response("DUZENLEME\nORIJINAL: bir şey")["type"] == "net"


def test_a_field_does_not_bleed_into_the_next_one():
    raw = "DÜZENLEME\nORİJİNAL: eski metin\nÖNERİ: yeni metin\nNEDEN: daha açık"
    assert parse_response(raw)["replacement"] == "yeni metin"


# ---------------------------------------------------------------- resolution
def test_a_question_marked_solved_carries_its_index():
    assert parse_response("COZULDU: 2") == {"type": "resolved", "resolved_index": 2}
    assert parse_response("ÇÖZÜLDÜ 1")["resolved_index"] == 1


def test_solved_without_a_number_is_ignored():
    assert parse_response("COZULDU")["type"] == "net"


# ---------------------------------------------------------------- chat replies
def test_understood_carries_the_text_meant_for_the_note():
    reply = parse_chat_reply("ANLADIM\nNOT: Kayıtlar tarihe göre klasörlenecek.")
    assert reply == {"type": "understood", "note": "Kayıtlar tarihe göre klasörlenecek."}


def test_a_follow_up_question_keeps_the_thread_open():
    assert parse_chat_reply("SORU: Kaç kayıt birikmesini bekliyorsun?") == {
        "type": "question", "text": "Kaç kayıt birikmesini bekliyorsun?"}


def test_an_untagged_reply_ending_in_a_question_mark_is_a_question():
    assert parse_chat_reply("Peki bunları kim dinleyecek?")["type"] == "question"


def test_an_empty_reply_asks_again_instead_of_writing_nothing():
    assert parse_chat_reply("")["type"] == "question"


def test_the_reasoning_block_is_stripped_before_parsing():
    reply = parse_chat_reply("<think>kullanıcı net konuştu</think>ANLADIM\nNOT: Tamamdır.")
    assert reply == {"type": "understood", "note": "Tamamdır."}


# ---------------------------------------------------------------- context
def test_a_short_note_is_sent_whole():
    note = "# Kısa\n\nİki satırlık bir not.\n"
    assert note_context(note) == note


def test_a_long_note_sends_its_opening_plus_the_edited_section():
    body = "## Arşiv\n" + ("Arşivle ilgili uzun bir paragraf. " * 60)
    note = "# Uzun Not\n\n" + ("Girişte duran uzun bir paragraf. " * 60) + "\n" + body
    assert len(note) > MAX_CONTEXT_CHARS
    context = note_context(note, [note.index("## Arşiv") + 20, note.index("## Arşiv") + 30])
    assert context.startswith("# Uzun Not")        # stable prefix, so the prompt cache keeps hitting
    assert "## Arşiv" in context
    assert "[…]" in context
    assert len(context) <= HEAD_CONTEXT_CHARS + MAX_CONTEXT_CHARS + 10


# ---------------------------------------------------------------- turkish text
def test_dotted_and_dotless_i_fold_together():
    assert fold("İSTANBUL") == fold("istanbul") == "istanbul"
    assert fold("IŞIK") == "işik"


def test_frontmatter_is_split_off_with_its_line_count():
    text = "---\ngizli: true\netiketler: [fikir, ses]\n---\n# Not\n\ngövde\n"
    meta, body, lines = split_frontmatter(text)
    assert meta["gizli"] == "true"
    assert meta["etiketler"] == ["fikir", "ses"]
    assert body.startswith("# Not")
    assert lines == 4


def test_a_note_without_frontmatter_is_left_alone():
    assert split_frontmatter("# Not\n\ngövde\n") == ({}, "# Not\n\ngövde\n", 0)
