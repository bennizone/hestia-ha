"""cap-v2 rev2-Result-Shaping — DIE eine Quelle (train == serve).

Analog zu render.py/parse.py: der rev2-Tool-Result (RESULT_SCHEMA.md) wird EINMAL
gebaut. Der HA-Serve-Executor (`hestia-ha/.../executor.py`) UND der Trainings-Generator
(`ha-llm-finetune/data_gen/v23/emit_capv2_multiturn.py`) importieren dieselben Shaper/
Error-Builder/Resolver → kein train≠serve auf dem Tool-JSON (Audit 2026-07-09, B2–B8/H2–H9).

Reinheit: HA-frei, dep-frei (nur stdlib `difflib`/`typing`). Alle Funktionen sind pure über
`(Call-args, exposure, State-Reads)`. Die Naht zwischen serve und train ist der **StateProvider**:
- serve: liest echtes HA (`hass.states.get` / `dt_util.now`),
- train: liest Haus-Config + simulierten State-Store (Generator-seitig).
Service-Calls (`hass.services.async_call`) bleiben serve-seitig; sie speisen das Result NIE —
die Result-Felder kommen aus `names`, `args` und State-READS.

Kontrakt: homelab-admin/hestia/v23/RESULT_SCHEMA.md (rev2, GELOCKT 2026-07-08).
Fehler-Codes: RESULT_SCHEMA §3 (additiv-only Enum) — hier die einzige Bau-Quelle.
"""
from __future__ import annotations

import difflib
from datetime import date as _date
from typing import Protocol, runtime_checkable

from .schema import COLOR_SYNONYMS, COLOR_WORDS, SETTABLE_ATTRS

# ── Konstanten (aus executor.py gehoben — jetzt Single-Source) ────────────────
# Attribut → zuständige Domain (set_state/adjust ohne explizites domain-Filter):
# „stell die Heizung auf 20" darf NUR climate treffen, nicht TVs/Lichter/Lüfter.
ATTR_DOMAIN = {"temperature": "climate", "brightness": "light", "color": "light",
               "color_temp": "light", "volume": "media_player", "position": "cover",
               "fan_speed": "fan", "lock": "lock", "alarm": "alarm_control_panel"}

# amount-Enum → Schrittweite (pct-Verben) bzw. Grad-Delta (temperature)
STEP_PCT = {"a_little": 10, "some": 25, "a_lot": 50}
STEP_DEG = {"a_little": 0.5, "some": 1.0, "a_lot": 2.0}
KELVIN = {"warm": 2700, "cool": 6500}

# state-Werte, die als „an/aktiv" zählen (any/all-Aggregat)
ON_STATES = {"on", "open", "home", "playing", "unlocked", "heat", "cool", "auto"}


# ── StateProvider (die train/serve-Naht) ──────────────────────────────────────
@runtime_checkable
class StateProvider(Protocol):
    """Abstrahiert den State-Zugriff. serve wrappt HA, train wrappt Haus+Sim-Store."""
    def read(self, eid: str) -> dict | None:
        """{"state": <str>, "attributes": {...}} für eine Entität, oder None (unbekannt)."""
        ...

    def now(self):
        """Aktuelle lokale Zeit (datetime) — für get_state(datetime)."""
        ...


# ── kleine Helfer ──────────────────────────────────────────────────────────────
def _norm(s) -> str:
    return (s or "").strip().casefold()


def _cap3(names: list) -> list:
    return names[:3]


def _num(x):
    """Kanonische Zahl-Repräsentation: ganze Floats → int (22.0 → 22). Fixt B3-Byte-Divergenz;
    identische Konvention wie serialize._fmt_value."""
    if isinstance(x, bool):
        return x
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


def _pct(v, lo=0):
    if v == "max":
        return 100
    if v == "min":
        return lo
    return int(v)


def _step(amount, table, default_key="some"):
    if isinstance(amount, (int, float)):
        return float(amount)
    return table.get(amount, table[default_key])


def names_of(exposure: dict, eids: list) -> list:
    return [exposure[e]["llm_name"] for e in eids if e in exposure]


