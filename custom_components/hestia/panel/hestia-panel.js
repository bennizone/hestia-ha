/*
 * Hestia — Config-Panel (Custom-Element, kein Build-Step, kein Framework).
 *
 * Design GELOCKT (Benni 2026-07-10): HA-nativ (Theme-Vars → aktives HA-Theme, Dark-Default),
 * responsive Master-Detail (breit = Seiten-Spalte / schmal = Slide-over-Sheet), einklappbarer
 * Rail. Drei Zustände pro Gerät: Aktiv · Deaktiviert (Metadaten bleiben) · Nicht-hinzugefügt.
 *
 * Daten via WS-API (websocket.py) gegen den Config-Store (.storage): list / candidates / set.
 * Dieser Block liefert nur die **Exposure**-Sektion; die übrigen Nav-Punkte sind vorgemerkt.
 */

const DOM_LABEL = {
  light: "Licht", switch: "Steckdose", media_player: "Medien", cover: "Rollladen",
  sensor: "Sensor", binary_sensor: "Sensor", lock: "Schloss", climate: "Klima",
  fan: "Ventilator", number: "Regler", select: "Auswahl", button: "Taster",
  scene: "Szene", vacuum: "Sauger", humidifier: "Luftfeuchter",
};

// Kompakte Domain-Icons (Feather/HA-Stil). Fallback = Punkt.
const DOM_ICON = {
  light: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.2 1 2.5h6c0-1.3.3-1.8 1-2.5A6 6 0 0 0 12 3Z"/>',
  switch: '<path d="M6 3h12v4a6 6 0 0 1-12 0V3Z"/><path d="M9 20h6M12 13v7"/>',
  media_player: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
  cover: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M4 8h16M9 3v5M15 3v5"/>',
  sensor: '<path d="M12 2v4M12 18v4"/><circle cx="12" cy="12" r="4"/><path d="m4.9 4.9 2.8 2.8M16.3 16.3l2.8 2.8"/>',
  binary_sensor: '<path d="M3 12h4l2-5 3 10 2-5h7"/>',
  lock: '<rect x="3" y="11" width="18" height="10" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  climate: '<path d="M3 12h4l2-5 3 10 2-5h7"/>',
  fan: '<path d="M12 12v9M12 12 4 8M12 12l8-4M12 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"/>',
};
const ICON_DOT = '<circle cx="12" cy="12" r="3"/>';

