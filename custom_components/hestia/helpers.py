"""Native-HA-Helfer anlegen/auflisten/löschen (READ-Seite Aggregation).

Benni-Lock (2026-07-10): Aggregation = **native HA-Helfer**, kein Executor-Eigenbau. Das Modell
sieht einen normalen Sensor, rechnet/rät nichts. Zwei Sorten (Findings: HELPER_FLOW_FINDINGS.md):
  - **numeric** → `min_max`-Integration (min/max/mean/median über N Sensoren) → „Arbeitszimmer-Temp".
  - **binary**  → `group`→binary_sensor (ODER/UND über binäre) → „Wohnzimmer-Präsenz".

Wir treiben HAs eigene Config-Flows server-seitig (`async_init`/`async_configure`) — dieselben,
die HAs Helfer-UI nutzt (empirisch verifiziert HA 2026.7). Kein `.storage`/YAML-Gebastel.
Der angelegte Helfer ist eine normale HA-Entität → taucht wie jede andere im Exposure-Add-Dialog
auf (Helfer-Anlegen und Exposure bleiben entkoppelt/komponierbar).
"""
from __future__ import annotations

import asyncio
import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

# Config-Entry-Domains „unserer" Helfer (Auflisten/Zuordnen).
HELPER_DOMAINS = ("min_max", "group")

# numeric-Aggregat-Enum (Panel) → `min_max.type`. Auf die sinnvollen Read-Aggregate begrenzt.
NUMERIC_AGG = ("mean", "min", "max", "median")

# ── Ownership-Store: NUR von Hestia angelegte Helfer dürfen gelistet/gelöscht werden ──
# Kritischer Safety-Fix (2026-07-13): früher listete/löschte das Panel ALLE group/min_max-
# Config-Entries — auch die, die der Nutzer selbst in HAs UI angelegt hat → Panel-Bug löschte
# fremde Helfer (light.ambiente, binary_sensor-Fenster-Gruppen). Jetzt merkt sich Hestia die
# eigenen entry_ids; fremde HA-Helfer sind für Panel/Delete unsichtbar und unantastbar.
_OWN_KEY = "hestia.helpers_owned"
_OWN_VERSION = 1

# ── Virtuelle Quellen: climate-Attribut → Template-Sensor-Brücke ──────────────
# HA-`min_max` liest den STATE einer Entität, nie Attribute. climate.* führt seine Temperatur
# aber nur als Attribut (`current_temperature`). Damit man Klima-Ist-Werte in einen Ø/min/max-
# Helfer mischen kann (Benni 2026-07-14), legt Hestia beim Anlegen automatisch einen nativen
# Template-Sensor an, der das Attribut spiegelt, und verdrahtet DESSEN entity_id in den min_max.
# Das Panel kodiert eine virtuelle Quelle als "<climate_eid>::<attribut>".
# unit_kind ∈ {"temperature","humidity"} = SensorDeviceClass (steuert Unit-Validierung im Flow).
CLIMATE_NUMERIC_ATTRS = {
    "current_temperature": ("Ist-Temperatur", "temperature"),
    "current_humidity": ("Ist-Luftfeuchte", "humidity"),
}


def _attr_unit(hass: HomeAssistant, unit_kind: str) -> str | None:
    """Unit für die Brücke — muss zur device_class passen (Flow-`_validate_unit`)."""
    if unit_kind == "temperature":
        return hass.config.units.temperature_unit   # System-Unit (°C/°F) — deckt sich mit Sensoren
    if unit_kind == "humidity":
        return "%"
    return None


async def owned_ids(hass: HomeAssistant) -> set[str]:
    """Set der entry_ids, die HESTIA selbst angelegt hat (inkl. Template-Brücken)."""
    ids, _ = await _own_load(hass)
    return ids


async def _own_load(hass: HomeAssistant) -> tuple[set[str], dict[str, list[str]]]:
    """(owned entry_ids, deps: parent_entry_id → [brücken_entry_id]). deps steuert Cascade-Delete."""
    data = await Store(hass, _OWN_VERSION, _OWN_KEY).async_load() or {}
    return set(data.get("entry_ids", [])), dict(data.get("deps", {}))


async def _own_save(hass: HomeAssistant, ids: set[str], deps: dict[str, list[str]]) -> None:
    await Store(hass, _OWN_VERSION, _OWN_KEY).async_save(
        {"entry_ids": sorted(ids), "deps": {k: v for k, v in deps.items() if v}})