# ── Error-Builder (RESULT_SCHEMA §3 = einzige Quelle) ─────────────────────────
def ok(**kw) -> dict:
    return {"ok": True, **kw}


def err_entity_not_found(query, did_you_mean=None) -> dict:
    d = {"ok": False, "error": "entity_not_found", "query": query}
    if did_you_mean:
        d["did_you_mean"] = list(did_you_mean)
    return d


def err_ambiguous(candidates=None, count=None, areas=None) -> dict:
    d = {"ok": False, "error": "ambiguous"}
    if count is not None:
        d["count"] = count
    if candidates is not None:
        d["candidates"] = _cap3(list(candidates))
    if areas is not None:
        d["areas"] = _cap3(list(areas))
    return d


def err_invalid_value(param, given, allowed) -> dict:
    return {"ok": False, "error": "invalid_value", "param": param,
            "given": given, "allowed": list(allowed)}


def err_no_targets(query="") -> dict:
    return {"ok": False, "error": "no_targets", "query": query}


def err_no_data(query="") -> dict:
    return {"ok": False, "error": "no_data", "query": query}


def err_unavailable(query="") -> dict:
    return {"ok": False, "error": "unavailable", "query": query}


def err_not_controllable(query="") -> dict:
    return {"ok": False, "error": "not_controllable", "query": query}


def err_unsafe(query="") -> dict:
    return {"ok": False, "error": "unsafe", "query": query}


def err_timeout(query="") -> dict:
    return {"ok": False, "error": "timeout", "query": query}


def err_unparseable() -> dict:
    return {"ok": False, "error": "unparseable"}


# ── Resolution (ersetzt executor.resolve UND generator.resolve_targets, H7) ────
def resolve(args: dict, exposure: dict) -> tuple:
    """Ziel-Block → (entity_ids, None) ODER (None, fehler-dict).

    name → exakter/aliaser Match (fuzzy did_you_mean bei Fehlschlag); sonst area/floor/domain
    als Gruppen-Filter. Leerer Ziel-Block → no_targets (MVP; `ref` ist gestrichen)."""
    name = args.get("name")
    area, floor, domain = args.get("area"), args.get("floor"), args.get("domain")

    pool = []
    for eid, rec in exposure.items():
        if domain and rec["domain"] != domain:
            continue
        if area and _norm(rec.get("area")) != _norm(area):
            continue
        if floor and _norm(rec.get("floor")) != _norm(floor):
            continue
        pool.append((eid, rec))

    if name:
        nn = _norm(name)
        exact = [(eid, rec) for eid, rec in pool
                 if _norm(rec["llm_name"]) == nn or any(_norm(a) == nn for a in rec.get("aliases", ()))]
        if len(exact) == 1:
            return [exact[0][0]], None
        if len(exact) > 1:
            areas = sorted({r.get("area") or "" for _, r in exact if r.get("area")})
            if len(exact) > 3 and len(areas) > 1:
                return None, err_ambiguous(count=len(exact), areas=areas)
            return None, err_ambiguous(candidates=[r["llm_name"] for _, r in exact])
        # kein exakter Treffer → fuzzy-Hinweis über ALLE exponierten Namen
        allnames = [rec["llm_name"] for rec in exposure.values()]
        dym = difflib.get_close_matches(name, allnames, n=3, cutoff=0.5)
        return None, err_entity_not_found(name, did_you_mean=dym or None)

    # kein name → Gruppen-Aktion über Filter
    if not (area or floor or domain):
        return None, err_no_targets("")
    if not pool:
        return None, err_no_targets(area or floor or domain)
    return [eid for eid, _ in pool], None


# Read-only Domains ohne on/off-Semantik: dürfen NIE Ziel eines Gruppen-turn_on/off sein (H6).
_TURN_READONLY = ("sensor", "binary_sensor", "weather")


def strip_readonly_for_turn(eids: list, exposure: dict):
    """Gruppen-turn_on/off ohne Domain löst den GANZEN Raum auf → Sensoren/Wetter (read-only) raus,
    sonst erschiene ein Sensor als „eingeschaltet" (train≠serve-Wurzel H6). (eids, None) | (None, err)."""
    keep = [e for e in eids if exposure[e]["domain"] not in _TURN_READONLY]
    if not keep:
        return None, err_no_targets("")
    return keep, None


