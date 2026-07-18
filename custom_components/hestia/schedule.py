"""schedule — v23.7 Zeitsteuerung: geplante Gerätebefehle via getaggte HA-Automation.

Design (V23_7_TIME_SCHEDULING_SPIKE.md, Benni-lock): `set_timer` mit `do_verb` = geplanter Befehl.
Statt selbst zu schedulen legt Hestia eine **native HA-Automation** an (analog zum Helfer-Muster):
Persistenz gratis (überlebt Neustart), sichtbar/managebar in HAs Automations-UI, Ownership-getrennt.

Backing: `automations.yaml` (config: `automation: !include automations.yaml`) lesen → eigene Einträge
(id-Präfix `hestia_sched_`) mutieren → `automation.reload`. Ownership-Store `hestia.schedules_owned`
merkt sich NUR eigene Schedules (die Helfer-Lösch-Lehre v0.1.3: nie ohne Ownership-Filter anfassen).

Self-Cleanup (kein fragiles Self-Delete — HA hat keinen Automation-Delete-Service):
  1. on-fire Self-Disable (letzte Automation-Action = `automation.turn_off {{ this.entity_id }}`).
  2. täglicher Cleanup + Startup-Cleanup löschen deaktivierte eigene one-shot-Schedules.

Lifecycle (Vokabel vom Timer geerbt): cancel=löschen · add/subtract=Triggerzeit neu · pause/resume=
disable/enable · check=eigene listen. Alles NUR über den Ownership-Store.
"""
from __future__ import annotations

import os
import re
from datetime import timedelta

from homeassistant.core import HomeAssistant, Context
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
import yaml

from .hestia_cap import cap_attrs
from .hestia_cap import result as R

_OWN_KEY = "hestia.schedules_owned"
_OWN_VERSION = 1
_ID_PREFIX = "hestia_sched_"
_ALIAS_PREFIX = "Hestia: "


# ── Ownership-Store ──────────────────────────────────────────────────────────
async def _load(hass: HomeAssistant) -> dict:
    """{id: {label, do_verb, do_target, entity_ids, when, trigger, created}} + counter."""
    data = await Store(hass, _OWN_VERSION, _OWN_KEY).async_load() or {}
    return {"schedules": dict(data.get("schedules", {})), "counter": int(data.get("counter", 0))}


async def _save(hass: HomeAssistant, data: dict) -> None:
    await Store(hass, _OWN_VERSION, _OWN_KEY).async_save(
        {"schedules": data["schedules"], "counter": data["counter"]})


async def owned_ids(hass: HomeAssistant) -> set[str]:
    return set((await _load(hass))["schedules"])


# ── Zeit-Mathe (Executor rechnet, nicht das Modell) ──────────────────────────
def _parse_duration(d) -> timedelta | None:
    """'1h30min'/'50min'/'90s' → timedelta. None wenn nichts Gültiges."""
    secs = 0
    found = False
    for num, unit in re.findall(r"(\d+)\s*(h|min|s)", str(d or "")):
        secs += int(num) * {"h": 3600, "min": 60, "s": 1}[unit]
        found = True
    return timedelta(seconds=secs) if found else None


def _trigger_time(at: str | None, duration: str | None) -> str | None:
    """(at|duration) → 'HH:MM:SS' Trigger-Zeit. `at` absolut (nächstes Vorkommen); `duration` relativ
    zu jetzt. HAs time-Trigger feuert täglich zu HH:MM:SS — one-shot garantiert der Self-Disable."""
    if at:
        m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", at.strip())
        if not m:
            return None
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        if not (0 <= h < 24 and 0 <= mi < 60 and 0 <= s < 60):
            return None
        return f"{h:02d}:{mi:02d}:{s:02d}"
    delta = _parse_duration(duration)
    if delta is None or delta.total_seconds() <= 0:
        return None
    return (dt_util.now() + delta).strftime("%H:%M:%S")


