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

from . import mapping
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
        return R.with_say(await _deferred(hass, call, exposure, context, device_id), verb, args)

    # v23.5: Single-Exit über with_say — auch Fehler-Results tragen jetzt die Failure-say (B1,
    # train==serve). Bei Klärungs-Fehlern (dym/ambiguous/invalid_value) ist with_say ein No-Op.
    return R.with_say(await _exec_action(hass, verb, args, exposure, context, deny), verb, args)


async def _exec_action(hass: HomeAssistant, verb: str, args: dict, exposure: dict,
                       context: Context, deny: list) -> dict:
    """Mutierendes/Aktions-Verb: Ziel auflösen → dispatchen; liefert das ROHE Result/Fehler-dict
    (die Failure-/Erfolgs-say hängt der Aufrufer via with_say an, train==serve)."""
    # Ziel auflösen (geteilter Resolver)
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
            return await _set_state(hass, eids, names, args, exposure, context)
        if verb == "adjust":
            return await _adjust(hass, eids, names, args, exposure, context)
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
    # B3: stop nur für cover/vacuum (Bewegung). fan/media/light haben keinen Stopp → not_controllable
    # statt Fake-„gestoppt" (train==serve via geteiltem strip_to_stoppable).
    keep, err = R.strip_to_stoppable(eids, exposure)
    if err:
        return err
    for eid in keep:
        dom = exposure[eid]["domain"]
        if dom == "cover":
            await hass.services.async_call("cover", "stop_cover", {"entity_id": eid},
                                           blocking=True, context=context)
        elif dom == "vacuum":
            await hass.services.async_call("vacuum", "stop", {"entity_id": eid},
                                           blocking=True, context=context)
    return R.shape_turn(R.names_of(exposure, keep))


async def _dispatch_pct(hass, domain, service, param, eids, exposure, canon, context, scale=1) -> None:
    """pct-Attribut an HA dispatchen — pro Entität Limit-Mapping (virtuell `canon` → echte Range).

    Nach dem gemappten *echten* Wert gebündelt (i.d.R. genau 1 Bucket, wenn keine/gleiche Limits
    → identischer Service-Call wie zuvor). Das Result echot weiterhin `canon` (virtuell) — s. Aufrufer."""
    buckets: dict[int, list] = {}
    for e in eids:
        real = mapping.apply(canon, exposure.get(e, {}).get("limit"))
        buckets.setdefault(real, []).append(e)
    for real, es in buckets.items():
        val = real * scale if scale != 1 else real
        await hass.services.async_call(domain, service, {"entity_id": es, param: val},
                                       blocking=True, context=context)