def entity_of_entry(hass: HomeAssistant, entry_id: str) -> str | None:
    """entity_id der vom Config-Entry erzeugten (einen) Helfer-Entität, oder None."""
    reg = er.async_get(hass)
    for e in reg.entities.values():
        if e.config_entry_id == entry_id:
            return e.entity_id
    return None


# State-Template einer Brücke → (source_eid, attribut) rückwärts lesen. Muss zum in
# `_create_template_bridge` geschriebenen `{{ state_attr('<eid>', '<attr>') }}` passen.
_STATE_ATTR_RE = re.compile(
    r"state_attr\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)")


def _bridge_source_key(hass: HomeAssistant, bridge_id: str) -> str | None:
    """`<source_eid>::<attribut>` einer Template-Brücke aus ihrem State-Template rekonstruieren
    (für Edit-Vorbefüllung + Reuse beim Update), oder None wenn nicht auflösbar."""
    entry = hass.config_entries.async_get_entry(bridge_id)
    if entry is None:
        return None
    tmpl = (entry.options or {}).get("state") or (entry.data or {}).get("state") or ""
    m = _STATE_ATTR_RE.search(tmpl)
    return f"{m.group(1)}::{m.group(2)}" if m else None


async def _await_entity(hass: HomeAssistant, entry_id: str) -> str | None:
    """Auf die vom Config-Flow erzeugte Entität warten — BOUNDED-Poll statt async_block_till_done():
    Letzteres kann im WS-Handler-Kontext hängen (Panel-„Lege an…"-Freeze 2026-07-13). Max ~2,5s."""
    for _ in range(50):
        eid = entity_of_entry(hass, entry_id)
        if eid:
            return eid
        await asyncio.sleep(0.05)
    return None


async def _create_template_bridge(hass: HomeAssistant, source_eid: str, attribute: str) -> tuple[str, str]:
    """Nativen Template-Sensor anlegen, der `attribute` von `source_eid` spiegelt → (entry_id, entity_id).

    Treibt HAs eigenen `template`-Config-Flow (sensor-Step, HA 2026.7) — kein YAML/.storage.
    Nötig, weil `min_max` nur States liest; siehe CLIMATE_NUMERIC_ATTRS."""
    if attribute not in CLIMATE_NUMERIC_ATTRS:
        raise ValueError(f"nicht-brückbares Attribut: {attribute}")
    label, unit_kind = CLIMATE_NUMERIC_ATTRS[attribute]
    src = hass.states.get(source_eid)
    src_name = (src.attributes.get("friendly_name") if src else None) or source_eid
    opts = {
        "name": f"{src_name} · {label}",
        "state": f"{{{{ state_attr('{source_eid}', '{attribute}') }}}}",
        "device_class": unit_kind,
        "state_class": "measurement",
    }
    unit = _attr_unit(hass, unit_kind)
    if unit:
        opts["unit_of_measurement"] = unit
    flow = await hass.config_entries.flow.async_init("template", context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"next_step_id": "sensor"})
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], opts)
    if result.get("type") != "create_entry":
        raise RuntimeError(
            f"Template-Brücke-Flow legte keinen Eintrag an: {result.get('type')} {result.get('errors')}")
    entry = result["result"]
    eid = await _await_entity(hass, entry.entry_id)
    if not eid:
        raise RuntimeError(f"Template-Brücke ohne Entität: {source_eid}::{attribute}")
    return entry.entry_id, eid