def narrow_by_attr_domain(eids: list, attr, exposure: dict):
    """set_state/adjust ohne explizites domain → auf die vom Attribut implizierte Domain einengen.
    Liefert (eids, None) oder (None, no_targets-err)."""
    dom = ATTR_DOMAIN.get(attr)
    if not dom:
        return eids, None
    narrowed = [e for e in eids if exposure[e]["domain"] == dom]
    if not narrowed:
        return None, err_no_targets(attr)
    return narrowed, None


# value_query auf Sensoren: der Wire trägt die Metrik als `attribute` (device_class), eine Area/Floor-
# Auflösung liefert aber ALLE Sensoren des Raums → auf die Metrik-tragenden Reads einengen (Raum → der
# eine passende Sensor, oder leer → no_data). GETEILT train==serve (emit read_result + executor _get_state
# rufen identisch auf). Nur bei area/floor OHNE name und nur für Sensor-Wert-Attribute — name-basierte
# Einzel-Reads (inkl. climate-temperature ohne device_class) bleiben unangetastet.
SENSOR_VALUE_ATTRS = frozenset({"temperature", "humidity", "illuminance",
                                "battery", "power", "energy", "co2"})
_ATTR_DEVICE_CLASS = {"co2": "carbon_dioxide"}   # sonst gilt attr == device_class


def narrow_area_reads(args: dict, attr, reads: list) -> list:
    """Area/Floor-value_query: reads auf die device_class des Metrik-Attributs filtern. No-op für
    name-basierte Reads oder Nicht-Sensor-Attribute."""
    if attr not in SENSOR_VALUE_ATTRS:
        return reads
    if args.get("name") or not (args.get("area") or args.get("floor")):
        return reads
    dc = _ATTR_DEVICE_CLASS.get(attr, attr)
    return [r for r in reads if (r.get("attributes") or {}).get("device_class") == dc]


# ── Wert-Normalisierung set_state (kanonisch, fixt B3/B5-pct/color_temp + invalid_value) ──
def set_value_or_error(attr, val) -> tuple:
    """(canon_value, unit, err) für set_state. canon = Result-Wert (auch HA-Service-Argument-Basis);
    err = invalid_value-dict oder None. Zentralisiert Wert-Semantik für serve UND train."""
    kind = SETTABLE_ATTRS.get(attr, {}).get("kind")
    if attr == "brightness":
        return _pct(val, lo=1), "%", None
    if attr in ("volume", "position", "fan_speed", "tilt", "humidity"):
        return _pct(val), "%", None
    if attr == "temperature":
        return _num(float(val)), "°C", None
    if attr == "value":                      # generischer Zahl-Helfer (number/input_number)
        return _num(float(val)), None, None
    if attr == "color":
        cv = COLOR_SYNONYMS.get(str(val).strip().lower(), str(val).strip().lower())
        if cv not in COLOR_WORDS:            # dt/en-Synonyme normalisiert, echt gamut-fremd → Fehler
            return None, None, err_invalid_value("color", val, list(COLOR_WORDS))
        return cv, None, None                # kanonischer Enum-Wert (Service-Arg + Result-value)
    if attr == "color_temp":
        kelvin = KELVIN.get(val, val if isinstance(val, (int, float)) else None)
        if kelvin is None:
            return None, None, err_invalid_value("color_temp", val, ["warm", "cool", "<kelvin>"])
        return _num(kelvin), "K", None
    if kind == "words":                      # hvac_mode/preset/lock/alarm/oscillate
        return val, None, None
    if kind == "str":                        # effect/option (freier Name)
        return val, None, None
    return None, None, err_not_controllable(attr)


# ── Shaper (beide call-sites) ──────────────────────────────────────────────────
def shape_turn(names: list) -> dict:
    return ok(targets=names)


