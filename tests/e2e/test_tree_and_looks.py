"""The idea tree at scale, zooming that no longer shakes it, the themes and
their skies, and the interface in another language."""
import pytest

# the running tree, caught as it draws its first frame
HOOK = """async () => {
  const m = await import('/static/js/tree.js');
  if (!window.__treeHooked) {
    const draw = m.IdeaTree.prototype._draw;
    m.IdeaTree.prototype._draw = function (t) { window.__tree = this; return draw.call(this, t); };
    window.__treeHooked = true;
  }
}"""


def open_tree(page, name):
    page.open_note(name)
    page.page.evaluate(HOOK)
    page.page.locator('[title^="Fikir ağacı"]').first.click()
    page.page.wait_for_function("window.__tree && window.__tree.stars.size > 0", timeout=15000)
    page.page.wait_for_timeout(1500)                         # the stars light up and settle


def test_a_big_tree_draws_every_star_and_keeps_moving(page):
    open_tree(page, "Büyük ağaç")
    stars = page.page.evaluate("window.__tree.stars.size")
    assert stars >= 100
    frames = page.page.evaluate("""() => new Promise((done) => {
      let n = 0; const start = performance.now();
      const tick = () => { n++; if (performance.now() - start < 1000) requestAnimationFrame(tick); else done(n); };
      requestAnimationFrame(tick);
    })""")
    assert frames >= 10, frames                               # it animates, it has not frozen


def test_zooming_out_at_the_edge_does_not_fling_the_stars(page):
    open_tree(page, "Büyük ağaç")
    moved = page.page.evaluate("""async () => {
      const t = window.__tree, c = t.canvas, r = c.getBoundingClientRect();
      const frame = () => new Promise((f) => requestAnimationFrame(f));
      const drift = () => { let m = 0; for (const s of t.stars.values()) if (s.depth) m = Math.max(m, Math.hypot(s.x - s.tx, s.y - s.ty) * t.cam.k); return m; };
      t.fit(false); for (let i = 0; i < 90; i++) await frame();
      let rest = 0; for (let i = 0; i < 20; i++) { await frame(); rest = Math.max(rest, drift()); }
      let peak = 0;
      for (let i = 0; i < 6; i++) {
        c.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, clientX: r.left + 60, clientY: r.top + 90, bubbles: true, cancelable: true }));
        for (let f = 0; f < 4; f++) { await frame(); peak = Math.max(peak, drift()); }
      }
      return { rest, peak };
    }""")
    # measured before the fix: about 70 px of fling; the stars' own rest is a few px
    assert moved["peak"] <= moved["rest"] + 8, moved


@pytest.mark.parametrize("theme,mood", [("takimyildiz", "night"), ("dark", "forest"), ("gunbatimi", "dusk"),
                                        ("parsomen", "sepia"), ("buzul", "polar"), ("kontrast", "black")])
def test_each_theme_gives_the_tree_its_own_sky(page, theme, mood):
    open_tree(page, "Bitki hatırlatıcı")
    page.page.locator("#themeBtn").click()
    page.page.locator(f'[data-theme-id="{theme}"]').click()
    assert page.page.evaluate("document.documentElement.dataset.theme") == theme
    page.page.wait_for_function("(m) => window.__tree.sky.look && window.__tree.sky.look.mood === m",
                                arg=mood, timeout=5000)


def test_the_interface_speaks_english_with_nothing_left_in_turkish(page, app):
    app.api.put("/api/preferences", json={"ui_language": "en"})
    try:
        page.page.reload()
        page.page.wait_for_selector(".sidebar .name", state="attached")
        page.page.wait_for_timeout(1500)
        page.open_note("Expense tracker")
        page.page.wait_for_timeout(800)
        status = page.page.locator("#statusbar").inner_text()
        assert "Live watch" in status and "Completion" in status, status
        missing = page.page.evaluate("window.__i18nMissing ? window.__i18nMissing() : []")
        turkish = [m for m in missing if any(ch in m for ch in "çğıöşüÇĞİÖŞÜ")]
        assert not turkish, turkish[:10]
    finally:
        app.api.put("/api/preferences", json={"ui_language": "tr"})
