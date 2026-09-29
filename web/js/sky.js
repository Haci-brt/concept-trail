// The sky behind the idea tree: a slow, living night in the theme's mood.
//
// Whatever does not change from one frame to the next — the nebulae, the
// Milky Way, the glow of a star — is painted once into offscreen canvases
// and after that only moved, faded and scaled, so a frame costs a handful of
// image draws and a few hundred dots. The layers sit at different depths:
// the far ones barely follow a pan or a zoom, the near ones follow more, and
// all of them drift very slowly on their own, so the sky is never quite
// still. Each theme has its own sky: a clear night, a forest night with
// fireflies, a dusk with embers and a warm horizon, a sepia night of an old
// star chart, a polar night with an aurora, and a plain black one for high
// contrast. With reduced motion it is a still picture.

const TAU = Math.PI * 2;

const MOODS = {
  night: {
    sky: ["#040816", "#081226", "#0e1a33"],
    nebula: ["72, 196, 170", "129, 120, 255", "255, 143, 200"],
    band: ["150, 140, 255", "110, 220, 200", "255, 196, 226", "200, 215, 255"],
    stars: ["#ffffff", "#cfe3ff", "#ffe8c2", "#d9d2ff"],
    motes: { kind: "dust", color: "190, 210, 255", count: 34 },
    meteor: "255, 255, 255",
  },
  forest: {
    sky: ["#030c0b", "#061719", "#0b2428"],
    nebula: ["64, 214, 160", "70, 150, 210", "170, 230, 120"],
    band: ["130, 220, 190", "150, 190, 255", "220, 255, 210", "200, 230, 255"],
    stars: ["#ffffff", "#d8fff0", "#fff3c9", "#cfe6ff"],
    motes: { kind: "fireflies", color: "214, 255, 140", count: 26 },
    meteor: "225, 255, 240",
  },
  dusk: {
    sky: ["#0d0718", "#1f0d24", "#3a1626"],
    nebula: ["255, 138, 92", "255, 110, 170", "150, 110, 255"],
    band: ["255, 170, 140", "255, 140, 190", "200, 160, 255", "255, 220, 200"],
    stars: ["#fff4ea", "#ffd9c2", "#ffe8a8", "#e8d6ff"],
    motes: { kind: "embers", color: "255, 170, 110", count: 30 },
    horizon: "255, 120, 80",
    meteor: "255, 236, 220",
  },
  sepia: {
    sky: ["#0c0906", "#17110b", "#241a10"],
    nebula: ["230, 170, 90", "200, 120, 70", "150, 120, 190"],
    band: ["240, 200, 150", "220, 170, 120", "255, 225, 190", "200, 180, 220"],
    stars: ["#fff6e6", "#ffe2b8", "#f5d6a8", "#ffffff"],
    motes: { kind: "dust", color: "255, 214, 160", count: 30 },
    meteor: "255, 240, 214",
  },
  polar: {
    sky: ["#020915", "#061528", "#0b2238"],
    nebula: ["90, 170, 255", "80, 220, 200", "170, 140, 255"],
    band: ["170, 210, 255", "120, 230, 220", "220, 235, 255", "190, 180, 255"],
    stars: ["#ffffff", "#dff0ff", "#cfe3ff", "#e6ddff"],
    motes: { kind: "snow", color: "235, 245, 255", count: 60 },
    aurora: ["80, 255, 180", "110, 190, 255"],
    meteor: "230, 245, 255",
  },
  // high contrast: the stars and nothing much else
  black: {
    sky: ["#000000", "#01020a", "#03050d"],
    nebula: ["72, 196, 170", "129, 120, 255", "255, 143, 200"],
    band: ["200, 200, 255", "180, 230, 220", "255, 220, 235", "220, 225, 255"],
    stars: ["#ffffff", "#e6f0ff", "#fff1d6", "#ffffff"],
    motes: null,
    meteor: "255, 255, 255",
    nebulaAlpha: 0.35,
    bandAlpha: 0.6,
  },
};
const THEME_MOOD = { light: "night", takimyildiz: "night", dark: "forest", gunbatimi: "dusk", parsomen: "sepia",
                     buzul: "polar", kontrast: "black" };
