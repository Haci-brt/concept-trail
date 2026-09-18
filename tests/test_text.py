"""The text helpers the assistant leans on.

Each case here is a bug we actually hit: suggestions landing under the wrong
heading, the same question coming back reworded, a typo fix looking like a
paragraph of new writing, a `<think>` tag cut in half mid-stream.
"""
from server.assistant import (_same_topic, _stems, diff_new_text, focus_span, looks_like_question,
                              msys_path, section_coverage, section_for, section_of,
                              sections_with_spans, thinking_preview, under_path)
from pathlib import Path

NOTE = """# Sesli Günlük

Her gün iki dakika konuşup kaydedeceğim.

## Kayıt

Telefonun mikrofonu yeterli, ayrı cihaz almayacağım.

## Arşiv

Kayıtlar tarihe göre klasörlenecek.
"""


def span_of(text: str, needle: str) -> list[int]:
    at = text.index(needle)
    return [at, at + len(needle)]


# ---------------------------------------------------------------- sections
def test_top_level_title_is_the_note_not_a_section():
    assert section_of(NOTE, span_of(NOTE, "iki dakika")) == ""


def test_section_of_uses_the_heading_above_the_change():
    assert section_of(NOTE, span_of(NOTE, "mikrofonu")) == "Kayıt"
    assert section_of(NOTE, span_of(NOTE, "klasörlenecek")) == "Arşiv"


def test_sections_carry_spans_that_cover_the_whole_note():
    parts = sections_with_spans(NOTE)
    assert [name for name, _, _, _ in parts] == ["", "Kayıt", "Arşiv"]
    assert parts[0][2] == 0 and parts[-1][3] == len(NOTE)
    for _, _, start, end in parts:
        assert start < end


# ---------------------------------------------------------------- attribution
def test_question_is_filed_under_the_section_it_quotes():
    # the bug: attribution used to fall back to the *last* heading, so every
    # question about the intro was filed under "Arşiv"
    assert section_for(NOTE, "İki dakika konuşmak yeterli mi?", None) == ""
    assert section_for(NOTE, "Mikrofon kalitesi kaydı bozar mı?", None) == "Kayıt"
    assert section_for(NOTE, "Klasörleme tarihe göre mi olmalı?", None) == "Arşiv"


def test_unrelated_question_lands_on_the_note_not_the_last_heading():
    assert section_for(NOTE, "Bunu kimseyle paylaşacak mısın?", None) == ""


def test_turkish_suffixes_do_not_hide_a_match():
    # "konuşup" in the note vs "konuşarak" in the question
    assert _stems("konuşarak") & _stems("konuşup")


# ---------------------------------------------------------------- repetition
def test_the_same_question_reworded_is_recognised():
    old = _stems("Kayıtları hangi klasörleme düzeniyle arşivleyeceksin?")
    new = _stems("Arşivlerken klasörleme düzenini nasıl kuracaksın?")
    assert _same_topic(new, old)


def test_a_genuinely_different_question_is_not_suppressed():
    old = _stems("Kayıtları hangi klasörleme düzeniyle arşivleyeceksin?")
    new = _stems("Mikrofon yerine ayrı bir cihaz almayı düşündün mü?")
    assert not _same_topic(new, old)


def test_empty_stems_never_count_as_the_same_topic():
    assert not _same_topic(set(), _stems("Kayıtları nasıl arşivleyeceksin?"))


# ---------------------------------------------------------------- focus
def test_a_whole_note_pass_goes_to_the_least_asked_section():
    nodes = [{"type": "question", "section": ""}, {"type": "question", "section": "Kayıt"}]
    start, end = focus_span(NOTE, nodes, None)
    assert NOTE[start:end].strip().startswith("## Arşiv")


def test_while_typing_the_pass_follows_the_edit():
    span = span_of(NOTE, "mikrofonu")
    assert focus_span(NOTE, [], span) == span


def test_coverage_marks_the_sections_with_no_questions_yet():
    lines = section_coverage(NOTE, [{"type": "question", "section": "Kayıt"}]).splitlines()
    assert "- (giriş): henüz soru yok" in lines
    assert "- Kayıt: 1 soru soruldu" in lines


# ---------------------------------------------------------------- diffing
def test_text_appended_at_the_end_is_reported_with_its_line():
    old = "# Not\n\nİlk cümle."
    new = old + " İkinci cümle."
    part, changed, span = diff_new_text(old, new)
    assert part == "İlk cümle. İkinci cümle."      # whole line, so the model has context
    assert changed == len("İkinci cümle.")          # but only the typed characters count
    assert new[span[0]:span[1]].strip() == part


def test_a_typo_fixed_mid_note_is_not_a_paragraph_of_new_text():
    old = "# Not\n\n" + "Uzun bir paragraf. " * 20 + "yanlis kelime sonda."
    new = old.replace("yanlis", "yanlış")
    part, changed, span = diff_new_text(old, new)
    assert changed < 25                              # not the whole 300-char paragraph
    assert "yanlış" in part and span is not None


def test_text_inserted_above_the_end_is_still_seen():
    # the pre-web app only looked past the previous length and missed this
    old = "# Not\n\nA satırı.\n\nB satırı.\n"
    new = "# Not\n\nA satırı.\n\nAraya giren satır.\n\nB satırı.\n"
    part, changed, span = diff_new_text(old, new)
    assert "Araya giren satır." in part and changed > 0
    assert "Araya giren satır." in new[span[0]:span[1]]


def test_no_change_reports_nothing():
    assert diff_new_text(NOTE, NOTE) == ("", 0, None)


# ---------------------------------------------------------------- streaming
def test_a_half_written_closing_think_tag_is_not_shown():
    preview = thinking_preview("<think>Kullanıcı arşivden söz ediyor</thi")
    assert preview["phase"] == "thinking"
    assert "</thi" not in preview["text"]


def test_the_opening_tag_arriving_letter_by_letter_reads_as_thinking():
    assert thinking_preview("<thi")["phase"] == "thinking"


def test_text_after_the_closing_tag_is_the_reply():
    preview = thinking_preview("<think>bir şeyler</think>Asıl cevap.")
    assert preview == {"phase": "writing", "text": "Asıl cevap."}


def test_a_reply_without_tags_is_just_the_reply():
    assert thinking_preview("Düz cevap.") == {"phase": "writing", "text": "Düz cevap."}


# ---------------------------------------------------------------- misc
def test_a_message_that_asks_something_is_not_an_answer():
    assert looks_like_question("Sen ne önerirsin?")
    assert looks_like_question("Neden böyle olsun")     # no question mark, still asking
    assert looks_like_question("Hangi format daha iyi?")
    assert not looks_like_question("Sadece kendi ailem için, yaklaşık 50 tarif.")


def test_dotted_and_dotless_i_do_not_break_question_detection():
    assert looks_like_question("NASIL yapacağım")


def test_windows_paths_become_git_bash_paths():
    assert msys_path(Path(r"C:\Users\x\run.sh")) == "/c/Users/x/run.sh"
    assert msys_path(Path("/d/models/a.gguf")) == "/d/models/a.gguf"


def test_under_path_matches_folders_not_name_prefixes():
    assert under_path("fikirler/not.md", "fikirler")
    assert under_path("fikirler", "fikirler")
    assert not under_path("fikirlerim/not.md", "fikirler")
