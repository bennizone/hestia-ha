"""Executor — Wire→Entität→hass.services + rev2-Result (RESULT_SCHEMA.md).

Der native Kern des Loops: geparste cap-v2-Calls (hestia_cap.Call) gegen HAs Registry
(via Exposure-Set) auflösen, den echten HA-Service rufen, und ein schlankes rev2-Result-JSON
bauen — mit handlungsleitenden Fehlern (did_you_mean/candidates/allowed), damit das LLM
self-correcten oder geerdet zurückfragen kann.

Resolver ist MVP (exakt/normalisiert + difflib-did_you_mean); area-gewichtetes rapidfuzz = F1.
Multi-Call (>1 Call in einem Turn) → sequenziell ausgeführt, EIN aggregiertes Result (§6.3).
"""
from __future__ import annotations

import difflib
import json
import logging

from homeassistant.core import HomeAssistant, Context

from .hestia_cap.schema import COLOR_WORDS

_LOGGER = logging.getLogger(__name__)

# Attribut → zuständige Domain (für set_state/adjust ohne explizites domain-Filter):
# „stell die Heizung im Schlafzimmer auf 20" darf NUR climate treffen, nicht TVs/Lichter/Lüfter.
_ATTR_DOMAIN = {"temperature": "climate", "brightness": "light", "color": "light",
                "color_temp": "light", "volume": "media_player", "position": "cover",
                "fan_speed": "fan"}

# amount-Enum → Schrittweite (pct-Verben) bzw. Grad-Delta (temperature)
_STEP_PCT = {"a_little": 10, "some": 25, "a_lot": 50}
_STEP_DEG = {"a_little": 0.5, "some": 1.0, "a_lot": 2.0}
_KELVIN = {"warm": 2700, "cool": 6500}


def _norm(s) -> str:
    return (s or "").strip().casefold()


def _cap3(names: list[str]) -> list[str]:
    return names[:3]


def _names_of(exposure: dict, eids: list[str]) -> list[str]:
    return [exposure[e]["llm_name"] for e in eids if e in exposure]


# ── Resolution ──────────────────────────────────────────────────────────────
def resolve(args: dict, exposure: dict) -> tuple[list[str] | None, dict | None]:
    """Ziel-Block → (entity_ids, None) ODER (None, fehler-dict).

    name → exakter/aliaser Match (fuzzy did_you_mean bei Fehlschlag); sonst area/floor/domain
    als Gruppen-Filter. ref/leerer Ziel-Block wird MVP nicht aufgelöst (no_targets)."""
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
                 if _norm(rec["llm_name"]) == nn or any(_norm(a) == nn for a in rec["aliases"])]
        if len(exact) == 1:
            return [exact[0][0]], None
        if len(exact) > 1:
            areas = sorted({r.get("area") or "" for _, r in exact if r.get("area")})
            if len(exact) > 3 and len(areas) > 1:
                return None, {"ok": False, "error": "ambiguous",
                              "count": len(exact), "areas": _cap3(areas)}
            return None, {"ok": False, "error": "ambiguous",
                          "candidates": _cap3([r["llm_name"] for _, r in exact])}
        # kein exakter Treffer → fuzzy-Hinweis über ALLE exponierten Namen
        allnames = [rec["llm_name"] for rec in exposure.values()]
        dym = difflib.get_close_matches(name, allnames, n=3, cutoff=0.5)
        err = {"ok": False, "error": "entity_not_found", "query": name}
        if dym:
            err["did_you_mean"] = dym
        return None, err

    # kein name → Gruppen-Aktion über Filter
    if not (area or floor or domain):
        return None, {"ok": False, "error": "no_targets", "query": ""}
    if not pool:
        return None, {"ok": False, "error": "no_targets", "query": area or floor or domain}
    return [eid for eid, _ in pool], None


# ── Wert-Helfer ───────────────────────────────────────────────────────────────
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


