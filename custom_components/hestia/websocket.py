"""WebSocket-API fürs Hestia-Panel (Exposure-Kuratierung).

Drei Befehle, alle admin-only (Kuratierung = bewusste Admin-Arbeit):
  - `hestia/exposure/list`       → hinzugefügte Entitäten, angereichert + **Live-State** (fürs ⚠).
  - `hestia/exposure/candidates` → adressierbare, noch NICHT hinzugefügte Entitäten (Add-Dialog).
  - `hestia/exposure/set`        → `{entity_id, patch}` mergen+persistieren, angereicherten Record zurück.

Der „Config-Compiler"-Gedanke lebt hier nur als *Lesen/Schreiben*; die eigentliche Übersetzung
in Sysprompt/Executor macht house_builder (Membership = `added AND active`).
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (area_registry as ar, device_registry as dr,
                                   entity_registry as er, floor_registry as fr)

from . import helpers
from .const import (DOMAIN, CONF_LLAMA_URL, CONF_LOOP_DEPTH, CONF_UNSAFE_MODE,
                    DEFAULT_LOOP_DEPTH, DEFAULT_UNSAFE_MODE)
from .house_builder import _aliases, _entity_area_id, _friendly_name
from .sentences import MODES, SUPPORTED_DOMAINS, get_sentence_store
from .store import PATCHABLE, get_store

# Live-States, die „nicht erreichbar" bedeuten (→ ⚠ im Panel, nur wenn aktiv).
_UNAVAILABLE = ("unavailable", "unknown")

# Entity-Categories, die im Add-Dialog NICHT auftauchen sollen (Config/Diagnose-Krempel).
_HIDDEN_CATEGORIES = ("config", "diagnostic")


@callback
def _area_floor(hass: HomeAssistant, entry, dev_reg, area_reg, floor_reg):
    """(area_name, floor_name) für eine Registry-Entity — beide können None sein."""
    area_id = _entity_area_id(entry, dev_reg)
    if not area_id:
        return None, None
    area = area_reg.async_get_area(area_id)
    if not area:
        return None, None
    floor_name = None
    if area.floor_id:
        fl = floor_reg.async_get_floor(area.floor_id)
        floor_name = fl.name if fl else None
    return area.name, floor_name


@callback
def _enrich(hass: HomeAssistant, entry, record: dict, regs) -> dict:
    """Registry-Entry + Store-Record → Panel-Zeile (eine Wahrheit fürs Frontend)."""
    dev_reg, area_reg, floor_reg = regs
    area, floor = _area_floor(hass, entry, dev_reg, area_reg, floor_reg)
    st = hass.states.get(entry.entity_id)
    raw = st.state if st else None
    ha_name = _friendly_name(hass, entry)
    return {
        "entity_id": entry.entity_id,
        "domain": entry.entity_id.split(".")[0],
        "area": area,
        "floor": floor,
        "ha_name": ha_name,                         # HAs friendly_name (Default/Referenz)
        "llm_name": record["llm_name"] or ha_name,  # effektiver Modell-Name (leer → HA-Name)
        "aliases": record["aliases"],
        "description": record["description"],
        "added": record["added"],
        "active": record["active"],
        "limit_min": record["limit_min"],           # WRITE-Mapping-Range (pct-Domains); 0/100 = kein Mapping
        "limit_max": record["limit_max"],
        "media_context": record["media_context"],   # media_player: im „Läuft gerade …"-Live-Kontext?
        "available": bool(st) and raw not in _UNAVAILABLE,
        "state": raw,
    }


@websocket_api.websocket_command({vol.Required("type"): "hestia/exposure/list"})
@websocket_api.require_admin
@callback
def ws_list(hass: HomeAssistant, connection, msg) -> None:
    """Alle hinzugefügten Entitäten (added=True), angereichert + Live-State."""
    store = get_store(hass)
    ent_reg = er.async_get(hass)
    regs = (dr.async_get(hass), ar.async_get(hass), fr.async_get(hass))
    rows = []
    for eid, rec in store.all_records().items():
        if not rec["added"]:
            continue
        entry = ent_reg.async_get(eid)
        if entry is None:      # Entität aus HA verschwunden → Record bleibt, aber nicht listbar
            continue
        rows.append(_enrich(hass, entry, rec, regs))
    connection.send_result(msg["id"], {"entities": rows})


@websocket_api.websocket_command({vol.Required("type"): "hestia/exposure/candidates"})
@websocket_api.require_admin
@callback
def ws_candidates(hass: HomeAssistant, connection, msg) -> None:
    """Adressierbare, noch nicht hinzugefügte Entitäten (für den Add-Dialog)."""
    store = get_store(hass)
    ent_reg = er.async_get(hass)
    regs = (dr.async_get(hass), ar.async_get(hass), fr.async_get(hass))
    rows = []
    for entry in ent_reg.entities.values():
        if store.get(entry.entity_id)["added"]:
            continue
        if entry.hidden_by is not None or entry.disabled:
            continue
        if entry.entity_category in _HIDDEN_CATEGORIES:
            continue
        rows.append(_enrich(hass, entry, store.get(entry.entity_id), regs))
    connection.send_result(msg["id"], {"entities": rows})


@websocket_api.websocket_command({
    vol.Required("type"): "hestia/exposure/set",
    vol.Required("entity_id"): str,
    vol.Required("patch"): {vol.In(PATCHABLE): object},
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set(hass: HomeAssistant, connection, msg) -> None:
    """Patch mergen + persistieren. Beim Erst-Add: Aliase aus der HA-Registry seeden."""
    store = get_store(hass)
    ent_reg = er.async_get(hass)
    eid = msg["entity_id"]
    entry = ent_reg.async_get(eid)
    if entry is None:
        connection.send_error(msg["id"], "not_found", f"Unbekannte Entität: {eid}")
        return

    patch = dict(msg["patch"])
    # Erst-Add: kein Record da UND wird gerade hinzugefügt → Registry-Aliase als Startpunkt.
    fresh = eid not in store.all_records()
    if fresh and patch.get("added") and "aliases" not in patch:
        reg_aliases = _aliases(entry)
        if reg_aliases:
            patch["aliases"] = reg_aliases

    rec = await store.async_set(eid, patch)
    regs = (dr.async_get(hass), ar.async_get(hass), fr.async_get(hass))
    connection.send_result(msg["id"], _enrich(hass, entry, rec, regs))


# ── Helfer (READ-Aggregation, native HA-Helfer via Config-Flow — helpers.py) ──
@websocket_api.websocket_command({vol.Required("type"): "hestia/helper/list"})
@websocket_api.require_admin
@callback
def ws_helper_list(hass: HomeAssistant, connection, msg) -> None:
    """Von uns verwaltbare Helfer (min_max/group-Config-Entries)."""
    connection.send_result(msg["id"], {"helpers": helpers.list_helpers(hass)})


@websocket_api.websocket_command({
    vol.Required("type"): "hestia/helper/create",
    vol.Required("kind"): vol.In(("numeric", "binary")),
    vol.Required("name"): str,
    vol.Required("entities"): [str],
    vol.Optional("agg", default="mean"): str,      # numeric: mean/min/max/median
    vol.Optional("mode", default="any"): vol.In(("any", "all")),   # binary: ODER/UND
    vol.Optional("area_id"): vol.Any(str, None),   # optionale Area (Benni-Lock: im UI wählbar)
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_helper_create(hass: HomeAssistant, connection, msg) -> None:
    """Nativen HA-Helfer anlegen → Area setzen → direkt aktiv exposen (Benni-Lock: „1 Klick").

    Trennung: helpers.py = native-Helfer-Mechanik (Config-Flow); hier die Orchestrierung
    (Area via Entity-Registry, Aufnahme in den Exposure-Store als added+active)."""
    if not msg["entities"]:
        connection.send_error(msg["id"], "no_entities", "Mindestens eine Quell-Entität wählen.")
        return
    try:
        rec = await helpers.async_create(hass, msg["kind"], msg["name"], msg["entities"],
                                         agg=msg["agg"], mode=msg["mode"])
    except Exception as e:  # noqa: BLE001 — Flow-Fehler → ehrliche WS-Fehlermeldung
        connection.send_error(msg["id"], "create_failed", str(e))
        return
    eid = rec.get("entity_id")
    if eid and msg.get("area_id"):                 # Area auf die Helfer-Entität setzen
        er.async_get(hass).async_update_entity(eid, area_id=msg["area_id"])
    if eid:                                        # „Anlegen & hinzufügen": aktiv in den Store
        await get_store(hass).async_set(eid, {"added": True, "active": True})
        rec["exposed"] = True
    connection.send_result(msg["id"], rec)


@websocket_api.websocket_command({
    vol.Required("type"): "hestia/helper/delete",
    vol.Required("entry_id"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_helper_delete(hass: HomeAssistant, connection, msg) -> None:
    """Helfer-Config-Entry entfernen — inkl. Exposure-Store-Rest (kein Zombie-Record)."""
    eid = helpers.entity_of_entry(hass, msg["entry_id"])   # vor dem Entfernen merken
    try:
        await helpers.async_delete(hass, msg["entry_id"])
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "delete_failed", str(e))
        return
    if eid:   # Helfer-Entität ist weg → Store-Record deaktivieren (Metadaten-Retention sinnlos)
        try:
            await get_store(hass).async_set(eid, {"added": False, "active": False})
        except Exception:  # noqa: BLE001
            pass
    connection.send_result(msg["id"], {"removed": msg["entry_id"]})


# ── Allgemein & Safemode (Config-Entry-Settings — kein Store, HAs eigenes .storage) ──
def _hestia_entry(hass: HomeAssistant):
    """Der (eine) Hestia-Config-Entry. Single-Instance-Integration → erster Eintrag."""
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _settings_view(data) -> dict:
    """Config-Entry-`data` → schlanke Settings-Sicht fürs Panel."""
    return {
        "llama_url": data.get(CONF_LLAMA_URL, ""),
        "loop_depth": data.get(CONF_LOOP_DEPTH, DEFAULT_LOOP_DEPTH),
        "unsafe_mode": data.get(CONF_UNSAFE_MODE, DEFAULT_UNSAFE_MODE),
    }


@websocket_api.websocket_command({vol.Required("type"): "hestia/settings/get"})
@websocket_api.require_admin
@callback
def ws_settings_get(hass: HomeAssistant, connection, msg) -> None:
    """Allgemein-Settings lesen (llama.cpp-Endpunkt, Loop-Tiefe, Safemode)."""
    entry = _hestia_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "no_entry", "Keine Hestia-Konfiguration gefunden.")
        return
    connection.send_result(msg["id"], _settings_view(entry.data))


@websocket_api.websocket_command({
    vol.Required("type"): "hestia/settings/set",
    vol.Optional("llama_url"): str,
    vol.Optional("loop_depth"): vol.All(int, vol.Range(min=1, max=8)),
    vol.Optional("unsafe_mode"): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_settings_set(hass: HomeAssistant, connection, msg) -> None:
    """Allgemein-Settings ins Config-Entry schreiben. `async_update_entry` ersetzt `entry.data`
    in-place → die Conversation-Entity liest sie live (conversation.py Properties), kein Reload."""
    entry = _hestia_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "no_entry", "Keine Hestia-Konfiguration gefunden.")
        return
    new = dict(entry.data)
    if "llama_url" in msg:
        url = msg["llama_url"].strip()
        if not url:
            connection.send_error(msg["id"], "bad_url", "Endpunkt darf nicht leer sein.")
            return
        new[CONF_LLAMA_URL] = url
    if "loop_depth" in msg:
        new[CONF_LOOP_DEPTH] = msg["loop_depth"]
    if "unsafe_mode" in msg:
        new[CONF_UNSAFE_MODE] = msg["unsafe_mode"]
    hass.config_entries.async_update_entry(entry, data=new)
    connection.send_result(msg["id"], _settings_view(new))


# ── Custom-Sätze (roher Router vor dem LLM — sentences.py) ──
@websocket_api.websocket_command({vol.Required("type"): "hestia/sentence/list"})
@websocket_api.require_admin
@callback
def ws_sentence_list(hass: HomeAssistant, connection, msg) -> None:
    """Alle konfigurierten Custom-Sätze (Anlege-Reihenfolge)."""
    connection.send_result(msg["id"], {"sentences": get_sentence_store(hass).all()})


@websocket_api.websocket_command({
    vol.Required("type"): "hestia/sentence/create",
    vol.Required("phrases"): [str],
    vol.Required("target_entity"): str,
    vol.Optional("mode", default="on"): vol.In(MODES),
    vol.Optional("response", default=""): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_sentence_create(hass: HomeAssistant, connection, msg) -> None:
    """Neuen Satz anlegen. Validiert: ≥1 Phrase, Ziel-Entität existiert."""
    phrases = [p.strip() for p in msg["phrases"] if isinstance(p, str) and p.strip()]
    if not phrases:
        connection.send_error(msg["id"], "no_phrases", "Mindestens einen Satz angeben.")
        return
    target = msg["target_entity"].strip()
    if not target or hass.states.get(target) is None:
        connection.send_error(msg["id"], "bad_target", f"Unbekannte Ziel-Entität: {target}")
        return
    if target.split(".")[0] not in SUPPORTED_DOMAINS:   # sonst würde async_fire still no-oppen
        connection.send_error(msg["id"], "bad_domain",
                              f"Diese Geräteart lässt sich (noch) nicht per Satz steuern: {target}")
        return
    rec = await get_sentence_store(hass).async_add(phrases, target, msg["mode"], msg.get("response", ""))
    connection.send_result(msg["id"], rec)


@websocket_api.websocket_command({
    vol.Required("type"): "hestia/sentence/delete",
    vol.Required("sentence_id"): str,   # NICHT `id` — das ist HAs reserviertes WS-Envelope-Feld
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_sentence_delete(hass: HomeAssistant, connection, msg) -> None:
    """Satz löschen (per sentence_id)."""
    sid = msg["sentence_id"]
    if not await get_sentence_store(hass).async_delete(sid):
        connection.send_error(msg["id"], "not_found", "Satz nicht gefunden.")
        return
    connection.send_result(msg["id"], {"removed": sid})


@callback
def async_register(hass: HomeAssistant) -> None:
    """Alle Hestia-WS-Befehle registrieren (idempotent — HA dedupliziert nach type)."""
    websocket_api.async_register_command(hass, ws_list)
    websocket_api.async_register_command(hass, ws_candidates)
    websocket_api.async_register_command(hass, ws_set)
    websocket_api.async_register_command(hass, ws_helper_list)
    websocket_api.async_register_command(hass, ws_helper_create)
    websocket_api.async_register_command(hass, ws_helper_delete)
    websocket_api.async_register_command(hass, ws_settings_get)
    websocket_api.async_register_command(hass, ws_settings_set)
    websocket_api.async_register_command(hass, ws_sentence_list)
    websocket_api.async_register_command(hass, ws_sentence_create)
    websocket_api.async_register_command(hass, ws_sentence_delete)