async def _dispatch_attr(hass, attr, canon, eids, exposure, context) -> None:
    """Ein set_state-Attribut mit EINEM effektiven Wert an HA dispatchen (Service-Map = statischer
    WIE-Teil; das OB entscheidet capabilities_of vorher). pct-Attrs via _dispatch_pct (Limit-Mapping
    virtuell→real). Nur EXECUTABLE_ATTRS-Attribute erreichen diese Funktion (Guard im Aufrufer;
    `preset` ∈ EXECUTABLE_ATTRS aber ∉ ATTR_DOMAIN — Multi-Domain, hier per Domain gesplittet)."""
    if attr == "brightness":
        await _dispatch_pct(hass, "light", "turn_on", "brightness_pct", eids, exposure, canon, context)
    elif attr == "volume":
        await _dispatch_pct(hass, "media_player", "volume_set", "volume_level", eids, exposure, canon,
                            context, scale=0.01)
    elif attr == "position":
        await _dispatch_pct(hass, "cover", "set_cover_position", "position", eids, exposure, canon, context)
    elif attr == "fan_speed":
        await _dispatch_pct(hass, "fan", "set_percentage", "percentage", eids, exposure, canon, context)
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
    elif attr == "effect":         # v23.6 P3-wire: Licht-Effekt (canon ∈ effect_list, Enum-gated)
        await hass.services.async_call("light", "turn_on",
                                       {"entity_id": eids, "effect": canon},
                                       blocking=True, context=context)
    elif attr == "hvac_mode":      # v23.6 P3-wire: Betriebsmodus (canon ∈ hvac_modes, Enum-gated)
        await hass.services.async_call("climate", "set_hvac_mode",
                                       {"entity_id": eids, "hvac_mode": canon},
                                       blocking=True, context=context)
    elif attr == "preset":         # v23.6 P3-wire: mehrdeutig → nach Domain splitten (climate vs fan)
        cl = [e for e in eids if exposure[e]["domain"] == "climate"]
        fn = [e for e in eids if exposure[e]["domain"] == "fan"]
        if cl:
            await hass.services.async_call("climate", "set_preset_mode",
                                           {"entity_id": cl, "preset_mode": canon},
                                           blocking=True, context=context)
        if fn:
            await hass.services.async_call("fan", "set_preset_mode",
                                           {"entity_id": fn, "preset_mode": canon},
                                           blocking=True, context=context)
    elif attr == "oscillate":      # v23.6 P3-wire: canon ∈ {on,off} (ONOFF-Enum)
        await hass.services.async_call("fan", "oscillate",
                                       {"entity_id": eids, "oscillating": canon == "on"},
                                       blocking=True, context=context)
    elif attr == "tilt":           # v23.6 P3-wire: Lamellen-Position. DIREKT (kein Limit-Mapping —
        await hass.services.async_call("cover", "set_cover_tilt_position",   # `limit` gilt für position,
                                       {"entity_id": eids, "tilt_position": int(canon)},  # nicht die Tilt-Achse)
                                       blocking=True, context=context)
    elif attr == "swing_mode":     # v23.6 Batch1a: canon ∈ swing_modes (Enum-gated)
        await hass.services.async_call("climate", "set_swing_mode",
                                       {"entity_id": eids, "swing_mode": canon},
                                       blocking=True, context=context)
    elif attr == "fan_mode":       # v23.6 Batch1a: climate-Lüftermodus, canon ∈ fan_modes (Enum-gated)
        await hass.services.async_call("climate", "set_fan_mode",
                                       {"entity_id": eids, "fan_mode": canon},
                                       blocking=True, context=context)
    elif attr == "option":         # v23.6 Batch1a: mehrdeutig → nach Domain splitten (select vs input_select)
        for d in ("select", "input_select"):
            de = [e for e in eids if exposure[e]["domain"] == d]
            if de:
                await hass.services.async_call(d, "select_option",
                                               {"entity_id": de, "option": canon},
                                               blocking=True, context=context)
    elif attr == "lock":            # Safety — nur erreichbar wenn unsafe_mode lock aus deny nahm
        await hass.services.async_call("lock", "lock" if canon == "locked" else "unlock",
                                       {"entity_id": eids}, blocking=True, context=context)
    elif attr == "alarm":          # Safety — dito (deny-gesteuert per Config-Toggle)
        svc = {"armed_home": "alarm_arm_home", "armed_away": "alarm_arm_away",
               "armed_night": "alarm_arm_night", "disarmed": "alarm_disarm"}[canon]
        await hass.services.async_call("alarm_control_panel", svc,
                                       {"entity_id": eids}, blocking=True, context=context)


