"""The master prompt end to end, an idea note's curiosity questions, and
speed that must not slide back: a long note and a big tree."""


def test_the_master_prompt_has_every_section_and_lists_the_models_decisions(page):
    page.open_note("Harcama takibi")
    page.page.keyboard.press("Control+Shift+M")
    sheet = page.page.locator(".mp-sheet")
    sheet.wait_for(timeout=10000)
    sheet.locator(".mp-go").click()
    page.page.wait_for_function("document.querySelectorAll('.mp-body h2').length >= 19", timeout=30000)
    headings = page.page.eval_on_selector_all(".mp-body h2", "els => els.map((e) => e.textContent)")
    assert headings[0].startswith("0.") and headings[-1].startswith("18.")
    assumed = sheet.locator(".mp-assumed li")
    assumed.first.wait_for(timeout=10000)
    assert assumed.count() >= 2


def test_an_idea_note_gets_curiosity_questions_not_the_decision_ladder(page, app):
    page.open_note(app.note("---\ntur: fikir\n---\n# Mahalle kütüphanesi\n\n"
                            "Apartmanın girişine bir raf koymak istiyorum, kitaplar bir deftere yazılsın.\n"))
    page.page.keyboard.press("Control+Enter")
    kind = page.page.locator(".h-item:not(.settled) .h-kind").first
    kind.wait_for(timeout=15000)
    kinds = page.page.eval_on_selector_all(".h-item:not(.settled) .h-kind", "els => els.map((e) => e.textContent)")
    assert any(k in ("Derinleştirme", "Alternatif fikir") for k in kinds), kinds
    assert not any(k.startswith(("Kapsam ·", "Mimari ·")) for k in kinds), kinds


def test_typing_in_a_long_note_stays_quick(page):
    page.open_note("Uzun not")
    timing = page.page.evaluate("""async () => {
      const ta = [...document.querySelectorAll('.md-input')].find((t) => t.value.length > 20000);
      ta.focus();
      ta.selectionStart = ta.selectionEnd = Math.floor(ta.value.length / 2);
      const took = [];
      for (let i = 0; i < 25; i++) {
        const a = performance.now();
        ta.setRangeText('x', ta.selectionStart, ta.selectionEnd, 'end');
        ta.dispatchEvent(new InputEvent('input', { bubbles: true, data: 'x', inputType: 'insertText' }));
        took.push(performance.now() - a);
        await new Promise((r) => setTimeout(r, 20));
      }
      took.sort((p, q) => p - q);
      return { chars: ta.value.length, median: took[12] };
    }""")
    # ~25 000 characters: 14 ms of line markup per key before its cache; a slide
    # back to re-drawing every line is what this catches, not a slow machine
    assert timing["chars"] > 20000 and timing["median"] < 60, timing


def test_a_big_tree_steps_its_physics_quickly(page):
    page.open_note("Büyük ağaç")
    page.page.evaluate("""async () => {
      const m = await import('/static/js/tree.js');
      const draw = m.IdeaTree.prototype._draw;
      m.IdeaTree.prototype._draw = function (t) { window.__tree = this; return draw.call(this, t); };
    }""")
    page.page.locator('[title^="Fikir ağacı"]').first.click()
    page.page.wait_for_function("window.__tree && window.__tree.stars.size >= 100", timeout=15000)
    step = page.page.evaluate("""() => {
      const t = window.__tree, took = [];
      for (let i = 0; i < 40; i++) { const a = performance.now(); t._step(1 / 60); took.push(performance.now() - a); }
      took.sort((p, q) => p - q);
      return took[20];
    }""")
    # 120 stars: about 1.5 ms; every pair compared again (the old way) is 5-10 times that
    assert step < 8, step