const FADE_S = 0.9;          // one sky giving way to another when the theme changes

// a small deterministic generator, so the sky is the same every time
export function seeded(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}
// roughly normal, for the density of the Milky Way across its width
const gauss = (rnd) => (rnd() + rnd() + rnd() + rnd() - 2) * 0.87;
const clamp01 = (v) => Math.max(0, Math.min(1, v));
// follows a pan at first, then gives less and less: a layer never slides off
const soft = (v, room) => (room > 0 ? room * Math.tanh(v / room) : 0);

function canvas(w, h) {
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(w));
  c.height = Math.max(1, Math.round(h));
  return c;
}

function puff(g, x, y, r, rgb, a) {
  const grad = g.createRadialGradient(x, y, 0, x, y, r);
  grad.addColorStop(0, `rgba(${rgb}, ${a})`);
  grad.addColorStop(0.45, `rgba(${rgb}, ${a * 0.5})`);
  grad.addColorStop(1, `rgba(${rgb}, 0)`);
  g.fillStyle = grad;
  g.fillRect(x - r, y - r, r * 2, r * 2);
}

/** A cloud of gas: a few filaments, each a random walk of soft puffs, on
 *  wide faint washes, with dark lanes of dust cut through the bright parts.
 *  Painted at half resolution — it is all soft edges anyway. */
function paintNebula(W, H, palette, seed) {
  const scale = 0.5;
  const c = canvas(W * scale, H * scale);
  const g = c.getContext("2d");
  g.scale(scale, scale);
  const rnd = seeded(seed);
  const hues = palette.nebula, span = Math.min(W, H);
  g.globalCompositeOperation = "lighter";
  for (let i = 0; i < 5; i++) {
    puff(g, rnd() * W, rnd() * H, Math.max(W, H) * (0.25 + rnd() * 0.25), hues[i % hues.length], 0.028);
  }
  const filaments = 3 + Math.floor(rnd() * 2);
  for (let f = 0; f < filaments; f++) {
    let x = W * (0.1 + rnd() * 0.8), y = H * (0.1 + rnd() * 0.8), a = rnd() * TAU;
    const hue = hues[f % hues.length], size = span * (0.1 + rnd() * 0.09);
    for (let s = 0, steps = 16 + Math.floor(rnd() * 10); s < steps; s++) {
      a += (rnd() - 0.5) * 0.9;
      x += Math.cos(a) * size * 0.42;
      y += Math.sin(a) * size * 0.42;
      puff(g, x, y, size * (0.45 + rnd() * 0.9), hue, 0.03 + rnd() * 0.05);
      // now and then a small bright knot, where stars are being born
      if (rnd() < 0.18) puff(g, x, y, size * 0.18, "255, 255, 255", 0.05);
    }
  }
  g.globalCompositeOperation = "destination-out";
  for (let i = 0; i < 22; i++) puff(g, rnd() * W, rnd() * H, span * (0.04 + rnd() * 0.08), "0, 0, 0", 0.2);
  return c;
}

/** The Milky Way: a soft diagonal band of countless faint stars with a dark
 *  lane of dust down its middle. */
