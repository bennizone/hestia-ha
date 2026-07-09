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
from typing import Protocol, runtime_checkable

from .schema import COLOR_WORDS, SETTABLE_ATTRS

# ── Konstanten (aus executor.py gehoben — jetzt Single-Source) ────────────────
# Attribut → zuständige Domain (set_state/adjust ohne explizites domain-Filter):
# „stell die Heizung auf 20" darf NUR climate treffen, nicht TVs/Lichter/Lüfter.
ATTR_DOMAIN = {"temperature": "climate", "brightness": "light", "color": "light",
               "color_temp": "light", "volume": "media_player", "position": "cover",
               "fan_speed": "fan"}

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
        if val not in COLOR_WORDS:
            return None, None, err_invalid_value("color", val, list(COLOR_WORDS))
        return val, None, None
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
        v = a.get("temperature", a.get("current_temperature"))
        return _num(v) if isinstance(v, float) else v, "°C", "temperature"
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