async def _set_state(hass, eids, names, args, exposure, context) -> dict:
    """v23.5 Phase 4 — dynamisch: pro Ziel echte Live-Caps (capabilities_of aus hass.states) →
    geteilter Gruppen-Planer (plan_group_set_state, per-Entität → partial, Benni 2026-07-14). Result
    (done/done_clamped/not_capable/invalid_value/partial) train==serve. Dispatch NUR die geplant-
    ausführbaren Ziele, gebündelt nach effektivem (ggf. geräte-echt geklemmtem) Wert."""
    attr, val = args["attribute"], args["value"]
    if attr not in R.EXECUTABLE_ATTRS:       # v23.6 P3-wire + Batch1a: effect/hvac_mode/preset/oscillate/
        return R.err_not_controllable(attr)  # tilt/swing_mode/fan_mode/option verdrahtet (advertised⊆executable)
    entries = [(e, exposure[e]["llm_name"],
                R.capabilities_of(exposure[e]["domain"], _state_read(hass, e) or {})) for e in eids]
    res, dispatch = R.plan_group_set_state(attr, val, entries)
    buckets: dict = {}
    for eid, canon, _unit in dispatch:       # effektiver Wert kann pro Entität abweichen (Klemmung)
        buckets.setdefault(canon, []).append(eid)
    for canon, bucket_eids in buckets.items():
        await _dispatch_attr(hass, attr, canon, bucket_eids, exposure, context)
    return res


def _adj_before(hass, eids, attr, exposure) -> tuple:
    """(before_virtuell, before_real, unit) pro Entität. Für pct-Attrs mit Limit wird der Read
    in den virtuellen 0–100-Raum umgerechnet (das Echo lebt virtuell → train==serve). Ohne Limit
    ist virtuell == real (Identität) → Verhalten unverändert."""
    before, real_before, unit = {}, {}, None
    for e in eids:
        v, u = R.adj_read(_state_read(hass, e), attr)
        real_before[e] = v
        lim = exposure.get(e, {}).get("limit") if attr in mapping.PCT_ATTRS else None
        before[e] = mapping.to_virtual(v, lim) if lim else v
        unit = unit or u
    return before, real_before, unit


async def _adjust(hass, eids, names, args, exposure, context) -> dict:
    """Relatives Verstellen. Echot den RESULTIERENDEN (virtuellen) Wert zurück (Vorher/Nachher-Read
    via result.adj_read), damit die Antwort ihn truthful zitieren kann; at_limit-Logik = shape_adjust.

    Limit-Mapping (mapping.py): brightness skaliert den Schritt auf die Range, position verstellt im
    virtuellen Raum und mapped aufs echte Gerät. Echo bleibt virtuell. temperature (°C) und volume
    (grobe HA-up/down-Schritte) sowie fan_speed werden NICHT gemappt (unverändert)."""
    attr = args["attribute"]
    direction = args.get("direction", "up")
    amount = args.get("amount", "some")
    before, real_before, unit = _adj_before(hass, eids, attr, exposure)

    # `after` wird ANALYTISCH aus dem kommandierten Schritt gebaut, NICHT nach dem Service-Call
    # zurückgelesen: der HA-State-Write racet nach `blocking=True` (Stale-Read → after==before →
    # falsches at_limit, obwohl real gedimmt wurde, Bug 2026-07-13). Der virtuelle Schritt ist
    # deterministisch und clampt in [0,100] wie der Generator-Sim → train==serve auf value/at_limit.
    after: dict = {}
    if attr == "brightness":
        vstep = int(R.adjust_delta("brightness", amount, direction))   # virtueller Schritt (vorzeichenbehaftet)
        buckets: dict[int, list] = {}                                  # nach echtem (skaliertem) Schritt bündeln
        for e in eids:
            rstep = mapping.scale_step(vstep, exposure.get(e, {}).get("limit"))
            buckets.setdefault(rstep, []).append(e)
            after[e] = max(0, min(100, before[e] + vstep))
        for rstep, es in buckets.items():
            await hass.services.async_call("light", "turn_on",
                                           {"entity_id": es, "brightness_step_pct": rstep},
                                           blocking=True, context=context)
    elif attr == "volume":
        svc = "volume_up" if direction == "up" else "volume_down"
        await hass.services.async_call("media_player", svc, {"entity_id": eids},
                                       blocking=True, context=context)
        for e in eids:                     # HA volume_up/down ist grob → kein präziser Wert (nur Richtung)
            after[e] = before.get(e)
    elif attr in ("temperature", "position", "fan_speed"):
        delta = R.adjust_delta(attr, amount, direction)
        for eid in eids:
            if attr == "temperature":
                cur = real_before.get(eid)
                if cur is None:
                    continue
                tgt = float(cur) + delta
                await hass.services.async_call("climate", "set_temperature",
                                               {"entity_id": eid, "temperature": tgt},
                                               blocking=True, context=context)
                after[eid] = tgt
            elif attr == "fan_speed":       # Reconcile 2026-07-10: Generator trainiert adjust(fan_speed)
                cur = real_before.get(eid)
                if cur is None:
                    continue
                tgt = max(0, min(100, int(cur + delta)))
                await hass.services.async_call("fan", "set_percentage",
                                               {"entity_id": eid, "percentage": tgt},
                                               blocking=True, context=context)
                after[eid] = tgt
            else:                           # position — virtuell verstellen, auf echte Range mappen
                vcur = before.get(eid)
                if vcur is None:
                    continue
                vtar = max(0, min(100, int(vcur + delta)))
                real_tar = mapping.apply(vtar, exposure.get(eid, {}).get("limit"))
                await hass.services.async_call("cover", "set_cover_position",
                                               {"entity_id": eid, "position": max(0, min(100, real_tar))},
                                               blocking=True, context=context)
                after[eid] = vtar
    else:
        return R.err_not_controllable(attr)

    return R.shape_adjust(names, before, after, eids, unit)