# Deferred-Verben (run_routine/manage_list/control_media/control_vacuum/set_timer/announce):
# Ziel-Shaping GETEILT (train==serve). Der HA-Service-/Intent-Dispatch lebt NUR im Executor —
# hier entsteht ausschließlich das Result-JSON, das der Model lernt.
#  · set_timer/announce = ABSTRAKT (Timer/Broadcast laufen im Intent-Layer, area = Dispatch-Detail,
#    kein Geräte-Ziel im Result) → targets=[].
#  · run_routine/manage_list/control_media/control_vacuum = reales Ziel (Szene·Liste·Player·Sauger)
#    → geteilter Resolver → targets=llm_names (konsistent mit turn_on/set_state). Fehler
#    (entity_not_found/ambiguous) fließt aus demselben Resolver → truthful auf beiden Seiten.
_DEFERRED_ABSTRACT = ("set_timer", "announce")
# Deferred-Geräteverben → implizierte Ziel-Domain(s). area-Auflösung liefert SONST den ganzen Raum
# (alle Domains) → auf die semantisch passende Domain einengen (analog narrow_by_attr_domain).
_DEFERRED_DOMAIN = {
    "control_media": ("media_player",),
    "control_vacuum": ("vacuum",),
    "run_routine": ("scene", "script", "automation"),
    "manage_list": ("todo",),
}


def deferred_result(verb: str, args: dict, exposure: dict) -> tuple:
    """(result, eids) für die deferred Verben. eids = aufgelöste Ziel-Entitäten (Executor-Dispatch)
    oder None. Empirie (v22-Master): media/vacuum-Cases tragen IMMER name/area → kein bare-no_targets."""
    if verb in _DEFERRED_ABSTRACT:
        return ok(targets=[]), None
    eids, err = resolve(args, exposure)
    if err:
        return err, None
    doms = _DEFERRED_DOMAIN.get(verb)
    if doms:                                  # area/name → auf die Verb-Domain einengen
        eids = [e for e in eids if exposure[e]["domain"] in doms]
        if not eids:
            return err_no_targets(args.get("name") or args.get("area") or ""), None
    return ok(targets=names_of(exposure, eids)), eids


def shape_set_state(names: list, canon, unit) -> dict:
    out = ok(targets=names, value=canon)
    if unit:
        out["unit"] = unit
    return out


def adjust_delta(attr, amount, direction):
    """Vorzeichenbehaftetes Delta für ein relatives Verstellen (temperature/position/pct)."""
    sign = 1 if direction == "up" else -1
    table = STEP_DEG if attr == "temperature" else STEP_PCT
    return sign * _step(amount, table)


def shape_adjust(names: list, before: dict, after: dict, eids: list, unit) -> dict:
    """Relatives Verstellen → Result. Echot den RESULTIERENDEN Wert (after-Read) NUR bei
    eindeutigem Einzelziel (Gruppe → mehrdeutig, nur targets). `at_limit` = kein Effekt
    (after == before, echter Anschlag) — NICHT bei clamped (Audit B4)."""
    out = ok(targets=names)
    if len(eids) == 1:
        e = eids[0]
        val = after.get(e)
        if val is not None:
            out["value"] = _num(val)
            if unit:
                out["unit"] = unit
            if before.get(e) is not None and val == before[e]:
                out["at_limit"] = True
    return out


def read_attr(read: dict, attr) -> tuple:
    """(value, unit, effektives-attribut) für einen State-Read + gefragtes Attribut.
    `read` = {"state":..., "attributes":{...}} (StateProvider-Form)."""
    a = (read or {}).get("attributes", {})
    state = (read or {}).get("state")
    if attr in (None, "state"):
        return state, None, "state"
    if attr == "temperature":
        # climate trägt den Wert in attributes.temperature/current_temperature; ein Temperatur-
        # SENSOR trägt ihn im state (attributes = uom/device_class). Beide Formen lesen.
        v = a.get("temperature", a.get("current_temperature"))
        if v is None and state not in (None, "", "unavailable", "unknown"):
            try:
                v = float(state)
            except (TypeError, ValueError):
                v = None
        return _num(v) if isinstance(v, float) else v, a.get("unit_of_measurement", "°C"), "temperature"
    if attr == "brightness":
        b = a.get("brightness")
        return (round(b / 255 * 100) if b is not None else None), "%", "brightness"
    if attr == "position":
        return a.get("current_position"), "%", "position"
    if attr == "open":
        return (state == "open"), None, "open"
    # generischer numerischer Sensor-Read (humidity/illuminance/battery/power/…):
    # Einheit aus unit_of_measurement (H8 — nie erfinden).
    unit = a.get("unit_of_measurement")
    if unit is not None:
        try:
            v = float(state)
            return _num(v), unit, attr
        except (TypeError, ValueError):
            return state, unit, attr
    return state, None, "state"


