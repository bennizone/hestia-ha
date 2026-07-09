"""Executor — Wire→Entität→hass.services + rev2-Result (RESULT_SCHEMA.md).

Der native Kern des Loops: geparste cap-v2-Calls (hestia_cap.Call) gegen HAs Registry
(via Exposure-Set) auflösen, den echten HA-Service rufen, und ein schlankes rev2-Result-JSON
bauen — mit handlungsleitenden Fehlern (did_you_mean/candidates/allowed), damit das LLM
self-correcten oder geerdet zurückfragen kann.

**Result-Shaping/Resolver/Error-Builder leben NICHT hier, sondern in `hestia_cap.result`**
(geteilt mit dem Trainings-Generator → kein train≠serve auf dem Tool-JSON, Audit 2026-07-09).
Diese Datei ist reine SERVE-Orchestrierung: resolve → deny → read-before → HA-service_call →
read-after → shape. Die HA-Primitive (`hass.services.async_call`, `hass.states.get`,
`dt_util.now`) bleiben hier; sie speisen das Result nie direkt.

Resolver ist MVP (exakt/normalisiert + difflib-did_you_mean); area-gewichtetes rapidfuzz = F1.
Multi-Call (>1 Call in einem Turn) → sequenziell ausgeführt, EIN aggregiertes Result (§6.3).
"""
from __future__ import annotations

import json
import logging

from homeassistant.core import HomeAssistant, Context

from .hestia_cap import result as R

_LOGGER = logging.getLogger(__name__)


def _state_read(hass: HomeAssistant, eid: str) -> dict | None:
    """HA-State → StateProvider-Form {state, attributes} (oder None)."""
    st = hass.states.get(eid)
    if st is None:
        return None
    return {"state": st.state, "attributes": dict(st.attributes)}


# ── Einzel-Call ausführen ─────────────────────────────────────────────────────
async def _exec_one(hass: HomeAssistant, call, exposure: dict, context: Context,
                    deny: list) -> dict:
    verb, args = call.verb, call.args

    if verb == "get_state":
        return await _get_state(hass, args, exposure)

    # ab hier: mutierende / Aktions-Verben → Ziel auflösen (geteilter Resolver)
    eids, err = R.resolve(args, exposure)
    if err:
        return err

    # set_state/adjust ohne explizites domain → auf die vom Attribut implizierte Domain einengen
    if verb in ("set_state", "adjust") and "domain" not in args:
        eids, err = R.narrow_by_attr_domain(eids, args.get("attribute"), exposure)
        if err:
            return err

    # Safety-Deny (Schloss/Alarm) — kein Service-Call
    if any(exposure[e]["domain"] in deny for e in eids):
        return R.err_unsafe(args.get("name") or args.get("domain") or "")

    names = R.names_of(exposure, eids)
    try:
        if verb in ("turn_on", "turn_off"):
            return await _turn(hass, verb, eids, names, exposure, context)
        if verb == "stop":
            return await _stop(hass, eids, names, exposure, context)
        if verb == "set_state":
            return await _set_state(hass, eids, names, args, context)
        if verb == "adjust":
            return await _adjust(hass, eids, names, args, context)
    except Exception as e:  # noqa: BLE001 — HA-Service-Fehler → ehrliches Result, kein Crash
        _LOGGER.warning("Hestia executor %s failed: %s", verb, e)
        return R.err_timeout(args.get("name") or args.get("domain") or "")

    # verbleibende Verben (run_routine/set_timer/control_media/announce/manage_list/control_vacuum)
    # sind bewusst DEFERRED (MVP) — ehrlich melden statt raten.
    return R.err_not_controllable(verb)


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
    return R.shape_turn(names)


async def _stop(hass, eids, names, exposure, context) -> dict:
    for eid in eids:
        dom = exposure[eid]["domain"]
        if dom == "cover":
            await hass.services.async_call("cover", "stop_cover", {"entity_id": eid},
                                           blocking=True, context=context)
        elif dom == "vacuum":
            await hass.services.async_call("vacuum", "stop", {"entity_id": eid},
                                           blocking=True, context=context)
    return R.shape_turn(names)