# ── Einzel-Call ausführen ─────────────────────────────────────────────────────
async def _exec_one(hass: HomeAssistant, call, exposure: dict, context: Context,
                    deny: list[str]) -> dict:
    verb, args = call.verb, call.args

    if verb == "get_state":
        return await _get_state(hass, args, exposure)

    # ab hier: mutierende / Aktions-Verben → Ziel auflösen
    eids, err = resolve(args, exposure)
    if err:
        return err

    # set_state/adjust ohne explizites domain → auf die vom Attribut implizierte Domain einengen
    if verb in ("set_state", "adjust") and "domain" not in args:
        dom = _ATTR_DOMAIN.get(args.get("attribute"))
        if dom:
            narrowed = [e for e in eids if exposure[e]["domain"] == dom]
            if not narrowed:
                return {"ok": False, "error": "no_targets", "query": args.get("attribute")}
            eids = narrowed

    # Safety-Deny (Schloss/Alarm) — kein Service-Call
    if any(exposure[e]["domain"] in deny for e in eids):
        return {"ok": False, "error": "unsafe", "query": args.get("name") or args.get("domain") or ""}

    names = _names_of(exposure, eids)
    try:
        if verb in ("turn_on", "turn_off"):
            return await _turn(hass, verb, eids, names, exposure, context)
        if verb == "stop":
            return await _stop(hass, eids, names, exposure, context)
        if verb == "set_state":
            return await _set_state(hass, eids, names, args, context)
        if verb == "adjust":
            return await _adjust(hass, eids, names, args, exposure, context)
    except Exception as e:  # noqa: BLE001 — HA-Service-Fehler → ehrliches Result, kein Crash
        _LOGGER.warning("Hestia executor %s failed: %s", verb, e)
        return {"ok": False, "error": "timeout", "query": args.get("name") or args.get("domain") or ""}

    # verbleibende Verben (run_routine/set_timer/control_media/announce/manage_list/control_vacuum)
    # sind bewusst DEFERRED (MVP) — ehrlich melden statt raten.
    return {"ok": False, "error": "not_controllable", "query": verb}


async def _turn(hass, verb, eids, names, exposure, context) -> dict:
    """turn_on/off domain-aware: Cover brauchen open_cover/close_cover (homeassistant.turn_on
    lässt Cover unberührt — im Härtetest verifiziert). Rest via generisches homeassistant.turn_*."""
    covers = [e for e in eids if exposure[e]["domain"] == "cover"]
    others = [e for e in eids if exposure[e]["domain"] != "cover"]
    if others:
        await hass.services.async_call("homeassistant", verb, {"entity_id": others},
                                       blocking=True, context=context)
    if covers:
        svc = "open_cover" if verb == "turn_on" else "close_cover"
        await hass.services.async_call("cover", svc, {"entity_id": covers},
                                       blocking=True, context=context)
    return {"ok": True, "targets": names}


async def _stop(hass, eids, names, exposure, context) -> dict:
    for eid in eids:
        dom = exposure[eid]["domain"]
        if dom == "cover":
            await hass.services.async_call("cover", "stop_cover", {"entity_id": eid},
                                           blocking=True, context=context)
        elif dom == "vacuum":
            await hass.services.async_call("vacuum", "stop", {"entity_id": eid},
                                           blocking=True, context=context)
    return {"ok": True, "targets": names}


