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


async def owned_ids(hass: HomeAssistant) -> set[str]:
    """Set der entry_ids, die HESTIA selbst angelegt hat."""
    data = await Store(hass, _OWN_VERSION, _OWN_KEY).async_load()
    return set((data or {}).get("entry_ids", []))


async def _own_write(hass: HomeAssistant, ids: set[str]) -> None:
    await Store(hass, _OWN_VERSION, _OWN_KEY).async_save({"entry_ids": sorted(ids)})


def entity_of_entry(hass: HomeAssistant, entry_id: str) -> str | None:
    """entity_id der vom Config-Entry erzeugten (einen) Helfer-Entität, oder None."""
    reg = er.async_get(hass)
    for e in reg.entities.values():
        if e.config_entry_id == entry_id:
            return e.entity_id
    return None


async def async_create(hass: HomeAssistant, kind: str, name: str, entities: list[str],
                       *, agg: str = "mean", mode: str = "any") -> dict:
    """Native Helfer anlegen. kind = 'numeric' | 'binary'. → {entry_id, entity_id, name, kind}.

    numeric: `agg` ∈ NUMERIC_AGG (Default mean). binary: `mode` = 'any' (ODER) | 'all' (UND)."""
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
    entry = result["result"]
    ids = await owned_ids(hass)                  # als Hestia-eigenen Helfer markieren (Ownership)
    ids.add(entry.entry_id)
    await _own_write(hass, ids)
    # Auf die vom Config-Flow erzeugte Entität warten — BOUNDED-Poll statt async_block_till_done():
    # Letzteres kann im WS-Handler-Kontext hängen (Panel-„Lege an…"-Freeze 2026-07-13). Max ~2,5s.
    entity_id = None
    for _ in range(50):
        entity_id = entity_of_entry(hass, entry.entry_id)
        if entity_id:
            break
        await asyncio.sleep(0.05)
    return {"entry_id": entry.entry_id, "entity_id": entity_id,
            "name": entry.title, "kind": kind}


async def list_helpers(hass: HomeAssistant) -> list[dict]:
    """NUR von Hestia angelegte Helfer (min_max/group) → Panel-Zeilen. Fremde HA-Helfer, die der
    Nutzer selbst angelegt hat, bleiben unsichtbar (Ownership-Filter) und damit unantastbar."""
    owned = await owned_ids(hass)
    out = []
    for entry in hass.config_entries.async_entries():
        if entry.domain not in HELPER_DOMAINS or entry.entry_id not in owned:
            continue
        out.append({"entry_id": entry.entry_id, "entity_id": entity_of_entry(hass, entry.entry_id),
                    "name": entry.title, "domain": entry.domain})
    return out


async def async_delete(hass: HomeAssistant, entry_id: str) -> None:
    """Helfer-Config-Entry entfernen (löscht auch die Entität) — NUR wenn Hestia ihn angelegt hat.
    Fremde (Nutzer-)Helfer sind tabu (Safety-Fix 2026-07-13)."""
    ids = await owned_ids(hass)
    if entry_id not in ids:
        raise PermissionError("Helfer wurde nicht von Hestia angelegt — Löschen verweigert.")
    await hass.config_entries.async_remove(entry_id)
    ids.discard(entry_id)
    await _own_write(hass, ids)