# ── get_state (Read-Verb, bleibt im Loop) ─────────────────────────────────────
async def _get_state(hass, args, exposure) -> dict:
    attr = args.get("attribute")
    aggregate = args.get("aggregate")

    if attr == "datetime":
        from homeassistant.util import dt as dt_util
        return R.shape_datetime(dt_util.now())

    if attr == "weather":
        return await _get_weather(hass, args, exposure)

    if attr == "sun":
        return _get_sun(hass)

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

    reads = R.narrow_area_reads(args, attr, reads)   # area-value: Raum → Metrik-Sensor(en)
    res = R.shape_get_state(attr, aggregate, reads)
    if res.get("error") == "no_data":   # query erden (Serve-Parität: name|area|floor, wie emit read_result)
        res["query"] = args.get("name") or args.get("area") or args.get("floor") or ""
    return res


# ── Sonnenstand (v23.2): flacher Read aus sun.sun → geteiltes shape_sun ────────
def _get_sun(hass) -> dict:
    """attribute="sun" → sun.sun lesen. state = above/below_horizon (autoritatives is_dark);
    next_rising/next_setting (ISO-UTC) → lokale HH:MM. Wie datetime: keine Entität-Auflösung nötig."""
    from homeassistant.util import dt as dt_util
    st = hass.states.get("sun.sun")
    if st is None:
        return R.err_unavailable("sun")

    def _local_hhmm(iso):
        dt = dt_util.parse_datetime(iso) if iso else None
        return dt_util.as_local(dt).strftime("%H:%M") if dt else None

    a = st.attributes
    sunrise = _local_hhmm(a.get("next_rising"))
    sunset = _local_hhmm(a.get("next_setting"))
    is_dark = (st.state == "below_horizon") if st.state in ("above_horizon", "below_horizon") else None
    return R.shape_sun(sunrise, sunset, is_dark)