async def _set_state(hass, eids, names, args, context) -> dict:
    attr, val = args["attribute"], args["value"]
    if attr == "brightness":
        await hass.services.async_call("light", "turn_on",
                                       {"entity_id": eids, "brightness_pct": _pct(val, lo=1)},
                                       blocking=True, context=context)
        return {"ok": True, "targets": names, "value": _pct(val, lo=1), "unit": "%"}
    if attr == "volume":
        await hass.services.async_call("media_player", "volume_set",
                                       {"entity_id": eids, "volume_level": _pct(val) / 100},
                                       blocking=True, context=context)
        return {"ok": True, "targets": names, "value": _pct(val), "unit": "%"}
    if attr == "position":
        await hass.services.async_call("cover", "set_cover_position",
                                       {"entity_id": eids, "position": _pct(val)},
                                       blocking=True, context=context)
        return {"ok": True, "targets": names, "value": _pct(val), "unit": "%"}
    if attr == "fan_speed":
        await hass.services.async_call("fan", "set_percentage",
                                       {"entity_id": eids, "percentage": _pct(val)},
                                       blocking=True, context=context)
        return {"ok": True, "targets": names, "value": _pct(val), "unit": "%"}
    if attr == "temperature":
        await hass.services.async_call("climate", "set_temperature",
                                       {"entity_id": eids, "temperature": float(val)},
                                       blocking=True, context=context)
        return {"ok": True, "targets": names, "value": float(val), "unit": "°C"}
    if attr == "color":
        if val not in COLOR_WORDS:
            return {"ok": False, "error": "invalid_value", "param": "color",
                    "given": val, "allowed": list(COLOR_WORDS)}
        await hass.services.async_call("light", "turn_on",
                                       {"entity_id": eids, "color_name": val.replace("_", "")},
                                       blocking=True, context=context)
        return {"ok": True, "targets": names, "value": val}
    if attr == "color_temp":
        kelvin = _KELVIN.get(val, val if isinstance(val, (int, float)) else None)
        if kelvin is None:
            return {"ok": False, "error": "invalid_value", "param": "color_temp",
                    "given": val, "allowed": ["warm", "cool", "<kelvin>"]}
        await hass.services.async_call("light", "turn_on",
                                       {"entity_id": eids, "color_temp_kelvin": int(kelvin)},
                                       blocking=True, context=context)
        return {"ok": True, "targets": names, "value": int(kelvin), "unit": "K"}
    return {"ok": False, "error": "not_controllable", "query": attr}


def _adj_read(st, attr):
    """(wert, unit) des adjust-relevanten Attributs — für Vorher/Nachher-Echo."""
    a = st.attributes
    if attr == "brightness":
        b = a.get("brightness")
        return (round(b / 255 * 100) if b is not None else None, "%")
    if attr == "volume":
        v = a.get("volume_level")
        return (round(v * 100) if v is not None else None, "%")
    if attr == "temperature":
        return (a.get("temperature"), "°C")
    if attr == "position":
        return (a.get("current_position"), "%")
    return (None, None)


async def _adjust(hass, eids, names, args, exposure, context) -> dict:
    """Relatives Verstellen. Echot den RESULTIERENDEN Wert zurück (Vorher/Nachher-Read), damit die
    Antwort ihn truthful zitieren kann; `at_limit` wenn schon am Anschlag (kein Effekt)."""
    attr = args["attribute"]
    direction = args.get("direction", "up")
    sign = 1 if direction == "up" else -1
    amount = args.get("amount", "some")
    before = {e: (_adj_read(hass.states.get(e), attr)[0] if hass.states.get(e) else None) for e in eids}

    if attr == "brightness":
        step = int(sign * _step(amount, _STEP_PCT))
        await hass.services.async_call("light", "turn_on",
                                       {"entity_id": eids, "brightness_step_pct": step},
                                       blocking=True, context=context)
    elif attr == "volume":
        svc = "volume_up" if sign > 0 else "volume_down"
        await hass.services.async_call("media_player", svc, {"entity_id": eids},
                                       blocking=True, context=context)
    elif attr in ("temperature", "position"):
        delta = sign * (_step(amount, _STEP_DEG) if attr == "temperature" else _step(amount, _STEP_PCT))
        for eid in eids:
            cur = before.get(eid)
            if cur is None:
                continue
            if attr == "temperature":
                await hass.services.async_call("climate", "set_temperature",
                                               {"entity_id": eid, "temperature": float(cur) + delta},
                                               blocking=True, context=context)
            else:
                await hass.services.async_call("cover", "set_cover_position",
                                               {"entity_id": eid, "position": max(0, min(100, int(cur + delta)))},
                                               blocking=True, context=context)
    else:
        return {"ok": False, "error": "not_controllable", "query": attr}

    out = {"ok": True, "targets": names}
    # Wert-Echo nur bei EINDEUTIGEM Einzelziel (Gruppe → mehrdeutig, nur targets)
    if len(eids) == 1:
        st = hass.states.get(eids[0])
        val, unit = _adj_read(st, attr) if st else (None, None)
        if val is not None:
            out["value"] = val
            if unit:
                out["unit"] = unit
            if before.get(eids[0]) is not None and val == before[eids[0]]:
                out["at_limit"] = True      # kein Effekt → schon am Anschlag ("bereits am Minimum")
    return out