async def async_create(hass: HomeAssistant, kind: str, name: str, entities: list[str],
                       *, agg: str = "mean", mode: str = "any") -> dict:
    """Native Helfer anlegen. kind = 'numeric' | 'binary'. → {entry_id, entity_id, name, kind}.

    numeric: `agg` ∈ NUMERIC_AGG (Default mean). binary: `mode` = 'any' (ODER) | 'all' (UND).

    Virtuelle Quellen "<climate_eid>::<attribut>" (nur numeric) → automatische Template-Brücke,
    deren entity_id in den min_max wandert. Brücken werden als deps[parent] getrackt (Cascade-Delete)."""
    # Virtuelle climate-Attribut-Quellen zuerst in echte (Brücken-)Entitäten auflösen.
    bridges: list[str] = []   # entry_ids der angelegten Template-Brücken → Cascade-Abhängigkeit
    resolved: list[str] = []
    try:
        for e in entities:
            src_eid, sep, attr = e.partition("::")
            if sep:
                b_entry, b_eid = await _create_template_bridge(hass, src_eid, attr)
                bridges.append(b_entry)
                resolved.append(b_eid)
            else:
                resolved.append(e)
    except Exception:
        for b in bridges:   # Teil-Anlage zurückrollen → keine verwaisten Brücken
            try:
                await hass.config_entries.async_remove(b)
            except Exception:  # noqa: BLE001
                pass
        raise
    entities = resolved

    try:
        if kind == "numeric":
            agg = agg if agg in NUMERIC_AGG else "mean"
            flow = await hass.config_entries.flow.async_init("min_max", context={"source": "user"})
            result = await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                {"name": name, "entity_ids": entities, "type": agg, "round_digits": 1},
            )
        elif kind == "binary":
            flow = await hass.config_entries.flow.async_init("group", context={"source": "user"})
            flow = await hass.config_entries.flow.async_configure(   # Menü → binary_sensor
                flow["flow_id"], {"next_step_id": "binary_sensor"})
            result = await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                {"name": name, "entities": entities, "hide_members": False, "all": (mode == "all")},
            )
        else:
            raise ValueError(f"unbekannte Helfer-Sorte: {kind}")

        if result.get("type") != "create_entry":
            raise RuntimeError(
                f"Helfer-Flow legte keinen Eintrag an: {result.get('type')} {result.get('errors')}")
    except Exception:
        for b in bridges:   # min_max/group-Flow scheiterte → schon angelegte Brücken zurückrollen
            try:
                await hass.config_entries.async_remove(b)
            except Exception:  # noqa: BLE001
                pass
        raise

    entry = result["result"]
    ids, deps = await _own_load(hass)            # als Hestia-eigenen Helfer markieren (Ownership)
    ids.add(entry.entry_id)
    ids.update(bridges)                          # Brücken sind ebenfalls Hestia-eigen (aber unsichtbar: kein HELPER_DOMAIN)
    if bridges:
        deps[entry.entry_id] = sorted(bridges)   # Cascade: beim Löschen des Helfers mit-entfernen
    await _own_save(hass, ids, deps)
    entity_id = await _await_entity(hass, entry.entry_id)
    return {"entry_id": entry.entry_id, "entity_id": entity_id,
            "name": entry.title, "kind": kind}


def _helper_row(hass: HomeAssistant, entry, deps: dict[str, list[str]], reg) -> dict:
    """Config-Entry → Panel-Zeile inkl. editierbarer Felder (kind/agg/mode/sources/area_id).
    Brücken-Entitäten werden für die Anzeige zurück auf "<source_eid>::<attr>" abgebildet, damit
    der Edit-Dialog die virtuelle Quelle zeigt (nicht die interne Template-Brücke)."""
    reg_ent = next((e for e in reg.entities.values() if e.config_entry_id == entry.entry_id), None)
    opts = {**(entry.data or {}), **(entry.options or {})}
    bmap = {}                                   # Brücken-entity_id → "<source_eid>::<attr>"
    for b in deps.get(entry.entry_id, []):
        beid = entity_of_entry(hass, b)
        key = _bridge_source_key(hass, b)
        if beid and key:
            bmap[beid] = key
    if entry.domain == "min_max":
        raw = list(opts.get("entity_ids") or [])
        agg = opts.get("type", "mean")
        kind, agg, mode = "numeric", (agg if agg in NUMERIC_AGG else "mean"), "any"
    else:                                       # group (binär)
        raw = list(opts.get("entities") or [])
        kind, agg, mode = "binary", "mean", ("all" if opts.get("all") else "any")
    return {
        "entry_id": entry.entry_id,
        "entity_id": reg_ent.entity_id if reg_ent else None,
        "name": entry.title,
        "domain": entry.domain,
        "kind": kind,
        "agg": agg,
        "mode": mode,
        "sources": [bmap.get(x, x) for x in raw],
        "area_id": reg_ent.area_id if reg_ent else None,
    }


async def list_helpers(hass: HomeAssistant) -> list[dict]:
    """NUR von Hestia angelegte Helfer (min_max/group) → Panel-Zeilen. Fremde HA-Helfer, die der
    Nutzer selbst angelegt hat, bleiben unsichtbar (Ownership-Filter) und damit unantastbar."""
    owned, deps = await _own_load(hass)
    reg = er.async_get(hass)
    out = []
    for entry in hass.config_entries.async_entries():
        if entry.domain not in HELPER_DOMAINS or entry.entry_id not in owned:
            continue
        out.append(_helper_row(hass, entry, deps, reg))
    return out


