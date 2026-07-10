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

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

# Config-Entry-Domains „unserer" Helfer (Auflisten/Zuordnen).
HELPER_DOMAINS = ("min_max", "group")

# numeric-Aggregat-Enum (Panel) → `min_max.type`. Auf die sinnvollen Read-Aggregate begrenzt.
NUMERIC_AGG = ("mean", "min", "max", "median")


def _entity_of_entry(hass: HomeAssistant, entry_id: str) -> str | None:
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
    await hass.async_block_till_done()          # Setup abwarten → Entität existiert in der Registry
    return {"entry_id": entry.entry_id, "entity_id": _entity_of_entry(hass, entry.entry_id),
            "name": entry.title, "kind": kind}


def list_helpers(hass: HomeAssistant) -> list[dict]:
    """Von uns verwaltbare Helfer (min_max/group-Config-Entries) → Panel-Zeilen."""
    out = []
    for entry in hass.config_entries.async_entries():
        if entry.domain not in HELPER_DOMAINS:
            continue
        out.append({"entry_id": entry.entry_id, "entity_id": _entity_of_entry(hass, entry.entry_id),
                    "name": entry.title, "domain": entry.domain})
    return out


async def async_delete(hass: HomeAssistant, entry_id: str) -> None:
    """Helfer-Config-Entry entfernen (löscht auch die Entität)."""
    await hass.config_entries.async_remove(entry_id)
