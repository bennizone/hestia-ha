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
            <a class="active">${svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>', 17)}<span class="lbl">Exposure</span><span class="tag" id="navcount"></span></a>
            <a class="soon">${svg('<path d="M4 7h11"/><path d="M19 7h1"/><circle cx="17" cy="7" r="2"/><path d="M4 17h1"/><path d="M9 17h11"/><circle cx="7" cy="17" r="2"/>', 17)}<span class="lbl">Limits &amp; Mapping</span><span class="tag">bald</span></a>
            <a class="soon">${svg('<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>', 17)}<span class="lbl">Helfer</span><span class="tag">bald</span></a>
            <div class="group-label">Verhalten</div>
            <a class="soon">${svg('<path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M16 9a4 4 0 0 1 0 6"/>', 17)}<span class="lbl">Medien</span><span class="tag">bald</span></a>
            <a class="soon">${svg('<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/>', 17)}<span class="lbl">Custom-Sätze</span><span class="tag">bald</span></a>
            <a class="soon">${svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8M4.6 9a1.6 1.6 0 0 0-.3-1.8"/>', 17)}<span class="lbl">Allgemein &amp; Safemode</span><span class="tag">bald</span></a>
          </nav>
          <div class="side-foot">
            <span class="dot"></span>
            <div class="foot-txt">Modell verbunden<div class="url">${esc(url) || "llama.cpp"}</div></div>
            <button class="rail-toggle" id="railBtn" title="Menü ein-/ausklappen">${svg('<path d="m15 6-6 6 6 6"/>', 24)}</button>
          </div>
        </aside>
        <div class="main">
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
          <div class="content" id="content"></div>
        </div>
      </div>
      <div class="scrim detail" id="scrimDetail"></div>
      <div class="scrim" id="scrimAdd"></div>
      <div class="modal" id="addModal"></div>
    `;
    this._content = this._root.querySelector("#content");
    this._root.querySelector("#railBtn").addEventListener("click", () => {
      this._rail = !this._rail;
      this._root.querySelector("#app").classList.toggle("rail", this._rail);
    });
    this._root.querySelector("#addBtn").addEventListener("click", () => this._openAdd());
    this._root.querySelector("#scrimDetail").addEventListener("click", () => this._closeSheet());
    this._root.querySelector("#scrimAdd").addEventListener("click", () => this._closeAdd());
    this.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { this._closeSheet(); this._closeAdd(); }
    });
  }

  // ── Hauptbereich (Liste + Detail) ──
  _renderMain() {
    if (!this._content) return;
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
    try {
      const updated = await this._hass.callWS({
        type: "hestia/exposure/set", entity_id: eid,
        patch: { active: d.active, llm_name: nameOut, aliases: d.aliases, description: d.description.trim() },
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
}

customElements.define("hestia-panel", HestiaPanel);
