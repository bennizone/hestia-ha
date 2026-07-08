"""HA-Registry → hestia_cap.House + Exposure-Set (der native, HA-abhängige Teil).

Baut aus HAs Floor-/Area-/Entity-Registry das kanonische Haus-Modell (das der vendored
Renderer byte-gleich zum Training in den Prompt gießt) UND das Exposure-Set, gegen das der
Executor auflöst.

Exposure-Set (Benni-Lock): EIGENES Mapping pro Entität `{llm_name, aliases[], domain, area,
floor, expose}`. MVP-Seed: Membership = HAs conversation-Exposure (kuratierbar später, F1),
llm_name = friendly_name, aliases = Registry-Aliase. Ein optionales Override-Dict aus der
Config (CONF_EXPOSURE) darf einzelne Felder/expose überschreiben.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_get_entity_settings
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (area_registry as ar, device_registry as dr,
                                   entity_registry as er, floor_registry as fr)

from .hestia_cap import House, Area, Entity


def _explicitly_exposed(hass: HomeAssistant, entity_id: str) -> bool:
    """Nur EXPLIZITE conversation-Opt-ins (ignoriert HAs breite Domain-Defaults).

    HAs `async_should_expose` würde default-exposed Domains (light/switch/…) fleet-weit
    einblenden → 100+-Entitäten-Prompt, den das kompakte LLM nicht sauber trägt. Wir bauen
    ein EIGENES, kuratiertes Set (Benni-Lock) und nehmen darum nur, was der Nutzer bewusst
    exponiert hat. Config-Override (CONF_EXPOSURE) kann zusätzlich `expose` setzen."""
    try:
        settings = async_get_entity_settings(hass, entity_id)
    except HomeAssistantError:
        return False
    return bool(settings.get(conversation.DOMAIN, {}).get("should_expose"))


def _friendly_name(hass: HomeAssistant, entry) -> str:
    """Bester Anzeigename: State-friendly_name > Registry-Name > original_name > entity_id."""
    st = hass.states.get(entry.entity_id)
    if st:
        fn = st.attributes.get("friendly_name")
        if fn:
            return fn
    return entry.name or entry.original_name or entry.entity_id


def _aliases(entry) -> list[str]:
    """Nur String-Aliase (Registry-Feld ist `str | ComputedNameType`)."""
    return [a for a in getattr(entry, "aliases", ()) if isinstance(a, str) and a.strip()]


def _entity_area_id(entry, dev_reg) -> str | None:
    """Area der Entität: direkt gesetzt, sonst über das Gerät."""
    if entry.area_id:
        return entry.area_id
    if entry.device_id:
        dev = dev_reg.async_get(entry.device_id)
        if dev:
            return dev.area_id
    return None


def build_exposure(hass: HomeAssistant, override: dict | None = None) -> dict[str, dict]:
    """entity_id -> {llm_name, aliases, domain, area, floor, expose}. Nur expose==True landet
    im Haus/Resolver. `override` (CONF_EXPOSURE) darf Felder pro entity_id überschreiben."""
    ent_reg = er.async_get(hass)
    area_reg = ar.async_get(hass)
    floor_reg = fr.async_get(hass)
    dev_reg = dr.async_get(hass)
    override = override or {}

    out: dict[str, dict] = {}
    for entry in ent_reg.entities.values():
        if entry.hidden_by is not None or entry.disabled:
            continue
        if not _explicitly_exposed(hass, entry.entity_id):
            continue
        area_id = _entity_area_id(entry, dev_reg)
        area_name = floor_name = None
        if area_id:
            area = area_reg.async_get_area(area_id)
            if area:
                area_name = area.name
                if area.floor_id:
                    fl = floor_reg.async_get_floor(area.floor_id)
                    floor_name = fl.name if fl else None
        rec = {
            "llm_name": _friendly_name(hass, entry),
            "aliases": _aliases(entry),
            "domain": entry.entity_id.split(".")[0],
            "area": area_name,
            "floor": floor_name,
            "expose": True,
        }
        ov = override.get(entry.entity_id)
        if isinstance(ov, dict):
            rec.update({k: v for k, v in ov.items() if k in rec})
        if rec["expose"]:
            out[entry.entity_id] = rec
    return out


def build_house(hass: HomeAssistant, exposure: dict[str, dict],
                timer_capable: bool = False) -> House:
    """Exposure-Set → hestia_cap.House (HA-nativ hierarchisch: Etage→Raum→Gerät).

    Baut Area/Entity DIREKT (nicht über House.from_dict): from_dict routet bei leerem
    `floors` zum Flat-Parser, der `areas_without_floor` nicht kennt → leeres Haus, wenn
    KEINE Etagen zugeordnet sind (häufig). Direktbau ist eindeutig und floor-robust; die
    Sortier-Semantik entspricht _from_ha_native (→ prefix-cache-stabil)."""
    groups: dict[tuple, list] = {}   # (floor, area_name) -> [Entity]
    for rec in exposure.values():
        ent = Entity(name=rec["llm_name"], domain=rec["domain"], aliases=tuple(rec["aliases"]))
        groups.setdefault((rec["floor"], rec["area"] or ""), []).append(ent)
    areas = [Area(name=area_name, floor=floor,
                  entities=tuple(sorted(ents, key=lambda x: x.name)))
             for (floor, area_name), ents in groups.items()]
    areas.sort(key=lambda a: (a.floor or "￿", a.name))   # kanonisch, floor-los zuletzt
    return House(house_id="ha", areas=areas, timer_capable=timer_capable)
