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

import re

from homeassistant.core import HomeAssistant, Context
from homeassistant.helpers import intent

from .hestia_cap import result as R

_LOGGER = logging.getLogger(__name__)

# Deferred-Verben (B1=A, Benni 2026-07-09): nativer Dispatch. run_routine/manage_list/control_media/
# control_vacuum via HA-Service; set_timer/announce/play_content via Intent-Layer (TimerManager/
# Broadcast/MediaSource). Result-Shape kommt IMMER aus dem geteilten R.deferred_result (train==serve).
_DEFERRED_VERBS = ("run_routine", "manage_list", "control_media", "control_vacuum",
                   "set_timer", "announce")


def _state_read(hass: HomeAssistant, eid: str) -> dict | None:
    """HA-State → StateProvider-Form {state, attributes} (oder None)."""
    st = hass.states.get(eid)
    if st is None:
        return None
    return {"state": st.state, "attributes": dict(st.attributes)}


# ── Einzel-Call ausführen ─────────────────────────────────────────────────────
async def _exec_one(hass: HomeAssistant, call, exposure: dict, context: Context,
                    deny: list, device_id: str | None = None) -> dict:
    verb, args = call.verb, call.args

    if verb == "get_state":
        return await _get_state(hass, args, exposure)

    if verb in _DEFERRED_VERBS:
        return await _deferred(hass, call, exposure, context, device_id)

    # ab hier: mutierende / Aktions-Verben → Ziel auflösen (geteilter Resolver)
    eids, err = R.resolve(args, exposure)
    if err:
        return err

    # set_state/adjust ohne explizites domain → auf die vom Attribut implizierte Domain einengen
    if verb in ("set_state", "adjust") and "domain" not in args:
        eids, err = R.narrow_by_attr_domain(eids, args.get("attribute"), exposure)
        if err:
            return err

    # Gruppen-turn ohne Name/Domain → read-only Domains (Sensoren/Wetter) raus (H6)
    if verb in ("turn_on", "turn_off") and "name" not in args:
        eids, err = R.strip_readonly_for_turn(eids, exposure)
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

    # Sicherheitsnetz: unbekanntes/nicht implementiertes Verb (z.B. help = Phase 3) → ehrlich melden.
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


# ── Deferred-Verben: nativer Dispatch (B1=A) ──────────────────────────────────
# Simple (target-lose) media/vacuum-Actions → 1:1 HA-Service. Result-Shape IMMER aus R.deferred_result.
_MEDIA_SVC = {
    "play": ("media_play", {}), "pause": ("media_pause", {}),
    "next": ("media_next_track", {}), "previous": ("media_previous_track", {}),
    "stop": ("media_stop", {}),
    "mute": ("volume_mute", {"is_volume_muted": True}),
    "unmute": ("volume_mute", {"is_volume_muted": False}),
}
_VACUUM_SVC = {
    "start": ("start", {}), "return_to_base": ("return_to_base", {}),
    "clean_area": ("start", {}),   # MVP: kein universeller Raum-Clean-Service → start
}
_ROUTINE_SVC = {"scene": ("scene", "turn_on"), "script": ("script", "turn_on"),
                "automation": ("automation", "trigger")}
# Timer-Action → HA-Intent (Voice-Timer leben in HAs TimerManager, KEIN timer.*-Service).
_TIMER_INTENT = {
    "set": "HassStartTimer", "cancel": "HassCancelTimer", "cancel_all": "HassCancelAllTimers",
    "check": "HassTimerStatus", "add": "HassIncreaseTimer", "subtract": "HassDecreaseTimer",
    "pause": "HassPauseTimer", "resume": "HassUnpauseTimer",
}


def _duration_slots(d) -> dict:
    """cap-v2 duration-String ('1h35min'/'60s') → HA-Timer-Intent-Slots {hours,minutes,seconds}."""
    slots = {}
    for num, unit in re.findall(r"(\d+)\s*(h|min|s)", str(d or "")):
        slots[{"h": "hours", "min": "minutes", "s": "seconds"}[unit]] = {"value": int(num)}
    return slots


async def _handle_intent(hass, intent_type: str, slots: dict, context, device_id=None) -> None:
    """An HAs eingebauten Intent-Handler delegieren (TimerManager/Broadcast/MediaSource).
    Slots = {name: {'value': ...}}; device_id = Voice-Satellit (Timer/Broadcast binden daran —
    ohne ihn wirft StartTimer TimersNotSupportedError, exakt wie HA selbst). Raises → err_timeout."""
    await intent.async_handle(hass, "hestia", intent_type,
                              {k: v for k, v in slots.items() if v.get("value") not in (None, "")},
                              context=context, device_id=device_id)