async def _set_state(hass, eids, names, args, context) -> dict:
    attr, val = args["attribute"], args["value"]
    canon, unit, err = R.set_value_or_error(attr, val)   # zentrale Wert-Semantik (B3/invalid_value)
    if err:
        return err
    # Service-Dispatch: HA-spezifisch, aus (attr, canon) abgeleitet. Nur implementierte Attribute;
    # neue Attribute (hvac_mode/preset/lock/alarm/oscillate/tilt/humidity/value/effect/option) sind
    # serve-seitig DEFERRED (Executor-Branches = Phase 1b/3) → ehrlich not_controllable.
    if attr == "brightness":
        await hass.services.async_call("light", "turn_on",
                                       {"entity_id": eids, "brightness_pct": canon},
                                       blocking=True, context=context)
    elif attr == "volume":
        await hass.services.async_call("media_player", "volume_set",
                                       {"entity_id": eids, "volume_level": canon / 100},
                                       blocking=True, context=context)
    elif attr == "position":
        await hass.services.async_call("cover", "set_cover_position",
                                       {"entity_id": eids, "position": canon},
                                       blocking=True, context=context)
    elif attr == "fan_speed":
        await hass.services.async_call("fan", "set_percentage",
                                       {"entity_id": eids, "percentage": canon},
                                       blocking=True, context=context)
    elif attr == "temperature":
        await hass.services.async_call("climate", "set_temperature",
                                       {"entity_id": eids, "temperature": float(canon)},
                                       blocking=True, context=context)
    elif attr == "color":
        await hass.services.async_call("light", "turn_on",
                                       {"entity_id": eids, "color_name": canon.replace("_", "")},
                                       blocking=True, context=context)
    elif attr == "color_temp":
        await hass.services.async_call("light", "turn_on",
                                       {"entity_id": eids, "color_temp_kelvin": int(canon)},
                                       blocking=True, context=context)
    else:
        return R.err_not_controllable(attr)
    return R.shape_set_state(names, canon, unit)


async def _adjust(hass, eids, names, args, context) -> dict:
    """Relatives Verstellen. Echot den RESULTIERENDEN Wert zurück (Vorher/Nachher-Read via
    result.adj_read), damit die Antwort ihn truthful zitieren kann; at_limit-Logik = shape_adjust."""
    attr = args["attribute"]
    direction = args.get("direction", "up")
    amount = args.get("amount", "some")
    unit = None
    before = {}
    for e in eids:
        v, u = R.adj_read(_state_read(hass, e), attr)
        before[e] = v
        unit = unit or u

    if attr == "brightness":
        step = int(R.adjust_delta("brightness", amount, direction))
        await hass.services.async_call("light", "turn_on",
                                       {"entity_id": eids, "brightness_step_pct": step},
                                       blocking=True, context=context)
    elif attr == "volume":
        svc = "volume_up" if direction == "up" else "volume_down"
        await hass.services.async_call("media_player", svc, {"entity_id": eids},
                                       blocking=True, context=context)
    elif attr in ("temperature", "position"):
        delta = R.adjust_delta(attr, amount, direction)
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
        return R.err_not_controllable(attr)

    after = {e: R.adj_read(_state_read(hass, e), attr)[0] for e in eids}
    return R.shape_adjust(names, before, after, eids, unit)


# ── get_state (Read-Verb, bleibt im Loop) ─────────────────────────────────────
async def _get_state(hass, args, exposure) -> dict:
    attr = args.get("attribute")
    aggregate = args.get("aggregate")

    if attr == "datetime":
        from homeassistant.util import dt as dt_util
        return R.shape_datetime(dt_util.now())

    eids, err = R.resolve(args, exposure)
    if err:
        return err

    reads = []
    for eid in eids:
        read = _state_read(hass, eid)
        if read is None:
            continue
        read["name"] = exposure[eid]["llm_name"]
        reads.append(read)

    res = R.shape_get_state(attr, aggregate, reads)
    if res.get("error") == "no_data":   # query erden (Serve-Parität)
        res["query"] = args.get("name") or ""
    return res


# ── Öffentlicher Einstieg ─────────────────────────────────────────────────────
async def execute_calls(hass: HomeAssistant, parsed, exposure: dict,
                        context: Context, deny: list) -> str:
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
    res = {"ok": True, "targets": targets} if ok else {"ok": False, "targets": targets, "failed": failed}
    return json.dumps(res, ensure_ascii=False, separators=(",", ":"))
