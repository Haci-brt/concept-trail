// Inline stroke icons (24px grid). icon("search", 16) → SVG markup string.

const P = {
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4-4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  minus: '<path d="M5 12h14"/>',
  square: '<rect x="5.5" y="5.5" width="13" height="13" rx="1.5"/>',
  restore: '<rect x="4.5" y="8.5" width="11" height="11" rx="1.5"/><path d="M8.5 8.5V6A1.5 1.5 0 0 1 10 4.5h8A1.5 1.5 0 0 1 19.5 6v8a1.5 1.5 0 0 1-1.5 1.5h-2.5"/>',
  chevronRight: '<path d="m9 6 6 6-6 6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  chevronUp: '<path d="m6 15 6-6 6 6"/>',
  folder: '<path d="M3.5 7.5A2 2 0 0 1 5.5 5.5H9l2 2.2h7.5a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  folderPlus: '<path d="M3.5 7.5A2 2 0 0 1 5.5 5.5H9l2 2.2h7.5a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/><path d="M12 11v5M9.5 13.5h5"/>',
  vault: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M3.5 9h17M8 13.5h3"/>',
  file: '<path d="M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z"/><path d="M13.5 3.5V9H19M8.5 13h7M8.5 16.5h4.5"/>',
  filePlus: '<path d="M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z"/><path d="M13.5 3.5V9H19M12 12v5.5M9.25 14.75h5.5"/>',
  play: '<path d="M8 5.8v12.4a.9.9 0 0 0 1.4.8l9.6-6.2a.9.9 0 0 0 0-1.6L9.4 5A.9.9 0 0 0 8 5.8z"/>',
  bold: '<path d="M7.5 5h5.25a3.5 3.5 0 0 1 0 7H7.5zM7.5 12h6a3.5 3.5 0 0 1 0 7h-6z"/>',
  italic: '<path d="M10.5 5h8M5.5 19h8M14.5 5l-5 14"/>',
  list: '<path d="M9.5 6.5h10M9.5 12h10M9.5 17.5h10"/><circle cx="5" cy="6.5" r=".9" fill="currentColor"/><circle cx="5" cy="12" r=".9" fill="currentColor"/><circle cx="5" cy="17.5" r=".9" fill="currentColor"/>',
  listOrdered: '<path d="M10.5 6.5h9M10.5 12h9M10.5 17.5h9M4 5l1.5-1v4.5M3.75 14.25a1.4 1.4 0 0 1 2.5.9c0 .9-2.5 2-2.5 3.35h2.6"/>',
  listChecks: '<path d="m3.5 6.5 1.6 1.6L8 5.2M3.5 13.5l1.6 1.6L8 12.2M11.5 6.5h9M11.5 13.5h9M11.5 19h9"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.7"/><path d="m20.5 15.5-4.5-4.5-9.5 8.5"/>',
  highlighter: '<path d="m9 11.5-4.5 4.5V19h3l4.5-4.5"/><path d="m14.5 5.5 4 4-5.5 5.5-4-4z"/><path d="M13 20h7"/>',
  code: '<path d="m8.5 7.5-4.5 4.5 4.5 4.5M15.5 7.5l4.5 4.5-4.5 4.5"/>',
  quote: '<path d="M4.5 7.5v4.5h4V7.5zM4.5 12c0 2.5-.5 4-2 5M14.5 7.5v4.5h4V7.5zM14.5 12c0 2.5-.5 4-2 5"/>',
  sparkles: '<path d="M11 3.5 12.9 9l5.6 2-5.6 2L11 18.5 9.1 13l-5.6-2 5.6-2z"/><path d="M18.5 15.5l.75 1.75 1.75.75-1.75.75-.75 1.75-.75-1.75L16 18l1.75-.75z"/>',
  sparkle: '<path d="M12 3c.6 4.4 2.6 6.4 7 7-4.4.6-6.4 2.6-7 7-.6-4.4-2.6-6.4-7-7 4.4-.6 6.4-2.6 7-7z"/>',
  tree: '<rect x="2.5" y="9.5" width="6" height="5" rx="1.5"/><rect x="15.5" y="3.5" width="6" height="5" rx="1.5"/><rect x="15.5" y="15.5" width="6" height="5" rx="1.5"/><path d="M8.5 12h2.5a1.5 1.5 0 0 0 1.5-1.5v-3A1.5 1.5 0 0 1 14 6h1.5M12.5 12v4.5A1.5 1.5 0 0 0 14 18h1.5"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.75"/>',
  eyeOff: '<path d="M10.6 5.6A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 0 1-2.4 3.1M6.5 7A15.4 15.4 0 0 0 2.5 12S6 18.5 12 18.5a9 9 0 0 0 4.6-1.3M4 4l16 16M10 10.1a2.75 2.75 0 0 0 3.9 3.9"/>',
  keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6.5 10h.01M10 10h.01M13.5 10h.01M17 10h.01M7.5 14h9"/>',
  help: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.6a2.5 2.5 0 0 1 4.9.8c0 1.7-2.5 2.2-2.5 3.6M12 16.8h.01"/>',
  message: '<path d="M4.5 6A2.5 2.5 0 0 1 7 3.5h10A2.5 2.5 0 0 1 19.5 6v7.5A2.5 2.5 0 0 1 17 16h-6.5l-4.5 4v-4H7a2.5 2.5 0 0 1-2.5-2.5z"/>',
  send: '<path d="M20.5 3.5 10 14M20.5 3.5 14 20.5l-4-6.5-6.5-4z"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  checkCircle: '<circle cx="12" cy="12" r="8.5"/><path d="m8.25 12.25 2.5 2.5 5-5"/>',
  pencil: '<path d="M16 4.5a2.1 2.1 0 0 1 3 3L8.5 18l-4 1 1-4z"/><path d="m14 6.5 3 3"/>',
  lightbulb: '<path d="M9 17.5h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.7.5 1.1 1.3 1.1 2.1v.1h5v-.1c0-.8.4-1.6 1.1-2.1A6 6 0 0 0 12 3z"/>',
  questionSquare: '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="M9.6 9.6a2.5 2.5 0 0 1 4.9.8c0 1.7-2.5 2.2-2.5 3.6M12 16.8h.01"/>',
  trash: '<path d="M4.5 7h15M10 11v6M14 11v6M6.5 7l.9 11.5a2 2 0 0 0 2 1.5h5.2a2 2 0 0 0 2-1.5L17.5 7M9.5 7V5a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 14.5 5v2"/>',
  rename: '<path d="M12.5 19.5h8"/><path d="M15.5 4.5a2.1 2.1 0 0 1 3 3L7.5 18.5l-4 1 1-4z"/>',
  hash: '<path d="M5 9h15M4 15h15M10.5 3.5l-2 17M15.5 3.5l-2 17"/>',
  tag: '<path d="M3.5 12.1V5A1.5 1.5 0 0 1 5 3.5h7.1a1.5 1.5 0 0 1 1 .4l6.9 6.9a1.5 1.5 0 0 1 0 2.2l-7.1 7.1a1.5 1.5 0 0 1-2.2 0l-6.9-6.9a1.5 1.5 0 0 1-.4-1z"/><circle cx="8.25" cy="8.25" r="1.25"/>',
  columns: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M12 4.5v15"/>',
  fit: '<path d="M4.5 9V6A1.5 1.5 0 0 1 6 4.5h3M15 4.5h3A1.5 1.5 0 0 1 19.5 6v3M19.5 15v3a1.5 1.5 0 0 1-1.5 1.5h-3M9 19.5H6A1.5 1.5 0 0 1 4.5 18v-3"/><rect x="9" y="9" width="6" height="6" rx="1"/>',
  zoomIn: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4-4M8.5 11h5M11 8.5v5"/>',
  zoomOut: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4-4M8.5 11h5"/>',
  sprout: '<path d="M12 20.5V12"/><path d="M12 12.5c0-4.2 2.8-7 7.5-7 0 4.7-2.8 7.5-7.5 7z"/><path d="M12 14.5c0-3.3-2.3-5.5-6.5-5.5 0 3.8 2.3 6 6.5 5.5z"/>',
  panelLeft: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M9 4.5v15"/>',
  panelRight: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M15 4.5v15"/>',
  more: '<circle cx="5.5" cy="12" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="18.5" cy="12" r="1.2" fill="currentColor"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9.5 3v3M14.5 3v3M9.5 18v3M14.5 18v3M3 9.5h3M3 14.5h3M18 9.5h3M18 14.5h3"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  refresh: '<path d="M19.5 11A7.5 7.5 0 0 0 6 6.8L4.5 8.5M4.5 4.5v4h4M4.5 13A7.5 7.5 0 0 0 18 17.2l1.5-1.7M19.5 19.5v-4h-4"/>',
  enter: '<path d="M19.5 5v6.5a2 2 0 0 1-2 2H5"/><path d="m9 9.5-4 4 4 4"/>',
  arrowRight: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  history: '<path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5"/><path d="M4 4.5v4h4M12 8v4.5l3 1.75"/>',
  alert: '<path d="M12 4 21 19.5H3z"/><path d="M12 10v4.5M12 17h.01"/>',
  command: '<path d="M9 6.5A2.5 2.5 0 1 0 6.5 9H9zM15 6.5A2.5 2.5 0 1 1 17.5 9H15zM9 17.5A2.5 2.5 0 1 1 6.5 15H9zM15 17.5a2.5 2.5 0 1 0 2.5-2.5H15zM9 9h6v6H9z"/>',
  settings: '<circle cx="12" cy="12" r="3.2"/><path d="M19.4 13.5a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5v.2a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H2a2 2 0 1 1 0-4h.2a1.6 1.6 0 0 0 1.4-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V2a2 2 0 1 1 4 0v.2a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.2a1.6 1.6 0 0 0-1.4 1z"/>',
  cloud: '<path d="M7 18.5h10.2a3.8 3.8 0 0 0 .4-7.6 5.6 5.6 0 0 0-10.8-1.3A4 4 0 0 0 7 18.5z"/>',
  key: '<circle cx="8" cy="12" r="3.8"/><path d="M11.8 12H21M18 12v3.2M15 12v2.4"/>',
  zap: '<path d="M13 2.5 5 13.5h6l-1 8 8-11h-6z"/>',
  wand: '<path d="m4 20 11-11M14 4v2M19 9h2M18 5l-1.5 1.5M14 9l1 1"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.3 3.6 5.1 3.6 8.5s-1.2 6.2-3.6 8.5c-2.4-2.3-3.6-5.1-3.6-8.5s1.2-6.2 3.6-8.5z"/>',
  copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6A1.5 1.5 0 0 0 14 4.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
  download: '<path d="M12 4.5v11M7.5 11l4.5 4.5 4.5-4.5M5 19.5h14"/>',
  sun: '<circle cx="12" cy="12" r="3.6"/><path d="M12 2.5v2M12 19.5v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2.5 12h2m15 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 15.4A8.5 8.5 0 0 1 8.6 4 8.5 8.5 0 1 0 20 15.4z"/>',
  star: '<path d="m12 2.7 2.8 5.7 6.3.9-4.6 4.4 1.1 6.3L12 17l-5.6 3 1.1-6.3-4.6-4.4 6.3-.9z"/>',
};