# ── Weather (v23.2): Read-Verb → live get_forecasts → geteilter Block-Builder ──
async def _get_weather(hass, args, exposure) -> dict:
    """attribute="weather" → Wetter-Entität auflösen, `weather.get_forecasts` (daily) holen,
    auf den normalisierten Struct mappen und mit dem GETEILTEN R.build_weather_block (via
    R.shape_weather) rendern → identisch zur Generator-Seite (train==serve).

    Ziel: benannter/lokalisierter Standort, sonst Default = erste exponierte weather-Entität
    (Multi-Standort fällt gratis aus dem Resolver, WEATHER_CONCEPT.md §Multi-Standort)."""
    if args.get("name") or args.get("area") or args.get("floor"):
        eids, err = R.resolve(args, exposure)
        if err:
            return err
        eids = [e for e in eids if exposure[e]["domain"] == "weather"]
    else:
        eids = [e for e, rec in exposure.items() if rec["domain"] == "weather"]
    if not eids:
        return R.err_no_targets(args.get("name") or "")

    eid = eids[0]   # MVP: Default-Standort = erste Wetter-Entität
    struct = await _weather_struct(hass, eid)
    if struct is None:   # Entität offline/unavailable ODER Forecast leer/fehlgeschlagen →
        return R.err_unavailable(args.get("name") or "")   # ehrlicher Fehler statt Rumpf-Block,
    #   den das Training NIE sah (train==serve-Verteilung: der Block hat IMMER ≥1 Forecast-Tag).
    return R.shape_weather(exposure[eid]["llm_name"], struct)


async def _weather_struct(hass, eid: str) -> dict | None:
    """HA-Wetter-Entität → {now, days[≤3]} ODER None (→ err_unavailable). Nur die Felder, die auch
    die Train-Quelle liefert (condition/high/low); precip wird NICHT in den Struct gereicht (Regen
    qualitativ aus cond im Builder). days POSITIONAL [0]=heute (HA-daily-Forecast ist heute-first).

    None bei: Entität fehlt/unavailable/unknown, get_forecasts-Fehler, ODER leerer Forecast. Damit
    erreicht KEIN Rumpf-Block (nur `Jetzt:`-Zeile, 0 Tage) je das Modell — der geteilte Builder
    bekommt serve-seitig garantiert dieselbe Form wie im Training (≥1 Tag)."""
    st = hass.states.get(eid)
    if st is None or st.state in ("unavailable", "unknown", "", None):
        return None
    try:
        resp = await hass.services.async_call(
            "weather", "get_forecasts",
            {"entity_id": eid, "type": "daily"},
            blocking=True, return_response=True)
    except Exception:   # noqa: BLE001 — Wetter darf den Loop nie sprengen
        _LOGGER.warning("weather.get_forecasts fehlgeschlagen für %s", eid, exc_info=True)
        return None

    forecast = ((resp or {}).get(eid) or {}).get("forecast") or []
    days = []
    for f in forecast[:3]:
        days.append({"cond": f.get("condition"),
                     "high": f.get("temperature"),   # daily: temperature = Tages-Hoch
                     "low": f.get("templow"),         # templow = Nacht-Tief
                     "date": (f.get("datetime") or "")[:10]})
    if not days:                                      # leerer Forecast → err_unavailable (s.o.)
        return None
    now = {"cond": st.state, "temp": st.attributes.get("temperature")}
    return {"now": now, "days": days}


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
    # `say` je Erfolgs-Call einsammeln + zu EINER Phrase verketten (spiegelt R/action_result, train==serve).
    targets, failed, says, ok = [], [], [], True
    for c in calls:
        r = await _exec_one(hass, c, exposure, context, deny, device_id)
        if r.get("ok"):
            targets += r.get("targets", [])
            if r.get("say"):
                says.append(r["say"])
        else:
            ok = False
            targets += r.get("targets", [])
            if r.get("failed"):                     # Sub-Result war selbst partial (Gruppen-set_state) → failed übernehmen
                failed += r["failed"]
            else:
                q = r.get("query") or (r.get("candidates") or ["?"])[0]
                failed.append({"name": q, "error": r.get("error", "failed")})
    if ok:
        res = {"ok": True, "targets": targets}
        if says:
            res["say"] = "; ".join(dict.fromkeys(says))
    else:
        res = {"ok": False, "targets": targets, "failed": failed}
        res["say"] = R.partial_say(res)       # v23.5 P4: truthful Aggregat-say (train==serve, s. action_result)
    return json.dumps(res, ensure_ascii=False, separators=(",", ":"))