# ── get_state (Read-Verb, bleibt im Loop) ─────────────────────────────────────
_ON_STATES = {"on", "open", "home", "playing", "unlocked", "heat", "cool", "auto"}


async def _get_state(hass, args, exposure) -> dict:
    attr = args.get("attribute")
    aggregate = args.get("aggregate")

    if attr == "datetime":
        from homeassistant.util import dt as dt_util
        now = dt_util.now()
        return {"ok": True, "reading": {"attribute": "datetime",
                                        "date": now.strftime("%Y-%m-%d"),
                                        "time": now.strftime("%H:%M"),
                                        "weekday": now.strftime("%A")}}

    eids, err = resolve(args, exposure)
    if err:
        # get_state-Fehler: entity_not_found bleibt, no_targets → no_data-ish
        return err
    if not eids:
        return {"ok": False, "error": "no_data", "query": args.get("name") or ""}

    if aggregate == "count":
        return {"ok": True, "aggregate": "count", "value": len(eids)}

    readings = []
    numeric = []
    on_flags = []
    for eid in eids:
        st = hass.states.get(eid)
        if not st:
            continue
        name = exposure[eid]["llm_name"]
        val, unit, a = _read_attr(st, attr)
        readings.append({"name": name, "attribute": a, "value": val,
                         **({"unit": unit} if unit else {})})
        if isinstance(val, (int, float)):
            numeric.append(val)
        on_flags.append(str(st.state).lower() in _ON_STATES)

    if aggregate in ("any", "all"):
        v = (any(on_flags) if aggregate == "any" else all(on_flags))
        detail = [readings[i]["name"] for i, f in enumerate(on_flags) if f != v]
        out = {"ok": True, "aggregate": aggregate, "value": v}
        if detail:
            out["detail"] = detail[:3]
        return out
    if aggregate in ("avg", "min", "max") and numeric:
        agg = (sum(numeric) / len(numeric) if aggregate == "avg"
               else min(numeric) if aggregate == "min" else max(numeric))
        return {"ok": True, "aggregate": aggregate, "value": round(agg, 1)}

    if not readings:
        return {"ok": False, "error": "no_data", "query": args.get("name") or ""}
    return {"ok": True, "readings": readings}


def _read_attr(st, attr):
    """(value, unit, effektives-attribut) für eine Entität + gefragtes Attribut."""
    a = st.attributes
    if attr in (None, "state"):
        return st.state, None, "state"
    if attr == "temperature":
        v = a.get("temperature", a.get("current_temperature"))
        return v, "°C", "temperature"
    if attr == "brightness":
        b = a.get("brightness")
        return (round(b / 255 * 100) if b is not None else None), "%", "brightness"
    if attr == "position":
        return a.get("current_position"), "%", "position"
    if attr == "open":
        return (st.state == "open"), None, "open"
    return st.state, None, "state"


# ── Öffentlicher Einstieg ─────────────────────────────────────────────────────
async def execute_calls(hass: HomeAssistant, parsed, exposure: dict,
                        context: Context, deny: list[str]) -> str:
    """ParseResult → rev2-Result-JSON-String (kompakt). Single-Call = reiches Einzel-Result;
    Multi-Call = sequenziell + EIN aggregiertes {ok,targets[,failed]}."""
    calls = parsed.calls
    if len(calls) == 1:
        res = await _exec_one(hass, calls[0], exposure, context, deny)
        return json.dumps(res, ensure_ascii=False, separators=(",", ":"))

    # Multi-Call: aggregieren (Aktions-Verben). Reads im Multi-Turn sind untypisch → best effort.
    targets, failed, ok = [], [], True
    for c in calls:
        r = await _exec_one(hass, c, exposure, context, deny)
        if r.get("ok"):
            targets += r.get("targets", [])
        else:
            ok = False
            targets += r.get("targets", [])
            q = r.get("query") or (r.get("candidates") or ["?"])[0]
            failed.append({"name": q, "error": r.get("error", "failed")})
    if ok:
        res = {"ok": True, "targets": targets}
    else:
        res = {"ok": False, "targets": targets, "failed": failed}
    return json.dumps(res, ensure_ascii=False, separators=(",", ":"))