# ── do-Aktion → HA-Automation-Action-Dict ────────────────────────────────────
# pct-Attribute: virtueller 0-100-Wert; im Automation-Kontext ohne Limit-Mapping (Schedule = fixe
# Entität, kein Gruppen-Limit-Bucket → direkter Service-Wert wie im Nicht-gemappten Fall).
def _do_action(do_verb: str, attr: str | None, value, eids: list) -> dict | None:
    """HA-Service-Action-Dict für die geplante Aktion, oder None wenn nicht ausführbar."""
    tgt = {"entity_id": eids}
    if do_verb == "turn_on":
        return {"service": "homeassistant.turn_on", "target": tgt}
    if do_verb == "turn_off":
        return {"service": "homeassistant.turn_off", "target": tgt}
    if do_verb != "set_state" or attr is None:
        return None
    # set_state: Attribut → (service, data). Spiegelt executor._dispatch_attr (WIE-Teil), aber statisch.
    if attr == "brightness":
        return {"service": "light.turn_on", "target": tgt, "data": {"brightness_pct": int(value)}}
    if attr == "color_temp":
        return {"service": "light.turn_on", "target": tgt, "data": {"color_temp_kelvin": int(value)}}
    if attr == "color":
        return {"service": "light.turn_on", "target": tgt, "data": {"color_name": str(value).replace("_", "")}}
    if attr == "temperature":
        return {"service": "climate.set_temperature", "target": tgt, "data": {"temperature": float(value)}}
    if attr == "fan_speed":
        return {"service": "fan.set_percentage", "target": tgt, "data": {"percentage": int(value)}}
    if attr == "position":
        return {"service": "cover.set_cover_position", "target": tgt, "data": {"position": int(value)}}
    if attr == "tilt":
        return {"service": "cover.set_cover_tilt_position", "target": tgt, "data": {"tilt_position": int(value)}}
    if attr == "volume":
        return {"service": "media_player.volume_set", "target": tgt, "data": {"volume_level": int(value) * 0.01}}
    if attr == "humidity":
        return {"service": "humidifier.set_humidity", "target": tgt, "data": {"humidity": int(value)}}
    row = cap_attrs.BY_ATTR.get(attr)            # enum-Cap-Attrs (hvac_mode/preset/…): Tabellen-Service
    if row:
        ha_dom, svc, param = row.service
        return {"service": f"{ha_dom}.{svc}", "target": tgt, "data": {param: value}}
    return None


# ── automations.yaml-Backing (in-process) ────────────────────────────────────
def _yaml_path(hass: HomeAssistant) -> str:
    return hass.config.path("automations.yaml")