def adj_read(read: dict, attr) -> tuple:
    """(wert, unit) des adjust-relevanten Attributs — Vorher/Nachher-Echo."""
    a = (read or {}).get("attributes", {})
    if attr == "brightness":
        b = a.get("brightness")
        return (round(b / 255 * 100) if b is not None else None), "%"
    if attr == "volume":
        v = a.get("volume_level")
        return (round(v * 100) if v is not None else None), "%"
    if attr == "temperature":
        v = a.get("temperature")
        return (_num(v) if isinstance(v, float) else v), "°C"
    if attr == "position":
        return a.get("current_position"), "%"
    return None, None


def shape_datetime(now) -> dict:
    return ok(reading={"attribute": "datetime",
                       "date": now.strftime("%Y-%m-%d"),
                       "time": now.strftime("%H:%M"),
                       "weekday": now.strftime("%A")})


# ── Weather (Bahn-2, v23.2) — geteilter Block-Builder = Single-Source ──────────
# Wetter ist ein Read-Verb (get_state attribute="weather"). Der Executor holt live
# `weather.get_forecasts`, der Generator echte InfluxDB-Folgetage → BEIDE mappen auf
# denselben normalisierten Struct und rufen denselben Builder → byte-identischer Block
# (train==serve, wie read_attr). Block sitzt im `value` eines readings-Eintrags →
# kein RESULT_SCHEMA-Bruch (readings existiert, value darf String sein).
#
# ⚠ Regel (WEATHER_CONCEPT.md): der Builder nutzt NUR Felder, die BEIDE Quellen liefern
# (condition, high, low). precipitation liefert InfluxDB NICHT → Regen QUALITATIV aus der
# Condition (nie ein mm-Wert, den das Training nicht reproduziert). Actionable Aggregate
# ("Schirm sinnvoll") stehen als GELABELTE Zeile, nicht inline pro Tag (350m band inline-
# Urteile sonst an den falschen Tag — Probe 2026-07-11).
_COND_DE = {
    "clear-night": "klar", "cloudy": "bewölkt", "fog": "neblig", "hail": "Hagel",
    "lightning": "Gewitter", "lightning-rainy": "Gewitter mit Regen",
    "partlycloudy": "wechselnd bewölkt", "pouring": "starker Regen", "rainy": "regnerisch",
    "snowy": "Schnee", "snowy-rainy": "Schneeregen", "sunny": "sonnig",
    "windy": "windig", "windy-variant": "windig", "exceptional": "extrem",
}
# Nass = Schirm/Regenschutz sinnvoll (actionable-Aggregat + faktisches Per-Tag-Wort)
_WET_RAIN = {"rainy", "pouring", "lightning-rainy", "lightning", "hail"}
_WET_SNOW = {"snowy", "snowy-rainy"}
_WD_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]   # date.weekday(): Mo=0
_REL_DE = ["Heute", "Morgen", "Übermorgen"]           # days[i] positional: 0=heute


def _cond_de(cond) -> str:
    return _COND_DE.get(cond, cond or "unbekannt")


def _wd_de(iso_date) -> str | None:
    """ISO-Datum ("2026-06-20") → deutsches Wochentags-Kürzel (locale-frei, deterministisch)."""
    if not iso_date:
        return None
    try:
        return _WD_DE[_date.fromisoformat(iso_date).weekday()]
    except (TypeError, ValueError):
        return None


def _t(x):
    """Temperatur-Anzeige: auf ganze Grad runden (Block ist Vorlese-Text, keine Präzision)."""
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return None


def _precip_word(cond) -> str:
    if cond in _WET_SNOW:
        return "Schnee"
    if cond in _WET_RAIN:
        return "Regen"
    return "trocken"