async def async_delete(hass: HomeAssistant, entry_id: str) -> None:
    """Helfer-Config-Entry entfernen (löscht auch die Entität) — NUR wenn Hestia ihn angelegt hat.
    Fremde (Nutzer-)Helfer sind tabu (Safety-Fix 2026-07-13)."""
    ids, deps = await _own_load(hass)
    if entry_id not in ids:
        raise PermissionError("Helfer wurde nicht von Hestia angelegt — Löschen verweigert.")
    await hass.config_entries.async_remove(entry_id)
    ids.discard(entry_id)
    for b in deps.pop(entry_id, []):   # Cascade: zugehörige Template-Brücken mit-entfernen (kein Orphan)
        if b in ids:
            try:
                await hass.config_entries.async_remove(b)
            except Exception:  # noqa: BLE001
                pass
            ids.discard(b)
    await _own_save(hass, ids, deps)


async def async_update(hass: HomeAssistant, entry_id: str, *, name: str, entities: list[str],
                       agg: str = "mean", mode: str = "any") -> dict:
    """Bestehenden Helfer editieren — NUR wenn Hestia ihn angelegt hat (Ownership wie async_delete).

    Reconciled die virtuellen climate-Attribut-Brücken: neue "<eid>::<attr>"-Quellen bekommen eine
    Brücke, weggefallene werden entfernt, unveränderte wiederverwendet (kein entity_id-Churn). Danach
    die min_max/group-Optionen neu schreiben + reloaden. → {entry_id, entity_id, name, kind}."""
    ids, deps = await _own_load(hass)
    if entry_id not in ids:
        raise PermissionError("Helfer wurde nicht von Hestia angelegt — Bearbeiten verweigert.")
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain not in HELPER_DOMAINS:
        raise ValueError("Kein editierbarer Hestia-Helfer.")

    old_bridges = list(deps.get(entry_id, []))
    reuse: dict[str, tuple[str, str | None]] = {}    # "<eid>::<attr>" → (bridge_entry_id, bridge_entity_id)
    for b in old_bridges:
        key = _bridge_source_key(hass, b)
        if key:
            reuse[key] = (b, entity_of_entry(hass, b))

    new_bridges: list[str] = []      # frisch angelegt → Rollback bei Fehler
    kept_bridges: list[str] = []     # nach dem Update bestehende Brücken (wiederverwendet + neu)
    resolved: list[str] = []
    try:
        for e in entities:
            src_eid, sep, attr = e.partition("::")
            if not sep:
                resolved.append(e)
                continue
            hit = reuse.get(e)
            if hit and hit[1]:                       # Brücke existiert + hat Entität → wiederverwenden
                kept_bridges.append(hit[0])
                resolved.append(hit[1])
            else:
                b_entry, b_eid = await _create_template_bridge(hass, src_eid, attr)
                new_bridges.append(b_entry)
                kept_bridges.append(b_entry)
                resolved.append(b_eid)
    except Exception:
        for b in new_bridges:   # Teil-Anlage zurückrollen → keine verwaisten Brücken
            try:
                await hass.config_entries.async_remove(b)
            except Exception:  # noqa: BLE001
                pass
        raise

    opts = dict(entry.options or {})     # integration-interne Keys (group_type/round_digits) erhalten
    if entry.domain == "min_max":
        opts.update({"entity_ids": resolved, "type": agg if agg in NUMERIC_AGG else "mean",
                     "round_digits": opts.get("round_digits", 1)})
    else:                                 # group (binär)
        opts.update({"entities": resolved, "all": (mode == "all"), "hide_members": False})
    try:
        hass.config_entries.async_update_entry(entry, title=name, options=opts)
        await hass.config_entries.async_reload(entry_id)
    except Exception:
        for b in new_bridges:   # Update scheiterte → schon angelegte Brücken zurückrollen
            try:
                await hass.config_entries.async_remove(b)
            except Exception:  # noqa: BLE001
                pass
        raise

    for b in old_bridges:                 # nicht wiederverwendete Brücken sind jetzt verwaist
        if b not in kept_bridges:
            try:
                await hass.config_entries.async_remove(b)
            except Exception:  # noqa: BLE001
                pass
            ids.discard(b)
    ids.update(new_bridges)
    if kept_bridges:
        deps[entry_id] = sorted(kept_bridges)
    else:
        deps.pop(entry_id, None)
    await _own_save(hass, ids, deps)
    return {"entry_id": entry_id, "entity_id": entity_of_entry(hass, entry_id),
            "name": name, "kind": "numeric" if entry.domain == "min_max" else "binary"}