function paintBand(W, H, palette, dpr) {
  const scale = Math.min(1.5, dpr);
  const c = canvas(W * scale, H * scale);
  const g = c.getContext("2d");
  g.scale(scale, scale);
  const rnd = seeded(21);
  const len = Math.hypot(W, H), thick = Math.min(W, H) * 0.2;
  g.translate(W / 2, H / 2);
  g.rotate(-0.5);
  for (let i = 0; i < 34; i++) {
    const x = (rnd() - 0.5) * len, y = gauss(rnd) * thick * 0.35, r = thick * (0.45 + rnd() * 0.8);
    puff(g, x, y, r, palette.band[Math.floor(rnd() * palette.band.length)], 0.07);
  }
  for (let i = 0; i < 3200; i++) {
    const x = (rnd() - 0.5) * len, y = gauss(rnd) * thick * 0.4, big = rnd() < 0.06;
    g.globalAlpha = 0.1 + rnd() * (big ? 0.7 : 0.4);
    g.fillStyle = palette.stars[rnd() < 0.7 ? 0 : 1 + Math.floor(rnd() * 3)];
    g.beginPath();
    g.arc(x, y, big ? 0.9 + rnd() * 0.6 : 0.35 + rnd() * 0.45, 0, TAU);
    g.fill();
  }
  g.globalAlpha = 1;
  const [r0, g0, b0] = hexRgb(palette.sky[0]);
  for (let i = 0; i < 26; i++) {
    const x = (rnd() - 0.5) * len * 0.9, y = gauss(rnd) * thick * 0.07, r = thick * (0.12 + rnd() * 0.22);
    puff(g, x, y, r, `${r0}, ${g0}, ${b0}`, 0.5);
  }
  return c;
}