def _temp_range(lo, hi) -> str:
    """Tief–Hoch als Vorlese-Spanne. Bei negativem Tief „bis" statt en-dash — „-4–1°" kollidiert
    optisch (Minus/Strich); „-4 bis 1°" ist eindeutig. Sonst en-dash (gelockte Form „20–32°")."""
    lo_i, hi_i = _t(lo), _t(hi)
    if lo_i is not None and hi_i is not None and lo_i != hi_i:
        sep = " bis " if lo_i < 0 else "–"
        return f"{lo_i}{sep}{hi_i}°"
    if hi_i is not None:
        return f"{hi_i}°"
    if lo_i is not None:
        return f"{lo_i}°"
    return "?"


def build_weather_block(struct: dict) -> str:
    """Normalisierter Wetter-Struct → tag-geankerter Vorlese-Block (B2). Pure/deterministisch.

    struct = {"now": {"cond": str, "temp": num}?,           # optional aktueller Zustand
              "days": [{"cond": str, "high": num, "low": num, "date": "YYYY-MM-DD"?}, ...]}
    days sind POSITIONAL: [0]=heute, [1]=morgen, [2]=übermorgen (max 3 genutzt).
    Gemeinsame Felder (train UND serve): cond/high/low. Regen qualitativ aus cond."""
    lines = []
    now = struct.get("now") or {}
    if now.get("cond") is not None:
        nt = _t(now.get("temp"))
        temp = f", ~{nt}°" if nt is not None else ""
        lines.append(f"Jetzt: {_cond_de(now.get('cond'))}{temp}.")

    days = (struct.get("days") or [])[:3]
    for i, d in enumerate(days):
        rel = _REL_DE[i] if i < len(_REL_DE) else f"Tag+{i}"
        wd = _wd_de(d.get("date"))
        head = f"{rel} ({wd})" if wd else rel
        span = _temp_range(d.get("low"), d.get("high"))
        lines.append(f"{head}: {_cond_de(d.get('cond'))}, {span}, {_precip_word(d.get('cond'))}")

    # ── Aggregate (deterministisch vorgebacken, gelabelt — nicht inline) ──
    hi_days = [(i, _t(d.get("high"))) for i, d in enumerate(days) if _t(d.get("high")) is not None]
    if len(days) >= 2 and hi_days:
        wi, wh = max(hi_days, key=lambda t: t[1])
        rel = (_REL_DE[wi] if wi < len(_REL_DE) else f"Tag+{wi}").lower()
        lines.append(f"Wärmster Tag: {rel} ({wh}°).")
    wet = [(_REL_DE[i] if i < len(_REL_DE) else f"Tag+{i}").lower()
           for i, d in enumerate(days) if d.get("cond") in _WET_RAIN or d.get("cond") in _WET_SNOW]
    if wet:
        lines.append(f"Schirm sinnvoll: {', '.join(wet)}.")

    return "\n".join(lines)


def shape_weather(name: str, struct: dict) -> dict:
    """Read-Result fürs Wetter: der Block sitzt im `value` eines readings-Eintrags.
    Beide Seiten (Executor/Generator) rufen dies → identisches Result-JSON (train==serve)."""
    return ok(readings=[{"name": name, "attribute": "weather",
                         "value": build_weather_block(struct)}])


# ── Sonnenstand (v23.2) — flacher Read (datetime-Geschwister, kein cap-v2) ────
# Basic: heutiger Auf-/Untergang + is_dark (vorgebacken). Serve liest sun.sun (state=
# above/below_horizon + next_rising/next_setting), Train berechnet die Zeiten astronomisch
# (sun_times.py) — beide füllen dasselbe flache reading (train==serve auf der FORM, Werte
# dürfen divergieren wie bei Weather). is_dark ist die deterministische Vorkau-Antwort auf
# „ist es dunkel?" (Modell rechnet nicht).
def _min_hhmm(s):
    """„HH:MM"(:SS) → Minuten-nach-Mitternacht, oder None."""
    try:
        h, m = str(s).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def shape_sun(sunrise, sunset, is_dark=None) -> dict:
    """Flaches Sonnenstand-reading {attribute:"sun", sunrise, sunset[, is_dark]}. sunrise/sunset =
    lokale „HH:MM". is_dark (bool) nur wenn bekannt (Serve: sun.sun-state; Train: now vs Zeiten)."""
    r = {"attribute": "sun", "sunrise": sunrise, "sunset": sunset}
    if is_dark is not None:
        r["is_dark"] = bool(is_dark)
    return ok(reading=r)