def _read_autos(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def _write_autos(path: str, autos: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(autos, f, allow_unicode=True, sort_keys=False)


async def _rewrite(hass: HomeAssistant, mutate) -> None:
    """automations.yaml lesen → `mutate(list)` → schreiben → automation.reload. Executor-Job für I/O."""
    path = _yaml_path(hass)
    autos = await hass.async_add_executor_job(_read_autos, path)
    autos = mutate(autos)
    await hass.async_add_executor_job(_write_autos, path, autos)
    await hass.services.async_call("automation", "reload", {}, blocking=True)


def _automation_cfg(sched_id: str, label: str, trigger: str, do_action: dict) -> dict:
    """Getaggte one-shot-Automation: time-Trigger → do-Aktion + Self-Disable (kein Re-Fire)."""
    return {
        "id": sched_id,
        "alias": f"{_ALIAS_PREFIX}{label}",
        "mode": "single",
        "trigger": [{"platform": "time", "at": trigger}],
        "action": [
            do_action,
            {"service": "automation.turn_off", "target": {"entity_id": "{{ this.entity_id }}"}},
        ],
    }


# ── Öffentliche Lifecycle-API (aus dem Executor gerufen) ─────────────────────
async def create(hass: HomeAssistant, args: dict, exposure: dict, context: Context) -> dict:
    """Geplante Aktion anlegen. Result train==serve-neutral (ok+targets), Answer baut die say aus args."""
    eids, err = R.resolve({"name": args.get("do_target")}, exposure)
    if err:
        return err
    trigger = _trigger_time(args.get("at"), args.get("duration"))
    if trigger is None:
        return R.err_unparseable()
    action = _do_action(args["do_verb"], args.get("do_attribute"), args.get("do_value"), eids)
    if action is None:
        return R.err_not_controllable(args.get("do_attribute") or args["do_verb"])
    data = await _load(hass)
    data["counter"] += 1
    sched_id = f"{_ID_PREFIX}{data['counter']}"
    label = args.get("label") or R.names_of(exposure, eids)[0]
    cfg = _automation_cfg(sched_id, label, trigger, action)
    await _rewrite(hass, lambda autos: [a for a in autos if a.get("id") != sched_id] + [cfg])
    data["schedules"][sched_id] = {
        "label": label, "do_verb": args["do_verb"], "do_target": args.get("do_target"),
        "entity_ids": eids, "at": args.get("at"), "duration": args.get("duration"),
        "trigger": trigger, "created": dt_util.now().isoformat(timespec="seconds")}
    await _save(hass, data)
    # Result STABIL via geteiltem Shaper (train==serve): scheduled=True (die echte Triggerzeit ist bei
    # `duration` nicht-deterministisch und darf das asserted Gold nicht speisen); say aus with_say.
    return R.shape_schedule(args, R.names_of(exposure, eids), label=label)


async def _find(hass: HomeAssistant, label: str | None):
    """(sched_id, meta) des eigenen Schedules per label (case-insensitiv, Teilstring), oder (None,None).
    Genau 1 eigenes → auch ohne label matchbar (häufigster Voice-Fall)."""
    data = await _load(hass)
    scheds = data["schedules"]
    if not scheds:
        return None, None, data
    if not label:
        if len(scheds) == 1:
            sid = next(iter(scheds))
            return sid, scheds[sid], data
        return None, None, data
    lab = label.strip().lower()
    for sid, m in scheds.items():
        if lab in (m.get("label") or "").lower():
            return sid, m, data
    return None, None, data


async def cancel(hass: HomeAssistant, label: str | None, context: Context) -> dict:
    sid, meta, data = await _find(hass, label)
    if not sid:
        return R.err_no_targets(label or "")
    await _rewrite(hass, lambda autos: [a for a in autos if a.get("id") != sid])
    data["schedules"].pop(sid, None)
    await _save(hass, data)
    return R.ok(targets=[meta["label"]], cancelled=True)


async def reschedule(hass: HomeAssistant, label: str | None, duration: str, subtract: bool,
                     context: Context) -> dict:
    """add/subtract: Triggerzeit um ±duration verschieben (neu schreiben)."""
    sid, meta, data = await _find(hass, label)
    if not sid:
        return R.err_no_targets(label or "")
    delta = _parse_duration(duration)
    if delta is None:
        return R.err_unparseable()
    base = dt_util.now().replace(hour=int(meta["trigger"][:2]), minute=int(meta["trigger"][3:5]),
                                 second=int(meta["trigger"][6:8]), microsecond=0)
    newt = (base - delta if subtract else base + delta).strftime("%H:%M:%S")
    action = _do_action(meta["do_verb"], None, None, meta["entity_ids"]) \
        if meta["do_verb"] != "set_state" else None
    # set_state-Reschedule: bestehende Action aus dem yaml behalten (Trigger-only-Patch)
    def _mut(autos):
        for a in autos:
            if a.get("id") == sid:
                a["trigger"] = [{"platform": "time", "at": newt}]
        return autos
    await _rewrite(hass, _mut)
    meta["trigger"] = newt
    await _save(hass, data)
    return R.ok(targets=[meta["label"]], scheduled=True, label=meta["label"])


async def set_enabled(hass: HomeAssistant, label: str | None, enabled: bool, context: Context) -> dict:
    """pause/resume → automation.turn_off/on auf die eigene Automation."""
    sid, meta, data = await _find(hass, label)
    if not sid:
        return R.err_no_targets(label or "")
    eid = _automation_entity_id(hass, sid)
    if eid:
        await hass.services.async_call("automation", "turn_on" if enabled else "turn_off",
                                       {"entity_id": eid}, blocking=True, context=context)
    return R.ok(targets=[meta["label"]], paused=(not enabled))


async def check(hass: HomeAssistant, context: Context) -> dict:
    """Eigene aktive Schedules listen (Live-Context / Antwort)."""
    data = await _load(hass)
    items = [{"label": m["label"], "trigger": m["trigger"], "do_verb": m["do_verb"],
              "do_target": m.get("do_target")} for m in data["schedules"].values()]
    return R.ok(targets=[], readings=items)


def _automation_entity_id(hass: HomeAssistant, sched_id: str) -> str | None:
    """automation.<slug> per id-Attribut finden (Slug driftet, id ist stabil)."""
    for st in hass.states.async_all("automation"):
        if st.attributes.get("id") == sched_id:
            return st.entity_id
    return None


# ── Cleanup (täglich + Startup): deaktivierte eigene one-shots löschen ────────
async def cleanup(hass: HomeAssistant, context: Context | None = None) -> int:
    """Eigene Schedules löschen, deren Automation off (self-disabled/gefeuert) oder verwaist ist."""
    data = await _load(hass)
    dead = []
    for sid in list(data["schedules"]):
        eid = _automation_entity_id(hass, sid)
        st = hass.states.get(eid) if eid else None
        if st is None or st.state == "off":     # verwaist ODER gefeuert (self-disabled)
            dead.append(sid)
    if not dead:
        return 0
    await _rewrite(hass, lambda autos: [a for a in autos if a.get("id") not in dead])
    for sid in dead:
        data["schedules"].pop(sid, None)
    await _save(hass, data)
    return len(dead)


async def live_context(hass: HomeAssistant) -> list[dict]:
    """Für den Prompt: aktive eigene Schedules (Modell sieht 'Geplant: … um HH:MM (label)')."""
    data = await _load(hass)
    return [{"label": m["label"], "trigger": m["trigger"], "do_verb": m["do_verb"],
             "do_target": m.get("do_target")} for m in data["schedules"].values()]


async def route(hass: HomeAssistant, args: dict, exposure: dict, context: Context):
    """Executor-Einstieg: gibt das Schedule-Result zurück ODER None (= kein Schedule → Timer-Intent).
    `do_verb` (nur mit action=set, Parser-garantiert) → neue geplante Aktion. Lifecycle-Aktionen
    übernimmt schedule NUR, wenn ein eigener Schedule betroffen ist (sonst fällt es auf den Timer)."""
    action = args.get("action")
    if args.get("do_verb"):
        return await create(hass, args, exposure, context)
    if action in ("cancel", "add", "subtract", "pause", "resume"):
        sid, _meta, _data = await _find(hass, args.get("label"))
        if not sid:
            return None
        if action == "cancel":
            return await cancel(hass, args.get("label"), context)
        if action in ("add", "subtract"):
            return await reschedule(hass, args.get("label"), args.get("duration"),
                                    action == "subtract", context)
        return await set_enabled(hass, args.get("label"), action == "resume", context)
    if action == "check":
        if (await _load(hass))["schedules"]:     # eigene Schedules da → listen (sonst Timer-Check)
            return await check(hass, context)
    return None