export function icon(name, size = 16, extraClass = "") {
  const body = P[name] || P.help;
  return `<svg class="ico ${extraClass}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

let logoSeq = 0;

/** The app mark (assets/icon/concept-trail-small.svg): a trail of stars
 *  climbing to a bright one. Each copy gets its own gradient ids — the title
 *  bar and the welcome screen show it at once. */
export function logo(size = 20) {
  const id = `lg${++logoSeq}`;
  return `<svg class="logo" width="${size}" height="${size}" viewBox="0 0 32 32" aria-hidden="true">
    <defs>
      <linearGradient id="${id}s" x1="0.1" y1="0" x2="0.9" y2="1"><stop offset="0" stop-color="#1f3168"/><stop offset="1" stop-color="#08101f"/></linearGradient>
      <radialGradient id="${id}d" cx="0.76" cy="0.26" r="0.55"><stop offset="0" stop-color="#6fe0c4" stop-opacity="0.55"/><stop offset="1" stop-color="#6fe0c4" stop-opacity="0"/></radialGradient>
    </defs>
    <rect x=".5" y=".5" width="31" height="31" rx="8" fill="url(#${id}s)"/>
    <rect x=".5" y=".5" width="31" height="31" rx="8" fill="url(#${id}d)"/>
    <path d="M7 25 L12.5 19.5 L12 13.5 L23 9" fill="none" stroke="#c9c0ff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" stroke-opacity=".9"/>
    <circle cx="7" cy="25" r="2.3" fill="#ffd166"/><circle cx="12.5" cy="19.5" r="2.4" fill="#7cc0ff"/><circle cx="12" cy="13.5" r="2.2" fill="#b9a6ff"/>
    <path d="M23 3.5 L24.3 7.7 L28.5 9 L24.3 10.3 L23 14.5 L21.7 10.3 L17.5 9 L21.7 7.7 Z" fill="#f2fffa"/>
    <circle cx="23" cy="9" r="1.9" fill="#fff"/>
  </svg>`;
}