def shape_get_state(attr, aggregate, reads: list) -> dict:
    """reads = list[{"name":str, "state":str, "attributes":{...}}] (schon aufgelöst+gelesen).
    Baut readings / aggregate (count/any/all/avg/min/max) nach RESULT_SCHEMA §2b."""
    if aggregate == "count":
        return ok(aggregate="count", value=len(reads))

    readings, numeric, on_flags = [], [], []
    for r in reads:
        val, unit, a = read_attr(r, attr)
        readings.append({"name": r["name"], "attribute": a, "value": val,
                         **({"unit": unit} if unit else {})})
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            numeric.append(val)
        on_flags.append(str(r.get("state")).lower() in ON_STATES)

    if aggregate in ("any", "all"):
        v = (any(on_flags) if aggregate == "any" else all(on_flags))
        detail = [readings[i]["name"] for i, f in enumerate(on_flags) if f != v]
        out = ok(aggregate=aggregate, value=v)
        if detail:
            out["detail"] = detail[:3]
        return out
    if aggregate in ("avg", "min", "max") and numeric:
        agg = (sum(numeric) / len(numeric) if aggregate == "avg"
               else min(numeric) if aggregate == "min" else max(numeric))
        return ok(aggregate=aggregate, value=_num(round(agg, 1)))

    if not readings:
        return err_no_data("")
    return ok(readings=readings)


# ── Exposure-Bau aus dem kanonischen Haus (train-Seite; serve baut aus HA-Registry) ──
def exposure_from_house(house) -> dict:
    """hestia_cap.House → exposure-Dict {eid: {llm_name, aliases, domain, area, floor}}.
    eids sind synthetisch/deterministisch (kein echtes HA-entity_id nötig — resolve nutzt sie
    nur als opaque Schlüssel). Serve baut ein äquivalentes Dict aus der echten HA-Registry."""
    exp = {}
    n = 0
    for area in house.areas:
        for e in area.entities:
            eid = f"e{n}"
            n += 1
            exp[eid] = {"llm_name": e.name, "aliases": list(e.aliases),
                        "domain": e.domain, "area": area.name, "floor": area.floor}
    return exp


# ── v23.4 `say`-Feld: natürlichsprachige Executor-Wahrheit im Result (train==serve) ──
# Der Executor kennt als Einziger die AUSGEFÜHRTE Wahrheit (Ziel+Aktion+Wert) und legt sie als
# fertige Phrase (`say`) ins Erfolgs-Result. Das Modell formuliert `say` um statt Entity/Aktion
# selbst zu GENERIEREN → fixt den Say-vs-Do-Gap. KANONISCH: Generator (train) UND Serve-Executor
# rufen beide `with_say` → keine Divergenz mehr (Reconcile 2026-07-13, war v23.4-Deployment-Gap).
_COLOR_DE = {
    "warm_white": "warmweiß", "cold_white": "kaltweiß", "white": "weiß", "red": "rot",
    "green": "grün", "blue": "blau", "yellow": "gelb", "orange": "orange",
    "purple": "lila", "pink": "pink", "cyan": "türkis", "violet": "lila", "magenta": "magenta",
}
_TURN_SAY = {"turn_on": "eingeschaltet", "turn_off": "ausgeschaltet", "stop": "gestoppt"}
_SET_PCT_VERB = {"brightness": "gedimmt", "position": "gefahren"}   # sonst "gestellt"
_UNIT_WORD = {"°C": "Grad", "K": "Kelvin", "%": "Prozent"}
_MEDIA_SAY = {"pause": "pausiert", "play": "gestartet", "stop": "gestoppt", "next": "übersprungen",
              "previous": "zurückgesetzt", "volume_up": "lauter gestellt", "volume_down": "leiser gestellt",
              "mute": "stummgeschaltet", "unmute": "wieder laut gestellt"}