const svg = (inner, w = 18) =>
  `<svg viewBox="0 0 24 24" width="${w}" height="${w}" fill="none" stroke="currentColor" ` +
  `stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const domLabel = (d) => DOM_LABEL[d] || d;
const domIcon = (d) => svg(DOM_ICON[d] || ICON_DOT);

// pct-steuerbare Domains → welches Attribut das WRITE-Limit-Mapping betrifft (Spiegel mapping.PCT_ATTRS).
// Das Modell bleibt immer im 0–100-Raum; die Range mappt nur den an HA gesendeten Steuerwert.
const PCT_ATTR = { light: "Helligkeit", media_player: "Lautstärke", cover: "Position", fan: "Stufe" };
// Spiegel von mapping.apply / mapping.norm (Python) — nur für die Live-Vorschau.
const mapReal = (v, lo, hi) => Math.round(lo + Math.max(0, Math.min(100, v)) / 100 * (hi - lo));
const rangeState = (lo, hi) =>
  (lo === 0 && hi === 100) ? "identity"
  : !(lo >= 0 && hi <= 100 && lo < hi) ? "invalid" : "mapped";

const STYLE = `
:host {
  --sans: Roboto, "Helvetica Neue", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: ui-monospace, "Roboto Mono", "SF Mono", Menlo, Consolas, monospace;
  --ground: var(--primary-background-color, #111111);
  --surface: var(--card-background-color, #1c1c1c);
  --surface-2: var(--secondary-background-color, #202020);
  --line: var(--divider-color, #2c2c2c);
  --line-strong: var(--divider-color, #3a3a3a);
  --ink: var(--primary-text-color, #e4e4e4);
  --ink-2: var(--secondary-text-color, #9a9a9a);
  --ink-3: var(--disabled-text-color, #6f6f6f);
  --accent: var(--primary-color, #03a9f4);
  --accent-strong: var(--light-primary-color, #58c4fb);
  --accent-ink: var(--text-primary-color, #ffffff);
  --accent-soft: color-mix(in srgb, var(--accent) 16%, transparent);
  --accent-line: color-mix(in srgb, var(--accent) 34%, transparent);
  --warn: var(--warning-color, #f9a825);
  --warn-soft: color-mix(in srgb, var(--warn) 18%, transparent);
  --danger: var(--error-color, #ef5350);
  --danger-soft: color-mix(in srgb, var(--danger) 18%, transparent);
  --r-sm: 8px; --r: var(--ha-card-border-radius, 12px);
  --shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,.35));
  --shadow-lg: 0 10px 34px rgba(0,0,0,.5);
  --focus: 0 0 0 2px var(--ground), 0 0 0 4px var(--accent);
  display: block; background: var(--ground); color: var(--ink);
  font-family: var(--sans); font-size: 14px; line-height: 1.5; min-height: 100%;
}
* { box-sizing: border-box; }
h1, h2, h3, h4 { margin: 0; font-weight: 620; letter-spacing: -0.01em; }
button, input, textarea { font: inherit; color: inherit; }
::selection { background: var(--accent-soft); }

.app { display: grid; grid-template-columns: 250px 1fr; min-height: 100vh; transition: grid-template-columns .2s ease; }
.app.rail { grid-template-columns: 66px 1fr; }

.rail-toggle { margin-left: auto; display: grid; place-items: center; width: 28px; height: 28px; flex: none;
  border: 1px solid var(--line-strong); background: var(--surface-2); color: var(--ink-2); border-radius: 7px; cursor: pointer; }
.rail-toggle svg { transition: transform .2s; }
.rail-toggle:hover { color: var(--ink); border-color: var(--ink-3); }
.app.rail .brand { justify-content: center; padding: 20px 0 16px; }
.app.rail .brand > div:last-child { display: none; }
.app.rail .nav { padding: 6px 10px; }
.app.rail .nav .group-label { display: none; }
.app.rail .nav a { justify-content: center; padding: 10px 0; }
.app.rail .nav a .lbl, .app.rail .nav a .tag { display: none; }
.app.rail .nav a.active::before { display: none; }
.app.rail .side-foot { justify-content: center; padding: 14px 0; }
.app.rail .side-foot .dot, .app.rail .side-foot .foot-txt { display: none; }
.app.rail .rail-toggle { margin: 0; }
.app.rail .rail-toggle svg { transform: rotate(180deg); }

.side { background: var(--surface); border-right: 1px solid var(--line); display: flex; flex-direction: column;
  position: sticky; top: 0; height: 100vh; }
.brand { display: flex; align-items: center; gap: 11px; padding: 20px 20px 16px; }
.brand .mark { width: 34px; height: 34px; border-radius: 9px; flex: none;
  background: radial-gradient(120% 120% at 30% 20%, var(--accent-strong), var(--accent));
  display: grid; place-items: center; color: var(--accent-ink); box-shadow: var(--shadow); }
.brand .name { font-size: 15px; font-weight: 680; letter-spacing: .14em; }
.brand .sub { font-size: 11px; color: var(--ink-3); letter-spacing: .08em; text-transform: uppercase; margin-top: 1px; }

.nav { padding: 6px 12px; display: flex; flex-direction: column; gap: 2px; overflow-y: auto; }
.nav .group-label { font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; color: var(--ink-3); padding: 14px 10px 6px; }
.nav a { display: flex; align-items: center; gap: 11px; padding: 8px 10px; border-radius: var(--r-sm);
  color: var(--ink-2); text-decoration: none; font-weight: 500; position: relative; cursor: pointer; }
.nav a svg { width: 17px; height: 17px; flex: none; opacity: .85; }
.nav a .tag { margin-left: auto; font-size: 11px; color: var(--ink-3); font-variant-numeric: tabular-nums; }
.nav a:hover { background: var(--surface-2); color: var(--ink); }
.nav a.active { background: var(--accent-soft); color: var(--accent-strong); }
.nav a.active svg { opacity: 1; }
.nav a.active::before { content: ""; position: absolute; left: -12px; top: 8px; bottom: 8px; width: 3px;
  background: var(--accent); border-radius: 0 3px 3px 0; }
.nav a.soon { color: var(--ink-3); cursor: default; }
.nav a.soon:hover { background: none; color: var(--ink-3); }
.nav a.soon .tag { font-size: 10px; letter-spacing: .04em; text-transform: uppercase; }

.side-foot { margin-top: auto; padding: 14px 18px; border-top: 1px solid var(--line);
  display: flex; align-items: center; gap: 9px; font-size: 12px; color: var(--ink-2); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); flex: none; box-shadow: 0 0 0 3px var(--accent-soft); }
.side-foot .url { font-family: var(--mono); font-size: 11.5px; color: var(--ink-3); }

.main { display: flex; flex-direction: column; min-width: 0; }
.topbar { display: flex; align-items: flex-end; gap: 20px; padding: 26px 30px 18px;
  border-bottom: 1px solid var(--line); background: var(--ground); position: sticky; top: 0; z-index: 5; }
.topbar .titlewrap { min-width: 0; }
.eyebrow { font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--accent-strong); font-weight: 600; }
.topbar h1 { font-size: 23px; margin-top: 4px; }
.topbar p { margin: 5px 0 0; color: var(--ink-2); max-width: 62ch; }
.topbar .actions { margin-left: auto; display: flex; gap: 10px; align-items: center; flex: none; }

.btn { display: inline-flex; align-items: center; gap: 7px; padding: 8px 14px; border-radius: var(--r-sm);
  border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink); font-weight: 550; cursor: pointer; white-space: nowrap; }
.btn svg { width: 15px; height: 15px; }
.btn:hover { border-color: var(--ink-3); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
.btn.primary:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
.btn:disabled { opacity: .5; cursor: default; }
.btn:focus-visible, a:focus-visible, input:focus-visible, textarea:focus-visible { outline: none; box-shadow: var(--focus); }

.content { display: grid; grid-template-columns: minmax(0,1fr) 344px; gap: 0; flex: 1; }
.col { min-width: 0; padding: 22px 30px 40px; }
.col.detail { border-left: 1px solid var(--line); background: var(--surface); padding: 0; }
.col.detail.empty { display: grid; place-items: center; color: var(--ink-3); font-size: 13px; padding: 30px; text-align: center; }

.tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 22px; }
.tile { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r); padding: 13px 15px; }
.tile .k { font-size: 11.5px; color: var(--ink-3); letter-spacing: .02em; }
.tile .v { font-size: 26px; font-weight: 640; margin-top: 3px; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.tile .v small { font-size: 14px; color: var(--ink-3); font-weight: 500; }
.tile.accent { background: var(--accent-soft); border-color: var(--accent-line); }
.tile.accent .v { color: var(--accent-strong); }
.tile.warn { background: var(--warn-soft); border-color: color-mix(in srgb, var(--warn) 30%, transparent); }
.tile.warn .v { color: var(--warn); }

.toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.search { position: relative; flex: 1; min-width: 200px; }
.search svg { position: absolute; left: 11px; top: 50%; transform: translateY(-50%); width: 16px; height: 16px; color: var(--ink-3); }
.search input { width: 100%; padding: 9px 12px 9px 34px; border-radius: var(--r-sm); border: 1px solid var(--line-strong); background: var(--surface); }
.search input::placeholder { color: var(--ink-3); }
.filters { display: flex; gap: 6px; flex-wrap: wrap; }
.chip-btn { padding: 7px 12px; border-radius: 20px; border: 1px solid var(--line-strong); background: var(--surface);
  color: var(--ink-2); cursor: pointer; font-size: 13px; font-weight: 500; }
.chip-btn.on { background: var(--ink); color: var(--ground); border-color: var(--ink); }
.chip-btn:hover:not(.on) { border-color: var(--ink-3); }

.area { margin-top: 20px; }
.area:first-of-type { margin-top: 0; }
.area-head { display: flex; align-items: center; gap: 10px; padding: 0 4px 9px; }
.area-head h3 { font-size: 13.5px; }
.area-head .floor { font-size: 11px; color: var(--ink-3); text-transform: uppercase; letter-spacing: .06em; }
.area-head .count { margin-left: auto; font-size: 12px; color: var(--ink-3); font-variant-numeric: tabular-nums; }
.area-head .rule { flex: 1; height: 1px; background: var(--line); }

.rows { display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r); overflow: hidden; }
.row { display: grid; grid-template-columns: 22px minmax(0,1.3fr) minmax(0,1.5fr) auto; align-items: center;
  gap: 14px; padding: 11px 15px; cursor: pointer; border-top: 1px solid var(--line); }
.row:first-child { border-top: none; }
.row:hover { background: var(--surface-2); }
.row.sel { background: var(--accent-soft); }
.row .dom { color: var(--ink-3); display: grid; place-items: center; }
.row .dom svg { width: 18px; height: 18px; }
.row.sel .dom { color: var(--accent-strong); }
.namecell { min-width: 0; }
.namecell .nm { font-weight: 560; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.namecell .eid { font-family: var(--mono); font-size: 11.5px; color: var(--ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.aliascell { display: flex; gap: 5px; flex-wrap: wrap; min-width: 0; }
.alias { font-size: 11.5px; padding: 2px 8px; border-radius: 5px; background: var(--surface-2); color: var(--ink-2); border: 1px solid var(--line); white-space: nowrap; }
.row.sel .alias { background: var(--surface); }
.statecell { display: flex; justify-content: flex-end; }

.pill { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 600;
  padding: 3px 9px 3px 7px; border-radius: 20px; white-space: nowrap; }
.pill .d { width: 6px; height: 6px; border-radius: 50%; }
.pill.exposed { background: var(--accent-soft); color: var(--accent-strong); }
.pill.exposed .d { background: var(--accent); }
.pill.hidden { background: var(--surface-2); color: var(--ink-3); }
.pill.hidden .d { background: var(--ink-3); }
.pill.offline { background: var(--warn-soft); color: var(--warn); }
.pill.offline svg { width: 13px; height: 13px; margin-right: -1px; }

.empty-state { padding: 50px 20px; text-align: center; color: var(--ink-3); }
.empty-state svg { width: 34px; height: 34px; opacity: .6; margin-bottom: 10px; }
.empty-state b { color: var(--ink-2); display: block; font-weight: 600; margin-bottom: 4px; }

.detail-head { padding: 20px 22px 16px; border-bottom: 1px solid var(--line); position: relative; }
.detail-close { display: none; position: absolute; top: 15px; right: 16px; place-items: center; width: 32px; height: 32px;
  border: 1px solid var(--line-strong); background: var(--surface-2); color: var(--ink-2); border-radius: 8px; cursor: pointer; }
.detail-close svg { width: 16px; height: 16px; }
.detail-close:hover { color: var(--ink); border-color: var(--ink-3); }
.detail-head .kicker { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--ink-3); }
.detail-head h2 { font-size: 18px; margin-top: 6px; }
.detail-head .eid { font-family: var(--mono); font-size: 12px; color: var(--ink-3); margin-top: 6px; }
.detail-body { padding: 18px 22px 26px; display: flex; flex-direction: column; gap: 18px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field > label { font-size: 12px; font-weight: 600; color: var(--ink-2); display: flex; align-items: center; gap: 6px; }
.field .hint { font-size: 11.5px; color: var(--ink-3); font-weight: 400; }
.inp, .ta { width: 100%; padding: 9px 11px; border-radius: var(--r-sm); border: 1px solid var(--line-strong); background: var(--ground); }
.ta { resize: vertical; min-height: 58px; line-height: 1.45; }
.alias-edit { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.alias-edit .alias { display: inline-flex; align-items: center; gap: 6px; padding: 4px 6px 4px 9px; background: var(--ground); }
.alias-edit .alias button { border: none; background: none; color: var(--ink-3); cursor: pointer; padding: 0; line-height: 1; font-size: 14px; }
.alias-edit .add-inp { width: 96px; padding: 4px 8px; border-radius: 5px; border: 1px dashed var(--line-strong); background: none; color: var(--ink); font-size: 11.5px; }

.toggle-row { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 13px 14px; border: 1px solid var(--line); border-radius: var(--r); background: var(--ground); }
.toggle-row .tl { font-size: 13px; font-weight: 600; }
.toggle-row .tl small { display: block; font-weight: 400; color: var(--ink-3); font-size: 11.5px; margin-top: 2px; }
.switch { position: relative; width: 40px; height: 23px; flex: none; }
.switch input { position: absolute; opacity: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; }
.switch .track { position: absolute; inset: 0; background: var(--line-strong); border-radius: 20px; transition: background .16s; }
.switch .knob { position: absolute; top: 2.5px; left: 2.5px; width: 18px; height: 18px; background: #fff; border-radius: 50%; transition: transform .16s; box-shadow: 0 1px 2px rgba(0,0,0,.3); }
.switch input:checked + .track { background: var(--accent); }
.switch input:checked + .track + .knob { transform: translateX(17px); }

.compiler { border: 1px solid var(--accent-line); border-radius: var(--r); background: var(--accent-soft); overflow: hidden; }
.compiler .ch { display: flex; align-items: center; gap: 8px; padding: 10px 13px; font-size: 12px; font-weight: 600; color: var(--accent-strong); border-bottom: 1px solid var(--accent-line); }
.compiler .ch svg { width: 15px; height: 15px; }
.compiler pre { margin: 0; padding: 12px 13px; font-family: var(--mono); font-size: 11.5px; line-height: 1.65; color: var(--ink-2); white-space: pre-wrap; word-break: break-word; }
.compiler pre b { color: var(--ink); font-weight: 600; }

/* ── Limits & Mapping (WRITE-Range, Geräte-Seite — NICHT was das Modell sieht) ── */
.limits .rng-lead { font-size: 11.5px; color: var(--ink-3); line-height: 1.5; margin: -1px 0 2px; }
.rng-row { display: flex; align-items: center; gap: 10px; }
.rng-inp { display: inline-flex; align-items: center; gap: 6px; flex: 1;
  border: 1px solid var(--line-strong); border-radius: var(--r-sm); background: var(--ground); padding: 0 11px; }
.rng-inp span { font-size: 11px; color: var(--ink-3); letter-spacing: .02em; }
.rng-inp input { border: none; background: none; padding: 9px 0; width: 100%; text-align: right; font-variant-numeric: tabular-nums; -moz-appearance: textfield; }
.rng-inp:focus-within { box-shadow: var(--focus); border-color: var(--accent); }
.rng-inp input:focus-visible { box-shadow: none; outline: none; }
.rng-arrow { color: var(--ink-3); font-weight: 600; }
.rng-preview { font-size: 11.5px; font-family: var(--mono); color: var(--ink-3); padding: 4px 2px 0; line-height: 1.6; }
.rng-preview.mapped { color: var(--ink-2); }
.rng-preview.mapped b { color: var(--accent-strong); font-weight: 600; }
.rng-preview.invalid { color: var(--warn); }

.offline-note { display: flex; gap: 10px; align-items: flex-start; padding: 11px 13px; border-radius: var(--r);
  background: var(--warn-soft); border: 1px solid color-mix(in srgb, var(--warn) 32%, transparent); font-size: 12.5px; line-height: 1.5; color: var(--ink-2); }
.offline-note svg { width: 18px; height: 18px; flex: none; color: var(--warn); margin-top: 1px; }
.offline-note b { color: var(--ink); font-weight: 600; }
.backup-note { display: flex; gap: 8px; align-items: center; font-size: 11.5px; color: var(--ink-3); }
.backup-note svg { width: 15px; height: 15px; flex: none; }
.remove-link { background: none; border: none; color: var(--danger); cursor: pointer; font-size: 12px; padding: 0; align-self: flex-start; }
.remove-link:hover { text-decoration: underline; }
.save-bar { display: flex; gap: 10px; }
.save-bar .btn { flex: 1; justify-content: center; }

.banner { display: flex; gap: 11px; align-items: flex-start; padding: 12px 14px; border-radius: var(--r);
  background: var(--surface-2); border: 1px solid var(--line); margin-bottom: 20px; font-size: 13px; color: var(--ink-2); }
.banner svg { width: 17px; height: 17px; flex: none; color: var(--accent-strong); margin-top: 1px; }
.banner b { color: var(--ink); font-weight: 600; }

/* ── Add-Dialog (Modal) ── */
.scrim { position: fixed; inset: 0; background: rgba(0,0,0,.5); opacity: 0; pointer-events: none; transition: opacity .2s; z-index: 40; }
.scrim.on { opacity: 1; pointer-events: auto; }
.modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -48%); width: min(560px, 94vw); max-height: 84vh;
  background: var(--surface); border: 1px solid var(--line-strong); border-radius: var(--r); box-shadow: var(--shadow-lg);
  z-index: 41; display: none; flex-direction: column; overflow: hidden; }
.modal.on { display: flex; }
.modal-head { padding: 18px 20px 14px; border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 12px; }
.modal-head h2 { font-size: 17px; }
.modal-head .btn { margin-left: auto; }
.modal .search { margin: 14px 20px 6px; flex: none; }
.modal-list { overflow-y: auto; padding: 6px 12px 16px; }
.cand { display: grid; grid-template-columns: 22px minmax(0,1fr) auto; align-items: center; gap: 12px; padding: 10px 12px; border-radius: var(--r-sm); }
.cand:hover { background: var(--surface-2); }
.cand .dom { color: var(--ink-3); display: grid; place-items: center; }
.cand .nm { font-weight: 550; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cand .eid { font-family: var(--mono); font-size: 11px; color: var(--ink-3); }
.cand .area-tag { font-size: 11px; color: var(--ink-3); margin-right: 8px; }
.cand .add-btn { padding: 5px 11px; font-size: 12.5px; }

/* ── Helfer-View ── */
.content.single { grid-template-columns: 1fr; }
.hrow { display: grid; grid-template-columns: 22px minmax(0,1.6fr) auto 84px auto; align-items: center; gap: 14px; padding: 11px 15px; border-top: 1px solid var(--line); }
.hrow:first-child { border-top: none; }
.hrow .dom { color: var(--ink-3); display: grid; place-items: center; }
.hrow .dom svg { width: 18px; height: 18px; }
.hval { font-variant-numeric: tabular-nums; font-weight: 560; color: var(--ink); white-space: nowrap; text-align: right; }
.hval small { color: var(--ink-3); font-weight: 400; }
.htype { font-size: 11.5px; color: var(--ink-3); text-align: right; }
.hdel { align-self: center; white-space: nowrap; }
.hc-body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 16px; }
.hc-foot { padding: 14px 20px; border-top: 1px solid var(--line); flex: none; }
.hc-foot .btn { width: 100%; justify-content: center; }
.hc-search { margin: 0 0 8px !important; }
.seg { display: inline-flex; gap: 4px; background: var(--surface-2); border: 1px solid var(--line-strong); border-radius: var(--r-sm); padding: 3px; flex-wrap: wrap; }
.seg-b { border: none; background: none; color: var(--ink-2); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-weight: 500; font-size: 12.5px; }
.seg-b.on { background: var(--accent); color: var(--accent-ink); }
.seg-b:hover:not(.on) { color: var(--ink); }
.checklist { max-height: 210px; overflow-y: auto; border: 1px solid var(--line-strong); border-radius: var(--r-sm); background: var(--ground); }
.chk { display: grid; grid-template-columns: auto minmax(0,1fr) auto; align-items: center; gap: 10px; padding: 8px 11px; cursor: pointer; border-top: 1px solid var(--line); }
.chk:first-child { border-top: none; }
.chk:hover { background: var(--surface-2); }
.chk.on { background: var(--accent-soft); }
.chk input { accent-color: var(--accent); width: 15px; height: 15px; flex: none; }
.chk-nm { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chk-eid { font-family: var(--mono); font-size: 11px; color: var(--ink-3); white-space: nowrap; }
select.inp { cursor: pointer; }

/* ── Custom-Sätze ── */
.srow { display: grid; grid-template-columns: 20px minmax(0,1.7fr) auto 96px auto; align-items: center; gap: 14px; padding: 12px 15px; border-top: 1px solid var(--line); }
.srow:first-child { border-top: none; }
.srow .dom { color: var(--ink-3); display: grid; place-items: center; }
.srow .dom svg { width: 17px; height: 17px; }
.srow .phrases { display: flex; flex-wrap: wrap; gap: 5px; }
.srow .tgt { font-family: var(--mono); font-size: 11.5px; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.srow .smode { font-size: 11.5px; color: var(--ink-3); text-align: right; text-transform: capitalize; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { display: inline-flex; align-items: center; gap: 6px; background: var(--accent-soft); color: var(--ink); border-radius: 999px; padding: 4px 6px 4px 11px; font-size: 12.5px; }
.chip.ro { padding: 4px 11px; }
.chip-x { border: none; background: none; color: var(--ink-3); cursor: pointer; display: grid; place-items: center; padding: 0; line-height: 0; }
.chip-x:hover { color: var(--danger); }
.chip-x svg { width: 13px; height: 13px; }
.chipwrap { border: 1px solid var(--line-strong); border-radius: var(--r-sm); background: var(--ground); padding: 9px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chipwrap input { border: none; background: none; outline: none; color: var(--ink); font: inherit; flex: 1; min-width: 120px; padding: 4px; }
.radiolist { max-height: 240px; overflow-y: auto; border: 1px solid var(--line-strong); border-radius: var(--r-sm); background: var(--ground); }

.loading { padding: 60px 20px; text-align: center; color: var(--ink-3); }

@media (max-width: 1040px) {
  .content { grid-template-columns: 1fr; }
  .tiles { grid-template-columns: repeat(2, 1fr); }
  .row { grid-template-columns: 22px 1fr auto; }
  .aliascell { display: none; }
  .topbar { position: static; padding: 15px 18px 13px; }
  .topbar p { display: none; }
  .topbar h1 { font-size: 20px; }
  .topbar .actions .btn span { display: none; }
  .topbar .actions .btn.primary span { display: inline; }
  .col.detail { position: fixed; top: 0; right: 0; bottom: 0; width: min(440px, 94vw);
    border-left: 1px solid var(--line); background: var(--surface); transform: translateX(100%);
    transition: transform .24s cubic-bezier(.4,0,.2,1); z-index: 41; overflow-y: auto; box-shadow: var(--shadow-lg); }
  .col.detail.empty { display: none; }
  .detail-close { display: grid; }
  :host(.detail-open) .col.detail { transform: none; }
  :host(.detail-open) .scrim.detail { opacity: 1; pointer-events: auto; }
}
@media (max-width: 720px) {
  .app, .app.rail { grid-template-columns: 1fr; }
  .side { position: static; height: auto; }
  .nav { flex-direction: row; flex-wrap: wrap; }
  .nav .group-label, .side-foot { display: none; }
  .nav a.active::before { display: none; }
  .topbar { flex-wrap: wrap; }
  .topbar .actions { margin-left: 0; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
`;

class HestiaPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._rows = null;          // Exposure-Liste (added=True)
    this._selected = null;      // entity_id im Editor
    this._draft = null;         // { llm_name, aliases[], description, active }
    this._search = "";
    this._filter = "all";       // all | active | inactive | <domain>
    this._rail = false;
    this._addOpen = false;
    this._candidates = null;
    this._candSearch = "";
    this._loading = true;
    this._error = null;
    this._view = "exposure";    // exposure | helpers | settings | sentences
    this._helpers = null;       // Helfer-Liste (min_max/group)
    this._settings = null;      // Allgemein-Settings (llama_url/loop_depth/unsafe_mode)
    this._sDraft = null;        // Settings-Entwurf im Editor
    this._areas = [];           // HA-Areas (Anlege-Dialog)
    this._hcDraft = null;       // Helfer-Anlege-Entwurf
    this._hcSearch = "";
    this._sentences = null;     // Custom-Sätze-Liste
    this._scDraft = null;       // Satz-Anlege-Entwurf { phrases[], target_entity, mode, response }
    this._scSearch = "";        // Ziel-Entität-Picker-Suche
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._bootstrap();
  }
  get hass() { return this._hass; }

  async _bootstrap() {
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><div id="root"></div>`;
    this._root = this.shadowRoot.getElementById("root");
    this._renderShell();
    await this._loadRows();
  }

  async _loadRows() {
    this._loading = true; this._error = null; this._renderMain();
    try {
      const res = await this._hass.callWS({ type: "hestia/exposure/list" });
      this._rows = res.entities || [];
    } catch (e) {
      this._error = (e && e.message) || String(e);
      this._rows = [];
    }
    this._loading = false;
    this._renderMain();
  }

  // ── Shell (Sidebar + Topbar-Rahmen); Inhalt rendert _renderMain separat ──
  _renderShell() {
    const url = this._hass?.states?.["sensor.hestia_endpoint"] || "";
    this._root.innerHTML = `
      <div class="app${this._rail ? " rail" : ""}" id="app">
        <aside class="side">
          <div class="brand">
            <div class="mark">${svg('<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v9h14v-9"/><path d="M12 19v-5a2 2 0 0 1 4 0v5"/>', 19)}</div>
            <div><div class="name">HESTIA</div><div class="sub">Konfiguration</div></div>
          </div>
          <nav class="nav">
            <div class="group-label">Sichtbarkeit &amp; Sprache</div>
            <a class="nav-link${this._view === "exposure" ? " active" : ""}" data-view="exposure">${svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>', 17)}<span class="lbl">Exposure</span><span class="tag" id="navcount"></span></a>
            <a class="soon">${svg('<path d="M4 7h11"/><path d="M19 7h1"/><circle cx="17" cy="7" r="2"/><path d="M4 17h1"/><path d="M9 17h11"/><circle cx="7" cy="17" r="2"/>', 17)}<span class="lbl">Limits &amp; Mapping</span><span class="tag">im Detail</span></a>
            <a class="nav-link${this._view === "helpers" ? " active" : ""}" data-view="helpers">${svg('<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>', 17)}<span class="lbl">Helfer</span><span class="tag" id="navhcount"></span></a>
            <div class="group-label">Verhalten</div>
            <a class="soon">${svg('<path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M16 9a4 4 0 0 1 0 6"/>', 17)}<span class="lbl">Medien</span><span class="tag">im Detail</span></a>
            <a class="nav-link${this._view === "sentences" ? " active" : ""}" data-view="sentences">${svg('<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/>', 17)}<span class="lbl">Custom-Sätze</span><span class="tag" id="navscount"></span></a>
            <a class="nav-link${this._view === "settings" ? " active" : ""}" data-view="settings">${svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8M4.6 9a1.6 1.6 0 0 0-.3-1.8"/>', 17)}<span class="lbl">Allgemein &amp; Safemode</span></a>
          </nav>
          <div class="side-foot">
            <span class="dot"></span>
            <div class="foot-txt">Modell verbunden<div class="url">${esc(url) || "llama.cpp"}</div></div>
            <button class="rail-toggle" id="railBtn" title="Menü ein-/ausklappen">${svg('<path d="m15 6-6 6 6 6"/>', 24)}</button>
          </div>
        </aside>
        <div class="main" id="main"></div>
      </div>
      <div class="scrim detail" id="scrimDetail"></div>
      <div class="scrim" id="scrimAdd"></div>
      <div class="modal" id="addModal"></div>
      <div class="scrim" id="scrimHelper"></div>
      <div class="modal" id="helperModal"></div>
      <div class="scrim" id="scrimSentence"></div>
      <div class="modal" id="sentenceModal"></div>
    `;
    this._main = this._root.querySelector("#main");
    this._root.querySelector("#railBtn").addEventListener("click", () => {
      this._rail = !this._rail;
      this._root.querySelector("#app").classList.toggle("rail", this._rail);
    });
    this._root.querySelectorAll(".nav-link").forEach((a) =>
      a.addEventListener("click", () => this._switchView(a.dataset.view)));
    this._root.querySelector("#scrimDetail").addEventListener("click", () => this._closeSheet());
    this._root.querySelector("#scrimAdd").addEventListener("click", () => this._closeAdd());
    this._root.querySelector("#scrimHelper").addEventListener("click", () => this._closeHelperCreate());
    this._root.querySelector("#scrimSentence").addEventListener("click", () => this._closeSentenceCreate());
    this.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { this._closeSheet(); this._closeAdd(); this._closeHelperCreate(); this._closeSentenceCreate(); }
    });
    this._renderView();
  }

  // ── View-Routing (Topbar + Content je View) ──
  _switchView(v) {
    if (v === this._view) return;
    this._view = v;
    this._root.querySelectorAll(".nav-link").forEach((a) =>
      a.classList.toggle("active", a.dataset.view === v));
    this._renderView();
    if (v === "helpers") { if (!this._helpers) this._loadHelpers(); else this._renderHelpers(); }
    else if (v === "settings") { if (!this._settings) this._loadSettings(); else this._renderSettings(); }
    else if (v === "sentences") { if (!this._sentences) this._loadSentences(); else this._renderSentences(); }
    else { if (!this._rows) this._loadRows(); else this._renderExposure(); }
  }

  _renderView() {
    if (this._view === "settings") {
      this._main.innerHTML = `
        <header class="topbar">
          <div class="titlewrap">
            <div class="eyebrow">Verhalten</div>
            <h1>Allgemein &amp; Safemode</h1>
            <p>Wohin Hestia spricht (llama.cpp-Endpunkt), wie oft der Loop nachfassen darf — und das <b>Sicherheits-Gate</b> für Schlösser &amp; Alarm. Änderungen greifen sofort, ohne Neustart.</p>
          </div>
        </header>
        <div class="content single" id="content"></div>`;
    } else if (this._view === "sentences") {
      this._main.innerHTML = `
        <header class="topbar">
          <div class="titlewrap">
            <div class="eyebrow">Verhalten</div>
            <h1>Custom-Sätze</h1>
            <p>Feste Sätze, die <b>direkt</b> eine Aktion auslösen — <b>ohne</b> das Modell. Mehrere Formulierungen pro Aktion, jede feuert eine Ziel-Entität (Szene · Skript · Schalter · Licht …) ein/aus/um. Greift <b>vor</b> Hestia; nur bei fast wortgleichem Treffer, damit normale Anfragen frei bleiben.</p>
          </div>
          <div class="actions">
            <button class="btn primary" id="createSentenceBtn">${svg('<path d="M12 5v14M5 12h14"/>', 24)}<span>Satz anlegen</span></button>
          </div>
        </header>
        <div class="content single" id="content"></div>`;
      this._main.querySelector("#createSentenceBtn").addEventListener("click", () => this._openSentenceCreate());
    } else if (this._view === "helpers") {
      this._main.innerHTML = `
        <header class="topbar">
          <div class="titlewrap">
            <div class="eyebrow">Sichtbarkeit &amp; Sprache</div>
            <h1>Helfer</h1>
            <p>Mehrere Sensoren zu <b>einem</b> zusammenfassen, den Hestia wie einen normalen Sensor liest — <b>native HA-Helfer</b>, das Modell rechnet nichts. Numerisch (Ø·min·max über Werte) oder binär (ODER·UND über Kontakte). Beim Anlegen direkt aktiv &amp; sichtbar.</p>
          </div>
          <div class="actions">
            <button class="btn primary" id="createHelperBtn">${svg('<path d="M12 5v14M5 12h14"/>', 24)}<span>Helfer anlegen</span></button>
          </div>
        </header>
        <div class="content single" id="content"></div>`;
      this._main.querySelector("#createHelperBtn").addEventListener("click", () => this._openHelperCreate());
    } else {
      this._main.innerHTML = `
        <header class="topbar">
          <div class="titlewrap">
            <div class="eyebrow">Sichtbarkeit &amp; Sprache</div>
            <h1>Exposure</h1>
            <p>Welche Geräte Hestia kennt — und unter welchem Namen. Du fügst jedes Gerät <b>bewusst hinzu</b>; <b>Deaktivieren</b> behält die Einrichtung, blendet es aber beim Modell aus. Kein Auto-Import, kein Abgleich der dir etwas wegnimmt.</p>
          </div>
          <div class="actions">
            <button class="btn primary" id="addBtn">${svg('<path d="M12 5v14M5 12h14"/>', 24)}<span>Gerät hinzufügen</span></button>
          </div>
        </header>
        <div class="content" id="content"></div>`;
      this._main.querySelector("#addBtn").addEventListener("click", () => this._openAdd());
    }
    this._content = this._main.querySelector("#content");
  }

  // Dispatcher — Exposure-Callsites rufen weiter _renderMain(); View entscheidet.
  _renderMain() {
    if (this._view === "helpers") this._renderHelpers();
    else if (this._view === "settings") this._renderSettings();
    else if (this._view === "sentences") this._renderSentences();
    else this._renderExposure();
  }

  // ── Hauptbereich Exposure (Liste + Detail) ──
  _renderExposure() {
    if (!this._content || this._view !== "exposure") return;
    if (this._loading) {
      this._content.innerHTML = `<div class="col"><div class="loading">Lade Exposure …</div></div><aside class="col detail empty"></aside>`;
      return;
    }
    const rows = this._rows || [];
    const nav = this._root.querySelector("#navcount");
    if (nav) nav.textContent = rows.length ? String(rows.length) : "";

    const active = rows.filter((r) => r.active);
    const inactive = rows.filter((r) => !r.active);
    const offline = active.filter((r) => !r.available);
    const areas = new Set(rows.map((r) => r.area || "—"));

    const q = this._search.trim().toLowerCase();
    const matchQ = (r) => !q || r.llm_name.toLowerCase().includes(q) ||
      r.entity_id.toLowerCase().includes(q) || (r.aliases || []).some((a) => a.toLowerCase().includes(q));
    const matchF = (r) => this._filter === "all" ? true
      : this._filter === "active" ? r.active
      : this._filter === "inactive" ? !r.active
      : r.domain === this._filter;
    const shown = rows.filter((r) => matchQ(r) && matchF(r));

    const domains = [...new Set(rows.map((r) => r.domain))].sort();
    const chip = (key, label) =>
      `<button class="chip-btn${this._filter === key ? " on" : ""}" data-filter="${esc(key)}">${esc(label)}</button>`;

    // Nach (floor, area) gruppieren, kanonisch sortiert (floor-los zuletzt).
    const groups = {};
    for (const r of shown) {
      const k = `${r.floor || "￿"} ${r.area || ""}`;
      (groups[k] = groups[k] || []).push(r);
    }
    const keys = Object.keys(groups).sort();

    const listHtml = !rows.length
      ? `<div class="empty-state">${svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>', 34)}
           <b>Noch keine Geräte hinzugefügt.</b>Klick oben auf „Gerät hinzufügen", um Hestia beizubringen, was sie kennt.</div>`
      : !shown.length
      ? `<div class="empty-state">${svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', 34)}<b>Keine Treffer.</b>Andere Suche oder Filter probieren.</div>`
      : keys.map((k) => {
          const ents = groups[k].sort((a, b) => a.llm_name.localeCompare(b.llm_name));
          const [floor, area] = k.split(" ");
          const floorLbl = floor === "￿" ? "" : `<span class="floor">${esc(floor)}</span>`;
          const nAct = ents.filter((e) => e.active).length;
          const nIn = ents.length - nAct;
          const count = nIn ? `${nAct} aktiv · ${nIn} deaktiviert` : `${nAct} aktiv`;
          return `<section class="area">
            <div class="area-head">${floorLbl}<h3>${esc(area || "Ohne Raum")}</h3><span class="rule"></span><span class="count">${count}</span></div>
            <div class="rows">${ents.map((r) => this._rowHtml(r)).join("")}</div>
          </section>`;
        }).join("");

    const errHtml = this._error
      ? `<div class="banner" style="border-color:var(--danger);color:var(--danger)">${svg('<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>')}<div><b>Fehler beim Laden:</b> ${esc(this._error)}</div></div>`
      : "";

    this._content.innerHTML = `
      <div class="col">
        <div class="tiles">
          <div class="tile accent"><div class="k">Aktiv — dem Modell sichtbar</div><div class="v">${active.length} <small>/ ${rows.length} hinzugefügt</small></div></div>
          <div class="tile"><div class="k">Deaktiviert</div><div class="v">${inactive.length}</div></div>
          <div class="tile ${offline.length ? "warn" : ""}"><div class="k">Nicht erreichbar</div><div class="v">${offline.length}</div></div>
          <div class="tile"><div class="k">Areas</div><div class="v">${areas.size}</div></div>
        </div>
        ${errHtml}
        <div class="banner">${svg('<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v4h1"/>')}
          <div><b>Config-Compiler:</b> Was du hier kuratierst, wird in den System-Prompt des Modells und ins Executor-Verhalten übersetzt — nicht bloß gespeichert. Rechts siehst du live, was pro Entität beim Modell ankommt.</div></div>
        <div class="toolbar">
          <div class="search">${svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', 16)}
            <input placeholder="Name, entity_id oder Alias suchen…" id="searchInp" value="${esc(this._search)}"></div>
          <div class="filters">
            ${chip("all", "Alle")}${chip("active", "Aktiv")}${chip("inactive", "Deaktiviert")}
            ${domains.map((d) => chip(d, domLabel(d))).join("")}
          </div>
        </div>
        ${listHtml}
      </div>
      ${this._detailHtml()}
    `;

    // Verdrahtung
    const si = this._content.querySelector("#searchInp");
    if (si) si.addEventListener("input", (e) => {
      this._search = e.target.value;
      const pos = e.target.selectionStart;
      this._renderMain();
      const ns = this._content.querySelector("#searchInp");
      if (ns) { ns.focus(); ns.setSelectionRange(pos, pos); }
    });
    this._content.querySelectorAll(".chip-btn").forEach((b) =>
      b.addEventListener("click", () => { this._filter = b.dataset.filter; this._renderMain(); }));
    this._content.querySelectorAll(".row").forEach((r) =>
      r.addEventListener("click", () => this._selectRow(r.dataset.eid)));
    this._wireDetail();
  }

  _rowHtml(r) {
    const aliases = (r.aliases || []).slice(0, 4).map((a) => `<span class="alias">${esc(a)}</span>`).join("");
    let pill;
    if (!r.active) pill = `<span class="pill hidden"><span class="d"></span>Deaktiviert</span>`;
    else if (!r.available) pill = `<span class="pill offline">${svg('<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>', 13)}Nicht erreichbar</span>`;
    else pill = `<span class="pill exposed"><span class="d"></span>Aktiv</span>`;
    return `<div class="row${this._selected === r.entity_id ? " sel" : ""}" data-eid="${esc(r.entity_id)}">
      <span class="dom">${domIcon(r.domain)}</span>
      <div class="namecell"><div class="nm">${esc(r.llm_name)}</div><div class="eid">${esc(r.entity_id)}</div></div>
      <div class="aliascell">${aliases}</div>
      <div class="statecell">${pill}</div></div>`;
  }

  // ── Detail-Editor ──
  _detailHtml() {
    if (!this._selected || !this._draft) {
      return `<aside class="col detail empty">Wähle links eine Entität, um Name, Aliase und Beschreibung fürs Modell zu bearbeiten.</aside>`;
    }
    const r = (this._rows || []).find((x) => x.entity_id === this._selected);
    if (!r) return `<aside class="col detail empty"></aside>`;
    const d = this._draft;
    const kicker = `${r.area || "Ohne Raum"} · ${domLabel(r.domain)}`;
    const offNote = (d.active && !r.available)
      ? `<div class="offline-note">${svg('<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>')}
          <div><b>Aktuell nicht erreichbar.</b> HA meldet die Entität als <code>unavailable</code>. Wenn das gewollt ist (Gerät abgebaut), <b>deaktivieren</b> — dann ist die Warnung weg und die Einrichtung bleibt erhalten.</div></div>`
      : "";
    const aliasChips = d.aliases.map((a, i) =>
      `<span class="alias">${esc(a)} <button data-rm="${i}" aria-label="entfernen">×</button></span>`).join("");
    return `<aside class="col detail">
      <div class="detail-head">
        <button class="detail-close" id="detailClose">${svg('<path d="M18 6 6 18M6 6l12 12"/>', 16)}</button>
        <div class="kicker">${esc(kicker)}</div>
        <h2>${esc(d.llm_name || r.ha_name)}</h2>
        <div class="eid">${esc(r.entity_id)}</div>
      </div>
      <div class="detail-body">
        ${offNote}
        <div class="toggle-row">
          <div class="tl">Aktiv<small>Wird dem Modell präsentiert. Aus = <b>deaktiviert</b>: Name &amp; Aliase bleiben erhalten, aber unsichtbar fürs Modell &amp; keine Offline-Warnung.</small></div>
          <label class="switch"><input type="checkbox" id="dActive"${d.active ? " checked" : ""}><span class="track"></span><span class="knob"></span></label>
        </div>
        <div class="field">
          <label>Name fürs Modell <span class="hint">— so spricht Hestia darüber</span></label>
          <input class="inp" id="dName" value="${esc(d.llm_name)}" placeholder="${esc(r.ha_name)}">
        </div>
        <div class="field">
          <label>Aliase <span class="hint">— zusätzliche Auflösungswege</span></label>
          <div class="alias-edit" id="dAliases">${aliasChips}<input class="add-inp" id="aliasInp" placeholder="+ Alias"></div>
        </div>
        <div class="field">
          <label>Beschreibung <span class="hint">— optionaler Kontext</span></label>
          <textarea class="ta" id="dDesc" placeholder="z. B. „Ambientelicht" meint die Stehlampe, nicht diese.">${esc(d.description)}</textarea>
        </div>
        ${this._limitsHtml(r, d)}
        ${this._mediaHtml(r, d)}
        <div class="compiler">
          <div class="ch">${svg('<path d="m7 8-4 4 4 4M17 8l4 4-4 4M14 4l-4 16"/>')}So kommt es beim Modell an</div>
          <pre>${this._compilerHtml(r, d)}</pre>
        </div>
        <div class="backup-note">${svg('<path d="M21 8v13H3V8"/><path d="M1 3h22v5H1zM10 12h4"/>')}Wird mit dem normalen HA-Backup gesichert.</div>
        <div class="save-bar">
          <button class="btn" id="dReset">Zurücksetzen</button>
          <button class="btn primary" id="dSave">Speichern</button>
        </div>
        <button class="remove-link" id="dRemove">Aus Hestia entfernen</button>
      </div>
    </aside>`;
  }

  // ── Limits & Mapping (nur pct-steuerbare Domains) ──
  _limitsHtml(r, d) {
    const label = PCT_ATTR[r.domain];
    if (!label) return "";                       // Sensor/Schloss/Klima etc.: keine pct-Range
    const lo = d.limit_min, hi = d.limit_max;
    const st = rangeState(lo, hi);
    let preview;
    if (st === "identity")
      preview = `Kein Mapping — das Gerät nutzt den vollen 0–100&nbsp;%-Bereich.`;
    else if (st === "invalid")
      preview = `Untergrenze muss unter der Obergrenze liegen.`;
    else {
      const ex = (v) => `Modell <b>${v}</b> → Gerät <b>${mapReal(v, lo, hi)}%</b>`;
      preview = `${ex(0)}  ·  ${ex(50)}  ·  ${ex(100)}`;
    }
    return `<div class="field limits">
      <label>${label}-Bereich <span class="hint">— echte Gerätegrenzen</span></label>
      <div class="rng-lead">Das Modell bleibt bei 0–100&nbsp;%; der Executor mappt auf diese Range und meldet den <b>angeforderten</b> Wert zurück. Fürs Modell unsichtbar (kein Retraining).</div>
      <div class="rng-row">
        <div class="rng-inp"><span>ab</span><input type="number" min="0" max="100" step="1" id="dLimMin" value="${lo}"><span>%</span></div>
        <span class="rng-arrow">–</span>
        <div class="rng-inp"><span>bis</span><input type="number" min="0" max="100" step="1" id="dLimMax" value="${hi}"><span>%</span></div>
      </div>
      <div class="rng-preview ${st}" id="limPreview">${preview}</div>
    </div>`;
  }

  // ── Medien-Eligibility (nur media_player) ──
  _mediaHtml(r, d) {
    if (r.domain !== "media_player") return "";   // Flag ist nur für media_player relevant
    return `<div class="toggle-row">
      <div class="tl">Im Live-Kontext<small>Läuft dieser Player, sieht das Modell „Läuft gerade …". Aus = bewusst ausgeschlossen (z.&nbsp;B. Schlafzimmer-TV) — bleibt aber steuerbar.</small></div>
      <label class="switch"><input type="checkbox" id="dMediaCtx"${d.media_context ? " checked" : ""}><span class="track"></span><span class="knob"></span></label>
    </div>`;
  }

  _compilerHtml(r, d) {
    const name = d.llm_name || r.ha_name;
    let out = `<b>${esc(name)}</b> (${esc(r.area || "Ohne Raum")}, ${esc(domLabel(r.domain))})`;
    if (d.aliases.length) out += `\n  auch: ${esc(d.aliases.join(", "))}`;
    if (d.description.trim()) out += `\n  ${esc(d.description.trim())}`;
    if (!d.active) out += `\n  (deaktiviert — dem Modell aktuell nicht präsentiert)`;
    return out;
  }

  _wireDetail() {
    const q = (id) => this._content.querySelector("#" + id);
    const close = q("detailClose");
    if (close) close.addEventListener("click", () => this._closeSheet());
    const act = q("dActive");
    if (act) act.addEventListener("change", (e) => { this._draft.active = e.target.checked; this._refreshCompiler(); });
    const nm = q("dName");
    if (nm) nm.addEventListener("input", (e) => { this._draft.llm_name = e.target.value; this._refreshCompiler(); });
    const desc = q("dDesc");
    if (desc) desc.addEventListener("input", (e) => { this._draft.description = e.target.value; this._refreshCompiler(); });
    const clampPct = (v) => Math.max(0, Math.min(100, Math.round(Number(v) || 0)));
    const lmin = q("dLimMin");
    if (lmin) lmin.addEventListener("input", (e) => { this._draft.limit_min = clampPct(e.target.value); this._refreshLimitPreview(); });
    const lmax = q("dLimMax");
    if (lmax) lmax.addEventListener("input", (e) => { this._draft.limit_max = clampPct(e.target.value); this._refreshLimitPreview(); });
    const mctx = q("dMediaCtx");
    if (mctx) mctx.addEventListener("change", (e) => { this._draft.media_context = e.target.checked; });
    const ai = q("aliasInp");
    if (ai) ai.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.value.trim()) {
        this._draft.aliases.push(e.target.value.trim()); e.target.value = ""; this._rerenderDetail(true);
      } else if (e.key === "Backspace" && !e.target.value && this._draft.aliases.length) {
        this._draft.aliases.pop(); this._rerenderDetail(true);
      }
    });
    this._content.querySelectorAll("#dAliases [data-rm]").forEach((b) =>
      b.addEventListener("click", () => { this._draft.aliases.splice(+b.dataset.rm, 1); this._rerenderDetail(); }));
    const save = q("dSave");
    if (save) save.addEventListener("click", () => this._save());
    const reset = q("dReset");
    if (reset) reset.addEventListener("click", () => { this._selectRow(this._selected, true); });
    const rm = q("dRemove");
    if (rm) rm.addEventListener("click", () => this._remove());
  }

  _refreshCompiler() {
    const r = (this._rows || []).find((x) => x.entity_id === this._selected);
    const pre = this._content.querySelector(".compiler pre");
    if (r && pre) pre.innerHTML = this._compilerHtml(r, this._draft);
    const off = this._content.querySelector(".offline-note");   // Toggle beeinflusst Offline-Hinweis
    if (off && (this._draft.active && !r.available) === false) off.remove();
  }

  _refreshLimitPreview() {
    const el = this._content.querySelector("#limPreview");
    if (!el) return;
    const { limit_min: lo, limit_max: hi } = this._draft;
    const st = rangeState(lo, hi);
    el.className = "rng-preview " + st;
    if (st === "identity") el.innerHTML = "Kein Mapping — das Gerät nutzt den vollen 0–100&nbsp;%-Bereich.";
    else if (st === "invalid") el.innerHTML = "Untergrenze muss unter der Obergrenze liegen.";
    else {
      const ex = (v) => `Modell <b>${v}</b> → Gerät <b>${mapReal(v, lo, hi)}%</b>`;
      el.innerHTML = `${ex(0)}  ·  ${ex(50)}  ·  ${ex(100)}`;
    }
  }

  _rerenderDetail(focusAlias) {
    // Nur die Detail-Spalte neu bauen (Liste unangetastet), dann optional Alias-Input fokussieren.
    const holder = this._content.querySelector(".col.detail");
    if (!holder) return;
    holder.outerHTML = this._detailHtml();
    this._wireDetail();
    if (focusAlias) { const ai = this._content.querySelector("#aliasInp"); if (ai) ai.focus(); }
  }

  _selectRow(eid, keepSheet) {
    const r = (this._rows || []).find((x) => x.entity_id === eid);
    if (!r) return;
    this._selected = eid;
    this._draft = {
      // Feld zeigt den EFFEKTIVEN Namen (default = HA-friendly). Beim Save auf leer normalisiert,
      // wenn == ha_name → house_builder trackt dann live den friendly_name.
      llm_name: r.llm_name || "",
      aliases: [...(r.aliases || [])],
      description: r.description || "",
      active: r.active,
      limit_min: r.limit_min ?? 0,
      limit_max: r.limit_max ?? 100,
      media_context: r.media_context ?? true,
    };
    this._renderMain();
    if (this._isNarrow() && !keepSheet) this.classList.add("detail-open");
  }

  async _save() {
    const eid = this._selected, d = this._draft;
    // llm_name == HA-Name → leer speichern (Live-Tracking von friendly_name).
    const r = (this._rows || []).find((x) => x.entity_id === eid);
    const nameOut = (d.llm_name.trim() && d.llm_name.trim() !== r.ha_name) ? d.llm_name.trim() : "";
    const btn = this._content.querySelector("#dSave");
    if (btn) { btn.disabled = true; btn.textContent = "Speichern …"; }
    const patch = { active: d.active, llm_name: nameOut, aliases: d.aliases, description: d.description.trim() };
    if (PCT_ATTR[r.domain]) {                     // Limit-Range nur für pct-steuerbare Domains persistieren
      patch.limit_min = d.limit_min;
      patch.limit_max = d.limit_max;
    }
    if (r.domain === "media_player") patch.media_context = d.media_context;   // Live-Kontext-Flag
    try {
      const updated = await this._hass.callWS({
        type: "hestia/exposure/set", entity_id: eid, patch,
      });
      const idx = this._rows.findIndex((x) => x.entity_id === eid);
      if (idx >= 0) this._rows[idx] = updated;
      this._renderMain();
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = "Speichern"; }
      alert("Speichern fehlgeschlagen: " + ((e && e.message) || e));
    }
  }

  async _remove() {
    const eid = this._selected;
    if (!confirm("Diese Entität aus Hestia entfernen? Name & Aliase gehen verloren (nicht bloß deaktivieren).")) return;
    try {
      await this._hass.callWS({ type: "hestia/exposure/set", entity_id: eid, patch: { added: false } });
      this._rows = this._rows.filter((x) => x.entity_id !== eid);
      this._selected = null; this._draft = null;
      this.classList.remove("detail-open");
      this._renderMain();
    } catch (e) {
      alert("Entfernen fehlgeschlagen: " + ((e && e.message) || e));
    }
  }

  _closeSheet() { this.classList.remove("detail-open"); }
  _isNarrow() { return this.offsetWidth <= 1040; }

  // ── Add-Dialog ──
  async _openAdd() {
    this._addOpen = true; this._candSearch = "";
    this._root.querySelector("#scrimAdd").classList.add("on");
    const modal = this._root.querySelector("#addModal");
    modal.classList.add("on");
    modal.innerHTML = `<div class="loading">Lade Kandidaten …</div>`;
    try {
      const res = await this._hass.callWS({ type: "hestia/exposure/candidates" });
      this._candidates = res.entities || [];
    } catch (e) {
      this._candidates = [];
      modal.innerHTML = `<div class="loading">Fehler: ${esc((e && e.message) || e)}</div>`;
      return;
    }
    this._renderAdd();
  }

  _renderAdd() {
    const modal = this._root.querySelector("#addModal");
    const q = this._candSearch.trim().toLowerCase();
    const list = (this._candidates || []).filter((c) =>
      !q || c.ha_name.toLowerCase().includes(q) || c.entity_id.toLowerCase().includes(q));
    list.sort((a, b) => (a.area || "￿").localeCompare(b.area || "￿") || a.ha_name.localeCompare(b.ha_name));
    const items = list.length
      ? list.map((c) => `<div class="cand" data-eid="${esc(c.entity_id)}">
          <span class="dom">${domIcon(c.domain)}</span>
          <div><div class="nm">${esc(c.ha_name)}</div><div class="eid">${esc(c.entity_id)}</div></div>
          <div style="display:flex;align-items:center">
            <span class="area-tag">${esc(c.area || "—")}</span>
            <button class="btn primary add-btn" data-add="${esc(c.entity_id)}">${svg('<path d="M12 5v14M5 12h14"/>', 15)}Hinzufügen</button>
          </div></div>`).join("")
      : `<div class="empty-state" style="padding:34px">${q ? "Keine Treffer." : "Alle adressierbaren Entitäten sind schon hinzugefügt."}</div>`;
    modal.innerHTML = `
      <div class="modal-head"><h2>Gerät hinzufügen</h2>
        <button class="btn" id="addClose">${svg('<path d="M18 6 6 18M6 6l12 12"/>', 15)}Schließen</button></div>
      <div class="search">${svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', 16)}
        <input placeholder="Suchen…" id="candSearch" value="${esc(this._candSearch)}"></div>
      <div class="modal-list">${items}</div>`;
    modal.querySelector("#addClose").addEventListener("click", () => this._closeAdd());
    const cs = modal.querySelector("#candSearch");
    cs.addEventListener("input", (e) => {
      this._candSearch = e.target.value; const pos = e.target.selectionStart;
      this._renderAdd();
      const ns = modal.querySelector("#candSearch"); if (ns) { ns.focus(); ns.setSelectionRange(pos, pos); }
    });
    modal.querySelectorAll("[data-add]").forEach((b) =>
      b.addEventListener("click", () => this._addEntity(b.dataset.add)));
  }

  async _addEntity(eid) {
    try {
      const rec = await this._hass.callWS({ type: "hestia/exposure/set", entity_id: eid, patch: { added: true } });
      (this._rows = this._rows || []).push(rec);
      this._candidates = (this._candidates || []).filter((c) => c.entity_id !== eid);
      this._renderMain();
      this._renderAdd();
    } catch (e) {
      alert("Hinzufügen fehlgeschlagen: " + ((e && e.message) || e));
    }
  }

  _closeAdd() {
    this._addOpen = false;
    this._root.querySelector("#scrimAdd").classList.remove("on");
    this._root.querySelector("#addModal").classList.remove("on");
  }

  // ══════════════════ Helfer-View ══════════════════
  // ── Allgemein & Safemode (Config-Entry-Settings via hestia/settings/*) ──
  _unsafeBanner() {
    const warn = '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>';
    return `<div class="banner" style="border-color:var(--danger);color:var(--danger)">${svg(warn)}<div><b>Safemode aus:</b> Hestia kann Türschlösser und die Alarmanlage schalten. Nur so lassen, wenn du das wirklich willst.</div></div>`;
  }

  async _loadSettings() {
    this._error = null; this._settings = null; this._renderSettings();
    try {
      this._settings = await this._hass.callWS({ type: "hestia/settings/get" });
    } catch (e) {
      this._error = (e && e.message) || String(e);
      this._settings = { llama_url: "", loop_depth: 3, unsafe_mode: false };
    }
    this._sDraft = { ...this._settings };
    this._renderSettings();
  }

  _renderSettings() {
    if (!this._content || this._view !== "settings") return;
    if (!this._settings || !this._sDraft) {
      this._content.innerHTML = `<div class="col"><div class="loading">Lade Einstellungen …</div></div>`; return;
    }
    const s = this._sDraft;
    const errHtml = this._error
      ? `<div class="banner" style="border-color:var(--danger);color:var(--danger)">${svg('<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>')}<div><b>Fehler:</b> ${esc(this._error)}</div></div>`
      : "";
    this._content.innerHTML = `
      <div class="col" style="max-width:640px">
        ${errHtml}
        <div class="field">
          <label>llama.cpp-Endpunkt <span class="hint">— /completion-Basis-URL</span></label>
          <input class="inp" id="sUrl" value="${esc(s.llama_url)}" placeholder="http://10.83.1.111:8099">
        </div>
        <div class="field">
          <label>Loop-Tiefe <span class="hint">— max. Tool-Runden pro Anfrage (1–8)</span></label>
          <input class="inp" type="number" min="1" max="8" step="1" id="sDepth" value="${Number(s.loop_depth) || 3}" style="max-width:140px">
        </div>
        <div class="toggle-row">
          <div class="tl">Schlösser &amp; Alarm steuern<small>Aus (empfohlen) = Hestia <b>blockt</b> Schloss-/Alarm-Befehle und antwortet „aus Sicherheitsgründen nicht". An = Steuerung erlaubt — bewusst, auf eigenes Risiko.</small></div>
          <label class="switch"><input type="checkbox" id="sUnsafe"${s.unsafe_mode ? " checked" : ""}><span class="track"></span><span class="knob"></span></label>
        </div>
        <div id="unsafeWarn">${s.unsafe_mode ? this._unsafeBanner() : ""}</div>
        <div class="backup-note">${svg('<path d="M21 8v13H3V8"/><path d="M1 3h22v5H1zM10 12h4"/>')}Wird mit dem normalen HA-Backup gesichert.</div>
        <div class="save-bar">
          <button class="btn" id="sReset">Zurücksetzen</button>
          <button class="btn primary" id="sSave">Speichern</button>
        </div>
      </div>`;
    this._wireSettings();
  }

  _wireSettings() {
    const q = (id) => this._content.querySelector("#" + id);
    const url = q("sUrl");
    if (url) url.addEventListener("input", (e) => { this._sDraft.llama_url = e.target.value; });
    const depth = q("sDepth");
    if (depth) depth.addEventListener("input", (e) => {
      this._sDraft.loop_depth = Math.max(1, Math.min(8, Math.round(Number(e.target.value) || 3)));
    });
    const uns = q("sUnsafe");
    if (uns) uns.addEventListener("change", (e) => {
      this._sDraft.unsafe_mode = e.target.checked;
      const w = q("unsafeWarn");
      if (w) w.innerHTML = e.target.checked ? this._unsafeBanner() : "";
    });
    const save = q("sSave");
    if (save) save.addEventListener("click", () => this._saveSettings());
    const reset = q("sReset");
    if (reset) reset.addEventListener("click", () => { this._sDraft = { ...this._settings }; this._renderSettings(); });
  }

  async _saveSettings() {
    const d = this._sDraft;
    const url = (d.llama_url || "").trim();
    if (!url) { alert("Endpunkt darf nicht leer sein."); return; }
    const btn = this._content.querySelector("#sSave");
    if (btn) { btn.disabled = true; btn.textContent = "Speichern …"; }
    try {
      const updated = await this._hass.callWS({
        type: "hestia/settings/set",
        llama_url: url,
        loop_depth: Math.max(1, Math.min(8, Math.round(Number(d.loop_depth) || 3))),
        unsafe_mode: !!d.unsafe_mode,
      });
      this._settings = updated;
      this._sDraft = { ...updated };
      this._renderSettings();
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = "Speichern"; }
      alert("Speichern fehlgeschlagen: " + ((e && e.message) || e));
    }
  }

  async _loadHelpers() {
    this._loading = true; this._error = null; this._renderHelpers();
    try {
      const [h, a] = await Promise.all([
        this._hass.callWS({ type: "hestia/helper/list" }),
        this._hass.callWS({ type: "config/area_registry/list" }),
      ]);
      this._helpers = h.helpers || [];
      this._areas = a || [];
    } catch (e) {
      this._error = (e && e.message) || String(e);
      this._helpers = [];
    }
    this._loading = false;
    this._renderHelpers();
  }

  _hState(eid) {
    const s = eid && this._hass && this._hass.states[eid];
    if (!s) return { val: "—", unit: "" };
    return { val: s.state, unit: (s.attributes && s.attributes.unit_of_measurement) || "" };
  }

  _renderHelpers() {
    if (!this._content || this._view !== "helpers") return;
    const navh = this._root.querySelector("#navhcount");
    if (this._loading) { this._content.innerHTML = `<div class="col"><div class="loading">Lade Helfer …</div></div>`; return; }
    const list = this._helpers || [];
    if (navh) navh.textContent = list.length ? String(list.length) : "";

    const numeric = list.filter((h) => h.domain === "min_max");
    const binary = list.filter((h) => h.domain === "group");
    const errHtml = this._error
      ? `<div class="banner" style="border-color:var(--danger);color:var(--danger)">${svg('<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>')}<div><b>Fehler:</b> ${esc(this._error)}</div></div>`
      : "";

    const hrow = (h) => {
      const isNum = h.domain === "min_max";
      const icon = isNum ? '<path d="M12 20V8M18 20V4M6 20v-6"/>' : '<path d="m9 12 2 2 4-4"/><rect x="3" y="4" width="18" height="16" rx="3"/>';
      const st = this._hState(h.entity_id);
      return `<div class="hrow">
        <span class="dom">${svg(icon)}</span>
        <div class="namecell"><div class="nm">${esc(h.name)}</div><div class="eid">${esc(h.entity_id || "—")}</div></div>
        <div class="hval">${esc(st.val)}${st.unit ? ` <small>${esc(st.unit)}</small>` : ""}</div>
        <div class="htype">${isNum ? "Numerisch" : "Binär"}</div>
        <button class="remove-link hdel" data-del="${esc(h.entry_id)}">Löschen</button>
      </div>`;
    };
    const section = (title, hint, arr) => arr.length ? `<section class="area">
        <div class="area-head"><h3>${title}</h3><span class="floor">${hint}</span><span class="rule"></span><span class="count">${arr.length}</span></div>
        <div class="rows">${arr.map(hrow).join("")}</div></section>` : "";

    const body = !list.length
      ? `<div class="empty-state">${svg('<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>', 34)}
           <b>Noch keine Helfer.</b>Fasse mehrere Sensoren zu einem zusammen — z. B. „Arbeitszimmer-Temperatur" als Durchschnitt mehrerer Thermometer.</div>`
      : `${section("Numerisch", "Ø · min · max · Median", numeric)}${section("Binär", "ODER · UND", binary)}`;

    this._content.innerHTML = `<div class="col">
      <div class="banner">${svg('<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v4h1"/>')}
        <div><b>Native HA-Helfer:</b> angelegt über HAs eigene Helfer-Integrationen (min_max / group). Das Modell sieht einen ganz normalen Sensor — es rechnet oder rät nichts. Du siehst &amp; verwaltest sie auch direkt in Home&nbsp;Assistant.</div></div>
      ${errHtml}${body}</div>`;

    this._content.querySelectorAll(".hdel").forEach((b) =>
      b.addEventListener("click", () => this._deleteHelper(b.dataset.del)));
  }

  async _deleteHelper(entryId) {
    const h = (this._helpers || []).find((x) => x.entry_id === entryId);
    if (!confirm(`Helfer „${h ? h.name : ""}" löschen? Die zugrundeliegenden Sensoren bleiben unberührt.`)) return;
    try {
      await this._hass.callWS({ type: "hestia/helper/delete", entry_id: entryId });
      this._helpers = (this._helpers || []).filter((x) => x.entry_id !== entryId);
      this._renderHelpers();
    } catch (e) {
      alert("Löschen fehlgeschlagen: " + ((e && e.message) || e));
    }
  }

  // ── Helfer anlegen (Modal) ──
  _openHelperCreate() {
    this._hcDraft = { kind: "numeric", name: "", entities: [], agg: "mean", mode: "any", area_id: "" };
    this._hcSearch = "";
    this._root.querySelector("#scrimHelper").classList.add("on");
    this._root.querySelector("#helperModal").classList.add("on");
    this._renderHelperModal();
  }

  _closeHelperCreate() {
    this._root.querySelector("#scrimHelper").classList.remove("on");
    this._root.querySelector("#helperModal").classList.remove("on");
    this._hcDraft = null;
  }

  // Quell-Kandidaten je Sorte aus hass.states (numeric: sensor/number/input_number; binary: binary_sensor).
  _hcSources() {
    const doms = this._hcDraft.kind === "numeric" ? ["sensor", "number", "input_number"] : ["binary_sensor"];
    const q = this._hcSearch.trim().toLowerCase();
    const out = [];
    for (const eid in (this._hass.states || {})) {
      const dom = eid.split(".")[0];
      if (!doms.includes(dom)) continue;
      const s = this._hass.states[eid];
      const nm = (s.attributes && s.attributes.friendly_name) || eid;
      if (q && !nm.toLowerCase().includes(q) && !eid.toLowerCase().includes(q)) continue;
      out.push({ eid, nm, unit: (s.attributes && s.attributes.unit_of_measurement) || "" });
    }
    out.sort((a, b) => a.nm.localeCompare(b.nm));
    return out;
  }

  _renderHelperModal() {
    const modal = this._root.querySelector("#helperModal");
    const d = this._hcDraft;
    const isNum = d.kind === "numeric";
    const seg = (key, cur, opts) => `<div class="seg">${opts.map(([k, l]) =>
      `<button class="seg-b${cur === k ? " on" : ""}" data-${key}="${k}">${l}</button>`).join("")}</div>`;
    const src = this._hcSources();
    const checklist = src.length ? src.map((c) => {
      const on = d.entities.includes(c.eid);
      return `<label class="chk${on ? " on" : ""}"><input type="checkbox" data-ent="${esc(c.eid)}"${on ? " checked" : ""}>
        <span class="chk-nm">${esc(c.nm)}</span><span class="chk-eid">${esc(c.eid)}</span></label>`;
    }).join("") : `<div class="empty-state" style="padding:24px">Keine passenden ${isNum ? "Sensoren/Regler" : "Binärsensoren"} gefunden.</div>`;

    const areaOpts = `<option value="">— keine Area —</option>` +
      (this._areas || []).slice().sort((a, b) => a.name.localeCompare(b.name))
        .map((a) => `<option value="${esc(a.area_id)}"${d.area_id === a.area_id ? " selected" : ""}>${esc(a.name)}</option>`).join("");

    const canSave = d.name.trim() && d.entities.length;
    modal.innerHTML = `
      <div class="modal-head"><h2>Helfer anlegen</h2>
        <button class="btn" id="hcClose">${svg('<path d="M18 6 6 18M6 6l12 12"/>', 15)}Schließen</button></div>
      <div class="hc-body">
        <div class="field"><label>Art</label>
          ${seg("kind", d.kind, [["numeric", "Numerisch (Ø·min·max)"], ["binary", "Binär (ODER·UND)"]])}
          <div class="hint">${isNum ? "Fasst mehrere Zahlen-Sensoren zu einem Wert zusammen." : "Fasst mehrere Kontakte/Binärsensoren zu einem Zustand zusammen."}</div>
        </div>
        <div class="field"><label>Name</label>
          <input class="inp" id="hcName" value="${esc(d.name)}" placeholder="${isNum ? "z. B. Arbeitszimmer-Temperatur" : "z. B. Wohnzimmer-Präsenz"}"></div>
        <div class="field"><label>${isNum ? "Aggregation" : "Logik"}</label>
          ${isNum
            ? seg("agg", d.agg, [["mean", "Durchschnitt"], ["min", "Minimum"], ["max", "Maximum"], ["median", "Median"]])
            : seg("mode", d.mode, [["any", "ODER — irgendeiner an"], ["all", "UND — alle an"]])}
        </div>
        <div class="field"><label>Quell-Entitäten <span class="hint">— ${d.entities.length} gewählt</span></label>
          <div class="search hc-search">${svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', 16)}
            <input placeholder="Suchen…" id="hcSearch" value="${esc(this._hcSearch)}"></div>
          <div class="checklist">${checklist}</div>
        </div>
        <div class="field"><label>Area <span class="hint">— optional, für die Raum-Zuordnung</span></label>
          <select class="inp" id="hcArea">${areaOpts}</select></div>
      </div>
      <div class="hc-foot">
        <button class="btn primary" id="hcCreate"${canSave ? "" : " disabled"}>Anlegen &amp; hinzufügen</button>
      </div>`;

    modal.querySelector("#hcClose").addEventListener("click", () => this._closeHelperCreate());
    modal.querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => {
      d.kind = b.dataset.kind; d.entities = []; d.agg = "mean"; d.mode = "any"; this._renderHelperModal();
    }));
    modal.querySelectorAll("[data-agg]").forEach((b) => b.addEventListener("click", () => { d.agg = b.dataset.agg; this._renderHelperModal(); }));
    modal.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => { d.mode = b.dataset.mode; this._renderHelperModal(); }));
    const nm = modal.querySelector("#hcName");
    nm.addEventListener("input", (e) => { d.name = e.target.value; const c = modal.querySelector("#hcCreate"); if (c) c.disabled = !(d.name.trim() && d.entities.length); });
    const se = modal.querySelector("#hcSearch");
    se.addEventListener("input", (e) => { this._hcSearch = e.target.value; const p = e.target.selectionStart; this._renderHelperModal(); const n2 = modal.querySelector("#hcSearch"); if (n2) { n2.focus(); n2.setSelectionRange(p, p); } });
    modal.querySelectorAll("[data-ent]").forEach((cb) => cb.addEventListener("change", (e) => {
      const eid = cb.dataset.ent;
      if (e.target.checked) { if (!d.entities.includes(eid)) d.entities.push(eid); }
      else d.entities = d.entities.filter((x) => x !== eid);
      cb.closest(".chk").classList.toggle("on", e.target.checked);
      const lbl = modal.querySelector(".field label .hint"); // erste Zählung nicht kritisch
      const c = modal.querySelector("#hcCreate"); if (c) c.disabled = !(d.name.trim() && d.entities.length);
    }));
    modal.querySelector("#hcArea").addEventListener("change", (e) => { d.area_id = e.target.value; });
    modal.querySelector("#hcCreate").addEventListener("click", () => this._createHelper());
  }

  async _createHelper() {
    const d = this._hcDraft;
    if (!(d.name.trim() && d.entities.length)) return;
    const btn = this._root.querySelector("#hcCreate");
    if (btn) { btn.disabled = true; btn.textContent = "Lege an …"; }
    const payload = { type: "hestia/helper/create", kind: d.kind, name: d.name.trim(), entities: d.entities };
    if (d.kind === "numeric") payload.agg = d.agg; else payload.mode = d.mode;
    if (d.area_id) payload.area_id = d.area_id;
    try {
      const rec = await this._hass.callWS(payload);
      (this._helpers = this._helpers || []).push({ entry_id: rec.entry_id, entity_id: rec.entity_id, name: rec.name, domain: d.kind === "numeric" ? "min_max" : "group" });
      this._rows = null;   // Exposure-Liste ist jetzt veraltet (Helfer wurde exposed) → beim nächsten Besuch neu laden
      this._closeHelperCreate();
      this._renderHelpers();
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = "Anlegen & hinzufügen"; }
      alert("Anlegen fehlgeschlagen: " + ((e && e.message) || e));
    }
  }

  // ══════════════════ Custom-Sätze ══════════════════
  async _loadSentences() {
    this._error = null; this._sentences = null; this._renderSentences();
    try {
      const res = await this._hass.callWS({ type: "hestia/sentence/list" });
      this._sentences = res.sentences || [];
    } catch (e) {
      this._error = (e && e.message) || String(e);
      this._sentences = [];
    }
    this._renderSentences();
  }

  _renderSentences() {
    if (!this._content || this._view !== "sentences") return;
    const navs = this._root.querySelector("#navscount");
    if (!this._sentences) { this._content.innerHTML = `<div class="col"><div class="loading">Lade Sätze …</div></div>`; return; }
    const list = this._sentences;
    if (navs) navs.textContent = list.length ? String(list.length) : "";
    const errHtml = this._error
      ? `<div class="banner" style="border-color:var(--danger);color:var(--danger)">${svg('<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>')}<div><b>Fehler:</b> ${esc(this._error)}</div></div>`
      : "";
    const modeLbl = { on: "Einschalten", off: "Ausschalten", toggle: "Umschalten" };
    const chatIcon = '<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/>';
    const srow = (s) => {
      const chips = (s.phrases || []).map((p) => `<span class="chip ro">${esc(p)}</span>`).join("");
      const resp = s.response ? `<div style="font-family:var(--mono);font-size:11px;color:var(--ink-3);margin-top:7px">↳ „${esc(s.response)}"</div>` : "";
      return `<div class="srow">
        <span class="dom">${svg(chatIcon)}</span>
        <div class="phrases"><div class="chips">${chips}</div>${resp}</div>
        <div class="tgt">${esc(s.target_entity)}</div>
        <div class="smode">${modeLbl[s.mode] || esc(s.mode)}</div>
        <button class="remove-link sdel" data-del="${esc(s.id)}">Löschen</button>
      </div>`;
    };
    const body = !list.length
      ? `<div class="empty-state">${svg(chatIcon, 34)}<b>Noch keine Custom-Sätze.</b>Lege feste Formulierungen an, die direkt eine Szene, ein Skript oder einen Schalter auslösen — am Modell vorbei.</div>`
      : `<section class="area"><div class="rows">${list.map(srow).join("")}</div></section>`;
    this._content.innerHTML = `<div class="col">
      <div class="banner">${svg('<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v4h1"/>')}
        <div><b>Vor dem Modell:</b> matcht eine Eingabe (fast wortgleich) einen dieser Sätze, feuert Hestia die Aktion <b>direkt</b> und antwortet kurz — kein LLM, keine Verzögerung. Bei mehreren Treffern gewinnt der beste. Nur bei sehr ähnlichem Wortlaut, damit normale Anfragen frei bleiben.</div></div>
      ${errHtml}${body}</div>`;
    this._content.querySelectorAll(".sdel").forEach((b) =>
      b.addEventListener("click", () => this._deleteSentence(b.dataset.del)));
  }

  async _deleteSentence(id) {
    const s = (this._sentences || []).find((x) => x.id === id);
    const first = s && s.phrases && s.phrases[0] ? s.phrases[0] : "";
    if (!confirm(`Satz „${first}" löschen?`)) return;
    try {
      await this._hass.callWS({ type: "hestia/sentence/delete", sentence_id: id });
      this._sentences = (this._sentences || []).filter((x) => x.id !== id);
      this._renderSentences();
    } catch (e) {
      alert("Löschen fehlgeschlagen: " + ((e && e.message) || e));
    }
  }

  // ── Satz anlegen (Modal) ──
  _openSentenceCreate() {
    this._scDraft = { phrases: [], target_entity: "", mode: "on", response: "" };
    this._scSearch = "";
    this._root.querySelector("#scrimSentence").classList.add("on");
    this._root.querySelector("#sentenceModal").classList.add("on");
    this._renderSentenceModal();
  }

  _closeSentenceCreate() {
    this._root.querySelector("#scrimSentence").classList.remove("on");
    this._root.querySelector("#sentenceModal").classList.remove("on");
    this._scDraft = null;
  }

  // Ziel-Kandidaten: aktionsfähige Domains aus hass.states (Szene/Skript/Schalter/Licht/…).
  _scTargets() {
    const DOMS = ["scene", "script", "switch", "light", "fan", "input_boolean", "media_player",
      "cover", "climate", "automation", "button", "input_button", "vacuum", "humidifier", "siren",
      "lock", "alarm_control_panel"];
    const q = this._scSearch.trim().toLowerCase();
    const out = [];
    for (const eid in (this._hass.states || {})) {
      const dom = eid.split(".")[0];
      if (!DOMS.includes(dom)) continue;
      const s = this._hass.states[eid];
      const nm = (s.attributes && s.attributes.friendly_name) || eid;
      if (q && !nm.toLowerCase().includes(q) && !eid.toLowerCase().includes(q)) continue;
      out.push({ eid, nm });
    }
    out.sort((a, b) => a.nm.localeCompare(b.nm));
    return out;
  }

  _renderSentenceModal() {
    const modal = this._root.querySelector("#sentenceModal");
    const d = this._scDraft;
    const xIcon = '<path d="M18 6 6 18M6 6l12 12"/>';
    const seg = (key, cur, opts) => `<div class="seg">${opts.map(([k, l]) =>
      `<button class="seg-b${cur === k ? " on" : ""}" data-${key}="${k}">${l}</button>`).join("")}</div>`;
    const chips = d.phrases.map((p, i) =>
      `<span class="chip">${esc(p)}<button class="chip-x" data-rmphrase="${i}">${svg(xIcon, 13)}</button></span>`).join("");
    const tg = this._scTargets();
    const targetList = tg.length ? tg.map((c) => {
      const on = d.target_entity === c.eid;
      return `<label class="chk${on ? " on" : ""}"><input type="radio" name="sctarget" data-tgt="${esc(c.eid)}"${on ? " checked" : ""}>
        <span class="chk-nm">${esc(c.nm)}</span><span class="chk-eid">${esc(c.eid)}</span></label>`;
    }).join("") : `<div class="empty-state" style="padding:24px">Keine passende Ziel-Entität gefunden.</div>`;
    const canSave = d.phrases.length && d.target_entity;
    modal.innerHTML = `
      <div class="modal-head"><h2>Satz anlegen</h2>
        <button class="btn" id="scClose">${svg(xIcon, 15)}Schließen</button></div>
      <div class="hc-body">
        <div class="field"><label>Sätze <span class="hint">— Enter fügt hinzu; mehrere Formulierungen für dieselbe Aktion</span></label>
          <div class="chipwrap" id="scChips">${chips}<input id="scPhrase" placeholder="${d.phrases.length ? "" : "z. B. Kinoabend"}" autocomplete="off"></div>
        </div>
        <div class="field"><label>Ziel-Entität <span class="hint">— was gefeuert wird (Szene · Skript · Schalter · Licht …)</span></label>
          <div class="search hc-search">${svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', 16)}
            <input placeholder="Suchen…" id="scSearch" value="${esc(this._scSearch)}"></div>
          <div class="radiolist">${targetList}</div>
        </div>
        <div class="field"><label>Aktion</label>
          ${seg("mode", d.mode, [["on", "Einschalten"], ["off", "Ausschalten"], ["toggle", "Umschalten"]])}
          <div class="hint">Szenen/Skripte werden immer ausgelöst (turn_on) — Modus ist dort ohne Wirkung.</div>
        </div>
        <div class="field"><label>Antwort <span class="hint">— optional; leer → „Ok."</span></label>
          <input class="inp" id="scResp" value="${esc(d.response)}" placeholder="Ok."></div>
      </div>
      <div class="hc-foot">
        <button class="btn primary" id="scCreate"${canSave ? "" : " disabled"}>Anlegen</button>
      </div>`;

    const refreshSave = () => { const c = modal.querySelector("#scCreate"); if (c) c.disabled = !(d.phrases.length && d.target_entity); };
    modal.querySelector("#scClose").addEventListener("click", () => this._closeSentenceCreate());
    const phraseInput = modal.querySelector("#scPhrase");
    const addPhrase = () => {
      const v = phraseInput.value.trim();
      if (v && !d.phrases.includes(v)) d.phrases.push(v);
      this._renderSentenceModal();
      const n = this._root.querySelector("#scPhrase"); if (n) n.focus();
    };
    phraseInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addPhrase(); }
      else if (e.key === "Backspace" && !phraseInput.value && d.phrases.length) {
        d.phrases.pop(); this._renderSentenceModal(); const n = this._root.querySelector("#scPhrase"); if (n) n.focus();
      }
    });
    modal.querySelectorAll("[data-rmphrase]").forEach((b) => b.addEventListener("click", () => {
      d.phrases.splice(Number(b.dataset.rmphrase), 1); this._renderSentenceModal();
      const n = this._root.querySelector("#scPhrase"); if (n) n.focus();
    }));
    const se = modal.querySelector("#scSearch");
    se.addEventListener("input", (e) => {
      this._scSearch = e.target.value; const p = e.target.selectionStart; this._renderSentenceModal();
      const n2 = this._root.querySelector("#scSearch"); if (n2) { n2.focus(); n2.setSelectionRange(p, p); }
    });
    modal.querySelectorAll("[data-tgt]").forEach((r) => r.addEventListener("change", () => {
      d.target_entity = r.dataset.tgt; refreshSave();
    }));
    modal.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => { d.mode = b.dataset.mode; this._renderSentenceModal(); }));
    const resp = modal.querySelector("#scResp");
    resp.addEventListener("input", (e) => { d.response = e.target.value; });
    modal.querySelector("#scCreate").addEventListener("click", () => this._createSentence());
  }

  async _createSentence() {
    const d = this._scDraft;
    if (!(d.phrases.length && d.target_entity)) return;
    const btn = this._root.querySelector("#scCreate");
    if (btn) { btn.disabled = true; btn.textContent = "Lege an …"; }
    try {
      const rec = await this._hass.callWS({
        type: "hestia/sentence/create",
        phrases: d.phrases,
        target_entity: d.target_entity,
        mode: d.mode,
        response: (d.response || "").trim(),
      });
      (this._sentences = this._sentences || []).push(rec);
      this._closeSentenceCreate();
      this._renderSentences();
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = "Anlegen"; }
      alert("Anlegen fehlgeschlagen: " + ((e && e.message) || e));
    }
  }
}

customElements.define("hestia-panel", HestiaPanel);