async def _deferred(hass, call, exposure: dict, context: Context, device_id=None) -> dict:
    """run_routine/manage_list/control_media/control_vacuum (HA-Service) +
    set_timer/announce/play_content (Intent-Layer). Result = geteiltes R.deferred_result (train==serve)."""
    verb, args = call.verb, call.args
    res, eids = R.deferred_result(verb, args, exposure)
    if not res.get("ok"):
        return res                       # entity_not_found/ambiguous aus dem geteilten Resolver
    try:
        if verb == "control_media":
            await _dispatch_media(hass, args, eids, args.get("action"), context, device_id)
        elif verb == "control_vacuum":
            svc, extra = _VACUUM_SVC[args["action"]]
            await hass.services.async_call("vacuum", svc, {"entity_id": eids, **extra},
                                           blocking=True, context=context)
        elif verb == "run_routine":
            for eid in eids:
                dom, svc = _ROUTINE_SVC.get(exposure[eid]["domain"], ("homeassistant", "turn_on"))
                await hass.services.async_call(dom, svc, {"entity_id": eid},
                                               blocking=True, context=context)
        elif verb == "manage_list":
            await _dispatch_list(hass, args, eids, context)
        elif verb == "set_timer":
            # add/subtract: duration = Delta (hours/minutes/seconds); cancel/check/pause/resume:
            # kein duration → über name (label) den Timer identifizieren (HA-Slot-Schema).
            slots = _duration_slots(args.get("duration"))
            if args.get("label"):
                slots["name"] = {"value": args["label"]}
            await _handle_intent(hass, _TIMER_INTENT[args["action"]], slots, context, device_id)
        elif verb == "announce":
            await _handle_intent(hass, "HassBroadcast", {"message": {"value": args.get("message", "")}},
                                 context, device_id)
    except Exception as e:  # noqa: BLE001 — HA-Fehler → truthful err_timeout, kein Crash
        _LOGGER.warning("Hestia deferred %s failed: %s", verb, e)
        return R.err_timeout(args.get("name") or args.get("action") or verb)
    return res


async def _dispatch_media(hass, args, eids, action, context, device_id=None) -> None:
    if action == "source":
        await hass.services.async_call("media_player", "select_source",
                                       {"entity_id": eids, "source": args.get("content", "")},
                                       blocking=True, context=context)
        return
    if action == "play_content":         # Search&Play → Intent (Media-Source-Auflösung)
        await _handle_intent(hass, "HassMediaSearchAndPlay",
                             {"search_query": {"value": args.get("content", "")},
                              "name": {"value": args.get("name")},
                              "area": {"value": args.get("area")}}, context, device_id)
        return
    svc, extra = _MEDIA_SVC[action]
    await hass.services.async_call("media_player", svc, {"entity_id": eids, **extra},
                                   blocking=True, context=context)


async def _dispatch_list(hass, args, eids, context) -> None:
    action, item = args["action"], args.get("item", "")
    svc, extra = {
        "add": ("add_item", {"item": item}),
        "remove": ("remove_item", {"item": item}),
        "complete": ("update_item", {"item": item, "status": "completed"}),
    }[action]
    for eid in eids:
        await hass.services.async_call("todo", svc, {"entity_id": eid, **extra},
                                       blocking=True, context=context)


# ── Öffentlicher Einstieg ─────────────────────────────────────────────────────
async def execute_calls(hass: HomeAssistant, parsed, exposure: dict,
                        context: Context, deny: list, device_id: str | None = None) -> str:
    """ParseResult → rev2-Result-JSON-String (kompakt). Single-Call = reiches Einzel-Result;
    Multi-Call = sequenziell + EIN aggregiertes {ok,targets[,failed]}.

    device_id = originierendes Gerät (Voice-Satellit) aus dem Conversation-Input — für den
    Intent-Layer nötig: Voice-Timer/Broadcast binden an den Satelliten (HA-Intent-Kontext)."""
    calls = parsed.calls
    if len(calls) == 1:
        res = await _exec_one(hass, calls[0], exposure, context, deny, device_id)
        return json.dumps(res, ensure_ascii=False, separators=(",", ":"))

    # Multi-Call: aggregieren (Aktions-Verben). Reads im Multi-Turn sind untypisch → best effort.
    targets, failed, ok = [], [], True
    for c in calls:
        r = await _exec_one(hass, c, exposure, context, deny, device_id)
        if r.get("ok"):
            targets += r.get("targets", [])
        else:
            ok = False
            targets += r.get("targets", [])
            q = r.get("query") or (r.get("candidates") or ["?"])[0]
            failed.append({"name": q, "error": r.get("error", "failed")})
    res = {"ok": True, "targets": targets} if ok else {"ok": False, "targets": targets, "failed": failed}
    return json.dumps(res, ensure_ascii=False, separators=(",", ":"))