function hexRgb(hex) {
  const v = parseInt(hex.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

/** A round glow, white at the heart: drawn scaled for stars, motes and meteors. */
function glowSprite(rgb, core = 1) {
  const c = canvas(64, 64), g = c.getContext("2d");
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, `rgba(255, 255, 255, ${core})`);
  grad.addColorStop(0.12, `rgba(${rgb}, 0.9)`);
  grad.addColorStop(0.4, `rgba(${rgb}, 0.22)`);
  grad.addColorStop(1, `rgba(${rgb}, 0)`);
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  return c;
}

/** A far galaxy: a small tilted oval with a bright core. */
function galaxySprite(rnd, rgb) {
  const c = canvas(56, 56), g = c.getContext("2d");
  g.translate(28, 28);
  g.rotate(rnd() * Math.PI);
  g.scale(1, 0.28 + rnd() * 0.3);
  const grad = g.createRadialGradient(0, 0, 0, 0, 0, 26);
  grad.addColorStop(0, "rgba(255, 250, 240, 0.9)");
  grad.addColorStop(0.15, `rgba(${rgb}, 0.45)`);
  grad.addColorStop(1, `rgba(${rgb}, 0)`);
  g.fillStyle = grad;
  g.beginPath();
  g.arc(0, 0, 26, 0, TAU);
  g.fill();
  return c;
}

/** One ribbon of an aurora: light that is brightest at its lower edge and
 *  fades upward into the sky. */
function auroraSprite(rgb) {
  const c = canvas(1, 128), g = c.getContext("2d");
  const grad = g.createLinearGradient(0, 0, 0, 128);
  grad.addColorStop(0, `rgba(${rgb}, 0)`);
  grad.addColorStop(0.55, `rgba(${rgb}, 0.35)`);
  grad.addColorStop(0.9, `rgba(${rgb}, 1)`);
  grad.addColorStop(1, `rgba(${rgb}, 0)`);
  g.fillStyle = grad;
  g.fillRect(0, 0, 1, 128);
  return c;
}

function makeStars() {
  const rnd = seeded(7);
  const layer = (n, rMin, rMax, dMin, dMax) => {
    const list = [];
    for (let i = 0; i < n; i++) {
      const p = rnd();
      list.push({ x: rnd(), y: rnd(), r: rMin + rnd() * rnd() * (rMax - rMin), a: 0.3 + rnd() * 0.6,
                  phase: rnd() * TAU, speed: 0.4 + rnd() * 1.8, depth: dMin + rnd() * (dMax - dMin),
                  tint: p < 0.6 ? 0 : p < 0.8 ? 1 : p < 0.93 ? 2 : 3 });
    }
    return list.sort((a, b) => a.tint - b.tint);
  };
  // far: a dust of tiny points; mid: the ordinary stars; near: a few bright ones
  return { far: layer(420, 0.3, 0.85, 0.015, 0.04), mid: layer(150, 0.5, 1.4, 0.05, 0.11),
           near: layer(12, 1.1, 2.0, 0.13, 0.2) };
}

function makeMotes(motes) {
  if (!motes) return [];
  const list = [];
  for (let i = 0; i < motes.count; i++) {
    list.push({ x: Math.random(), y: Math.random(), phase: Math.random() * TAU, speed: 0.5 + Math.random(),
                r: 0.6 + Math.random() * 1.1, a: 0.3 + Math.random() * 0.7,
                vx: (Math.random() - 0.5) * 8, vy: 5 + Math.random() * 11 });
  }
  return list;
}

export class Sky {
  constructor() {
    this.mood = null;
    this.look = null;            // the current mood's painted layers
    this.fading = null;          // the previous mood's, while it gives way
    this.stars = makeStars();
    this.meteors = [];
    this.nextMeteor = 5 + Math.random() * 6;
    this.flare = null;
    this.nextFlare = 3;
    const rnd = seeded(41);
    this.galaxies = Array.from({ length: 5 }, () => ({ x: rnd(), y: rnd(), size: 18 + rnd() * 22, a: 0.35 + rnd() * 0.35,
                                                        depth: 0.012 + rnd() * 0.012, seed: rnd() }));
    this._vignette = null;
  }

  static moodFor(theme) { return THEME_MOOD[theme] || "night"; }

  /** Everything painted for one mood at one size. */
  _paint(mood, w, h, dpr) {
    const palette = MOODS[mood];
    const W = Math.ceil(w * 1.5), H = Math.ceil(h * 1.5);
    const rnd = seeded(97);
    return {
      mood, palette, w, h, dpr,
      nebulae: [paintNebula(W, H, palette, 11), paintNebula(W, H, palette, 29)],
      nebulaSize: { W, H },
      band: paintBand(Math.ceil(w * 1.35), Math.ceil(h * 1.35), palette, dpr),
      bandSize: { W: Math.ceil(w * 1.35), H: Math.ceil(h * 1.35) },
      glows: palette.stars.map((c) => glowSprite(hexRgb(c).join(", "))),
      mote: palette.motes ? glowSprite(palette.motes.color, palette.motes.kind === "snow" ? 1 : 0.9) : null,
      meteor: glowSprite(palette.meteor),
      galaxies: this.galaxies.map((gx) => galaxySprite(seeded(Math.floor(gx.seed * 1e6)),
                                                        palette.nebula[Math.floor(rnd() * palette.nebula.length)])),
      aurora: palette.aurora ? palette.aurora.map(auroraSprite) : null,
      motes: makeMotes(palette.motes),
    };
  }

  /** Draw the sky for one frame.
   *  view: { pan: {x, y} (screen pixels the sky has been panned), k (zoom),
   *          still (reduced motion), focus (0-1, a card is open),
   *          calm (a star is held: no shooting stars), dpr } */
  draw(ctx, w, h, t, view) {
    const mood = Sky.moodFor(document.documentElement.dataset.theme);
    const look = this.look;
    // repaint on a new mood, or when the view has grown or shrunk a good deal
    // (small resizes only rescale what is there)
    const resized = look && (Math.abs(look.w - w) > w * 0.25 || Math.abs(look.h - h) > h * 0.25 || look.dpr !== view.dpr);
    if (!look || look.mood !== mood || resized) {
      if (look && look.mood !== mood && !view.still) this.fading = { look, from: t };
      this.look = this._paint(mood, w, h, view.dpr);
    }
    let mix = 1;
    if (this.fading) {
      mix = clamp01((t - this.fading.from) / FADE_S);
      if (mix >= 1) this.fading = null;
    }
    const tt = view.still ? 0 : t;
    if (this.fading) this._layers(ctx, w, h, tt, view, this.fading.look, 1);
    this._layers(ctx, w, h, tt, view, this.look, mix);
    this._starfield(ctx, w, h, tt, view, this.look.palette);
    if (this.fading) this._motes(ctx, w, h, tt, view, this.fading.look, 1 - mix);
    this._motes(ctx, w, h, tt, view, this.look, mix);
    if (!view.still) this._meteors(ctx, w, h, t, view);
    this._vignetteOn(ctx, w, h);
  }

  // ---------- the backdrop: colour, clouds, the Milky Way, an aurora ----------
  _layers(ctx, w, h, t, view, look, alpha) {
    if (alpha <= 0) return;
    const { palette } = look;
    const { pan, k } = view;
    ctx.globalAlpha = alpha;
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, palette.sky[0]);
    g.addColorStop(0.55, palette.sky[1]);
    g.addColorStop(1, palette.sky[2]);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    if (palette.horizon) {
      // dusk: the last light of the day, breathing low on the horizon
      const breathe = 0.8 + 0.2 * Math.sin(t * 0.18);
      ctx.save();
      ctx.translate(w / 2 + soft(pan.x * 0.02, w * 0.1), h * 1.08);
      ctx.scale(1, 0.38);
      const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, w * 0.8);
      glow.addColorStop(0, `rgba(${palette.horizon}, ${0.3 * breathe * alpha})`);
      glow.addColorStop(0.5, `rgba(${palette.horizon}, ${0.1 * breathe * alpha})`);
      glow.addColorStop(1, `rgba(${palette.horizon}, 0)`);
      ctx.globalAlpha = 1;
      ctx.fillStyle = glow;
      ctx.fillRect(-w, -w, w * 2, w * 2);
      ctx.restore();
    }

    // two clouds of gas, each on its own slow drift, breathing out of step
    const { W, H } = look.nebulaSize;
    const sw = w / look.w, sh = h / look.h;
    look.nebulae.forEach((cloud, i) => {
      const z = Math.pow(k, i ? 0.09 : 0.05);
      const dw = W * sw * z, dh = H * sh * z;
      const room = { x: (dw - w) / 2, y: (dh - h) / 2 };
      const drift = { x: Math.sin(t * 0.011 + i * 2.1) * w * 0.05, y: Math.cos(t * 0.008 + i * 1.3) * h * 0.04 };
      const par = i ? 0.07 : 0.045;
      const x = (w - dw) / 2 + soft(pan.x * par + drift.x, room.x);
      const y = (h - dh) / 2 + soft(pan.y * par + drift.y, room.y);
      const breathe = 0.75 + 0.25 * Math.sin(t * (i ? 0.19 : 0.13) + i * 1.7);
      ctx.globalAlpha = alpha * breathe * (1 - view.focus * 0.3) * (palette.nebulaAlpha ?? 1);
      ctx.drawImage(cloud, x, y, dw, dh);
    });

    // the Milky Way sits furthest back and moves least
    {
      const z = Math.pow(k, 0.04);
      const dw = look.bandSize.W * sw * z, dh = look.bandSize.H * sh * z;
      const x = (w - dw) / 2 + soft(pan.x * 0.03, (dw - w) / 2);
      const y = (h - dh) / 2 + soft(pan.y * 0.03, (dh - h) / 2);
      ctx.globalAlpha = alpha * (0.84 + 0.1 * Math.sin(t * 0.13)) * (1 - view.focus * 0.35) * (palette.bandAlpha ?? 1);
      ctx.drawImage(look.band, x, y, dw, dh);
    }

    if (look.aurora) this._aurora(ctx, w, h, t, view, look, alpha);
    ctx.globalAlpha = 1;
  }

  /** Polar night: curtains of light that ripple and fold along the top of the sky. */
  _aurora(ctx, w, h, t, view, look, alpha) {
    const { pan } = view;
    const step = 5;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    look.aurora.forEach((sprite, r) => {
      const base = h * (0.26 + r * 0.1) + soft(pan.y * 0.03, h * 0.05);
      const shift = soft(pan.x * 0.03, w * 0.1);
      for (let x = -step; x < w + step; x += step) {
        const u = (x - shift) / w;
        const y = base + Math.sin(u * 5.2 + t * 0.22 + r * 1.3) * h * 0.05 + Math.sin(u * 13 - t * 0.37 + r * 2) * h * 0.016;
        // broad folds of the curtain, with a finer shimmer of rays running along it
        const fold = clamp01(0.5 + 0.38 * Math.sin(u * 8 + t * 0.35 + r * 4) + 0.12 * Math.sin(u * 29 - t * 0.8 + r));
        const ends = Math.sin(Math.PI * clamp01((u + 0.05) / 1.1));
        const a = alpha * (0.1 + 0.26 * fold * fold) * ends * (0.72 + 0.28 * Math.sin(t * 0.13 + r)) * (1 - view.focus * 0.4);
        if (a < 0.004) continue;
        const tall = h * (0.14 + 0.12 * fold);
        ctx.globalAlpha = a;
        ctx.drawImage(sprite, x, y - tall, step + 1, tall);
      }
    });
    ctx.restore();
  }

  // ---------- stars ----------
  /** One star's place on screen: its point in a tile the size of the view,
   *  moved by the pan and its own drift at its depth, then the tile scaled
   *  about the middle for the zoom. Zoomed out, the tile is smaller than the
   *  view, and its neighbours fill the edges. */
  _eachPlace(s, w, h, view, t, z, draw) {
    const u = ((s.x * w + view.pan.x * s.depth + t * s.depth * 18) % w + w) % w;
    const v = ((s.y * h + view.pan.y * s.depth) % h + h) % h;
    const x = w / 2 + (u - w / 2) * z, y = h / 2 + (v - h / 2) * z;
    if (z >= 1) { draw(x, y); return; }
    const tw = w * z, th = h * z;
    for (let i = -1; i <= 1; i++) {
      const X = x + i * tw;
      if (X < -4 || X > w + 4) continue;
      for (let j = -1; j <= 1; j++) {
        const Y = y + j * th;
        if (Y > -4 && Y < h + 4) draw(X, Y);
      }
    }
  }

  /** The far specks for this size and mood, painted once. */
  _farTile(w, h, palette, dpr) {
    const key = `${w}x${h}@${dpr}:${this.look.mood}`;
    if (this._far?.key === key) return this._far.canvas;
    const scale = Math.min(2, dpr || 1);
    const c = canvas(w * scale, h * scale), g = c.getContext("2d");
    g.scale(scale, scale);
    for (const s of this.stars.far) {
      g.globalAlpha = s.a * 0.8;
      g.fillStyle = palette.stars[s.tint];
      g.fillRect(s.x * w - s.r, s.y * h - s.r, s.r * 2, s.r * 2);
    }
    this._far = { key, canvas: c };
    return c;
  }

  _starfield(ctx, w, h, t, view, palette) {
    const { k, still } = view;
    const dim = 1 - view.focus * 0.25;
    // far: hundreds of specks, painted once into a tile the size of the view
    // and only moved and scaled — one to four image draws instead of 420
    let z = Math.pow(k, 0.03);
    {
      const tile = this._farTile(w, h, palette, view.dpr);
      const depth = 0.0275, tw = w * z, th = h * z;
      const ox = ((view.pan.x * depth + t * depth * 18) % w + w) % w;
      const oy = ((view.pan.y * depth) % h + h) % h;
      const sx = w / 2 + (ox - w / 2) * z, sy = h / 2 + (oy - h / 2) * z;
      ctx.globalAlpha = dim * (still ? 1 : 0.9 + 0.1 * Math.sin(t * 0.5));
      for (let x = sx - Math.ceil(sx / tw) * tw; x < w; x += tw) {
        for (let y = sy - Math.ceil(sy / th) * th; y < h; y += th) ctx.drawImage(tile, x, y, tw, th);
      }
    }
    // far galaxies: faint smudges, all but still
    this.galaxies.forEach((gx, i) => {
      ctx.globalAlpha = gx.a * dim;
      const sprite = this.look.galaxies[i];
      this._eachPlace(gx, w, h, view, t, z, (x, y) => ctx.drawImage(sprite, x - gx.size / 2, y - gx.size / 2, gx.size, gx.size));
    });
    // mid: round, twinkling
    z = Math.pow(k, 0.08);
    for (const s of this.stars.mid) {
      ctx.globalAlpha = s.a * (still ? 0.85 : 0.6 + 0.4 * Math.sin(t * s.speed + s.phase)) * dim;
      ctx.fillStyle = palette.stars[s.tint];
      this._eachPlace(s, w, h, view, t, z, (x, y) => { ctx.beginPath(); ctx.arc(x, y, s.r, 0, TAU); ctx.fill(); });
    }
    // near: a few bright stars with a halo and four fine spikes; every few
    // seconds one of them flares
    if (!still && t > this.nextFlare) {
      this.flare = { i: Math.floor(Math.random() * this.stars.near.length), born: t };
      this.nextFlare = t + 4 + Math.random() * 6;
    }
    z = Math.pow(k, 0.17);
    this.stars.near.forEach((s, i) => {
      const tw = still ? 0.8 : 0.65 + 0.35 * Math.sin(t * s.speed * 0.7 + s.phase);
      let flare = 0;
      if (this.flare && this.flare.i === i) {
        const p = (t - this.flare.born) / 1.6;
        if (p >= 1) this.flare = null;
        else flare = Math.sin(Math.PI * p);
      }
      const glow = this.look.glows[s.tint];
      // kept quieter than the tree's own stars: their glints mean "waiting for you"
      this._eachPlace(s, w, h, view, t, z, (x, y) => {
        const halo = s.r * (4.5 + flare * 8);
        ctx.globalAlpha = (0.4 * tw + 0.5 * flare) * dim;
        ctx.drawImage(glow, x - halo, y - halo, halo * 2, halo * 2);
        const len = s.r * (2.2 + flare * 11) * tw;
        ctx.globalAlpha = (0.16 * tw + 0.55 * flare) * dim;
        ctx.strokeStyle = palette.stars[s.tint];
        ctx.lineWidth = 0.7;
        ctx.beginPath();
        ctx.moveTo(x - len, y); ctx.lineTo(x + len, y);
        ctx.moveTo(x, y - len); ctx.lineTo(x, y + len);
        ctx.stroke();
      });
    });
    ctx.globalAlpha = 1;
  }

  // ---------- what floats: dust, fireflies, embers, snow ----------
  _motes(ctx, w, h, t, view, look, alpha) {
    const kind = look.palette.motes?.kind;
    if (!kind || !look.mote || alpha <= 0) return;
    const par = 0.3, span = { w: w + 40, h: h + 40 };
    const wrap = (v, n) => ((v % n) + n) % n - 20;
    const dim = alpha * (1 - view.focus * 0.5);
    for (const m of look.motes) {
      let x, y, a, size;
      if (kind === "fireflies") {
        // they wander, and glow only now and then
        x = m.x * w + Math.sin(t * 0.21 * m.speed + m.phase) * 46 + Math.sin(t * 0.53 + m.phase * 2) * 14;
        y = m.y * h + Math.cos(t * 0.17 * m.speed + m.phase) * 34 + Math.sin(t * 0.61 + m.phase) * 10;
        a = 0.05 + 0.85 * Math.pow(Math.max(0, Math.sin(t * m.speed * 0.9 + m.phase)), 6);
        size = m.r * 9;
      } else if (kind === "embers") {
        // rising from the warm horizon, swaying, flickering
        x = m.x * w + Math.sin(t * 0.6 * m.speed + m.phase) * 12;
        y = m.y * h - t * m.vy;
        a = m.a * (0.45 + 0.35 * Math.sin(t * 3 * m.speed + m.phase));
        size = m.r * 6;
      } else if (kind === "snow") {
        x = m.x * w + Math.sin(t * 0.5 * m.speed + m.phase) * 14 + t * 3;
        y = m.y * h + t * m.vy;
        a = m.a * 0.6;
        size = m.r * 3.2;
      } else {
        // dust: drifts about, catching the light
        x = m.x * w + t * m.vx + Math.sin(t * 0.3 + m.phase) * 8;
        y = m.y * h + t * m.vx * 0.6 + Math.cos(t * 0.23 + m.phase) * 8;
        a = m.a * (0.12 + 0.12 * Math.sin(t * m.speed + m.phase));
        size = m.r * 5;
      }
      x = wrap(x + view.pan.x * par, span.w);
      y = wrap(y + view.pan.y * par, span.h);
      ctx.globalAlpha = a * dim;
      ctx.drawImage(look.mote, x - size, y - size, size * 2, size * 2);
    }
    ctx.globalAlpha = 1;
  }

  // ---------- shooting stars ----------
  _meteors(ctx, w, h, t, view) {
    if (t > this.nextMeteor && !view.calm) {
      // now and then two at once, from the same corner of the sky
      const pair = Math.random() < 0.2;
      const left = Math.random() < 0.5;
      const angle = (left ? 0 : Math.PI) + (left ? 1 : -1) * (0.35 + Math.random() * 0.4);
      const x0 = w * (left ? 0.1 + Math.random() * 0.5 : 0.4 + Math.random() * 0.5), y0 = h * (0.02 + Math.random() * 0.3);
      for (let i = 0; i < (pair ? 2 : 1); i++) {
        this.meteors.push({ x: x0 + i * 40, y: y0 + i * 26, angle: angle + i * 0.04, born: t + i * 0.35,
                            len: 300 + Math.random() * 240, dur: 0.75 + Math.random() * 0.4 });
      }
      this.nextMeteor = t + 7 + Math.random() * 10;
    }
    const rgb = this.look.palette.meteor;
    this.meteors = this.meteors.filter((m) => t - m.born < m.dur);
    for (const m of this.meteors) {
      const p = (t - m.born) / m.dur;
      if (p < 0) continue;
      const fade = Math.min(1, p / 0.12) * Math.min(1, (1 - p) / 0.35);
      const dx = Math.cos(m.angle), dy = Math.sin(m.angle);
      const hx = m.x + dx * m.len * p, hy = m.y + dy * m.len * p + m.len * 0.05 * p * p;
      const tail = m.len * 0.3 * Math.min(1, p * 3);
      const tx = hx - dx * tail, ty = hy - dy * tail;
      const trail = ctx.createLinearGradient(hx, hy, tx, ty);
      trail.addColorStop(0, `rgba(${rgb}, ${0.85 * fade})`);
      trail.addColorStop(1, `rgba(${rgb}, 0)`);
      ctx.strokeStyle = trail;
      ctx.lineCap = "round";
      ctx.globalAlpha = 0.25;
      ctx.lineWidth = 3.2;
      ctx.beginPath(); ctx.moveTo(hx, hy); ctx.lineTo(tx, ty); ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.lineWidth = 1.3;
      ctx.beginPath(); ctx.moveTo(hx, hy); ctx.lineTo(tx, ty); ctx.stroke();
      ctx.globalAlpha = fade;
      ctx.drawImage(this.look.meteor, hx - 7, hy - 7, 14, 14);
      ctx.globalAlpha = 1;
    }
    ctx.lineCap = "butt";
  }

  /** The edges of the sky a little darker, so the middle opens up. */
  _vignetteOn(ctx, w, h) {
    if (!this._vignette || this._vignette.w !== w || this._vignette.h !== h) {
      const v = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.35, w / 2, h / 2, Math.max(w, h) * 0.78);
      v.addColorStop(0, "rgba(0, 0, 0, 0)");
      v.addColorStop(1, "rgba(0, 0, 0, 0.32)");
      this._vignette = { w, h, v };
    }
    ctx.fillStyle = this._vignette.v;
    ctx.fillRect(0, 0, w, h);
  }
}