_VACUUM_SAY = {"start": "losgeschickt", "stop": "gestoppt", "pause": "pausiert",
               "return": "zurück zur Basis geschickt", "return_to_base": "zurück zur Basis geschickt",
               "locate": "geortet", "clean_area": "losgeschickt", "clean": "losgeschickt",
               "clean_room": "losgeschickt", "clean_spot": "losgeschickt"}


def _fmt_num(v) -> str:
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def _color_de(c) -> str:
    return _COLOR_DE.get(str(c).strip().lower(), str(c))


def _say_entity(targets: list, args: dict):
    """Ziel-Phrase aus den aufgelösten Zielen (dedupt, Reihenfolge-stabil)."""
    uniq = list(dict.fromkeys(targets or []))
    if not uniq:
        return None
    return uniq[0] if len(uniq) == 1 else " und ".join(uniq)


def say_for_call(verb: str, args: dict, r: dict):
    """Deterministische Wahrheits-Phrase aus (Verb, Args, Result-Ziele/Wert). None → kein `say`
    (Fehler-Result, Read, oder Fälle ohne eindeutige Ausführungs-Wahrheit → Gold trägt sie)."""
    if not r.get("ok"):
        return None
    ent = _say_entity(r.get("targets") or [], args)
    if verb in _TURN_SAY:
        return f"{ent} {_TURN_SAY[verb]}" if ent else None
    if verb == "set_state":
        if not ent:
            return None
        attr, val, unit = args.get("attribute"), r.get("value"), r.get("unit")
        if attr == "color":
            return f"{ent} auf {_color_de(val)} gestellt"
        if attr == "lock":
            return (f"{ent} abgeschlossen" if val == "locked" else
                    f"{ent} aufgeschlossen" if val == "unlocked" else f"{ent} auf {val} gestellt")
        if attr == "open":
            return f"{ent} geöffnet" if val else f"{ent} geschlossen"
        if unit == "%":
            return f"{ent} auf {_fmt_num(val)} Prozent {_SET_PCT_VERB.get(attr, 'gestellt')}"
        if unit in ("°C", "K"):
            return f"{ent} auf {_fmt_num(val)} {_UNIT_WORD[unit]} gestellt"
        return f"{ent} auf {val} gestellt" if val is not None else None
    if verb == "adjust":
        val, unit = r.get("value"), r.get("unit")
        if not ent or r.get("at_limit"):
            return None                       # Anschlag/Gruppe → value-freie Gold-Richtungsantwort
        if unit and isinstance(val, (int, float)) and not isinstance(val, bool):
            return f"{ent} auf {_fmt_num(val)} {_UNIT_WORD.get(unit, unit)} gestellt"
        return None
    if verb == "manage_list":
        item = (args.get("item") or "").strip()
        if not item:
            return None
        lst = (r.get("targets") or [args.get("name", "")])[0]
        return (f"{item} zu {lst} hinzugefügt" if args.get("action", "add") == "add"
                else f"{item} von {lst} entfernt")
    if verb == "control_media":
        act = args.get("action")
        content = (args.get("content") or "").strip()
        if act in ("play_content", "play_media", "play") and content:
            return f"{content} auf {ent} gestartet" if ent else f"{content} gestartet"
        w = _MEDIA_SAY.get(act)
        return f"{ent} {w}" if ent and w else None
    if verb == "control_vacuum":
        w = _VACUUM_SAY.get(args.get("action"))
        return f"{ent} {w}" if ent and w else None
    if verb == "run_routine":
        return f"{ent} ausgeführt" if ent else None
    if verb == "set_timer":
        if args.get("action", "set") != "set":
            return "Timer abgebrochen"
        dur = args.get("duration")
        return f"Timer über {dur} gestellt" if dur else "Timer gestellt"
    if verb == "announce":
        return "Durchsage abgespielt"
    return None


def with_say(r: dict, verb: str, args: dict) -> dict:
    """Hängt `say` an ein Erfolgs-Result (kopiert, um geteilte Shaper-Dicts nicht zu mutieren)."""
    s = say_for_call(verb, args, r)
    if s:
        r = dict(r)
        r["say"] = s
    return r
