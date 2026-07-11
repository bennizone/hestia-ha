"""HA-Registry → hestia_cap.House + Exposure-Set (der native, HA-abhängige Teil).

Baut aus HAs Floor-/Area-/Entity-Registry das kanonische Haus-Modell (das der vendored
Renderer byte-gleich zum Training in den Prompt gießt) UND das Exposure-Set, gegen das der
Executor auflöst.

Exposure-Set (Benni-Lock): EIGENES Mapping pro Entität `{llm_name, aliases[], domain, area,
floor, expose}`. **Quelle = unser Config-Store** (store.py, kuratiert im Panel), NICHT mehr HAs
conversation-Exposure. Membership = `added AND active` (die „hinzugefügt & aktiv"-Regel aus dem
07-10-Lock). Deaktivierte/nicht-hinzugefügte Entitäten fallen raus; Metadaten (llm_name/aliases)
kommen aus dem Store, mit Fallback auf HA-friendly_name / Registry-Aliase.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (area_registry as ar, device_registry as dr,
                                   entity_registry as er, floor_registry as fr)

from . import mapping
from .hestia_cap import House, Area, Entity
from .store import get_store


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


def build_exposure(hass: HomeAssistant) -> dict[str, dict]:
    """entity_id -> {llm_name, aliases, domain, area, floor, expose}. Quelle = Config-Store.

    Membership = `added AND active`. Deaktivierte/nicht-hinzugefügte Records fallen raus. Namen
    aus dem Store (leer → HA-friendly_name), Aliase aus dem Store (leer → Registry-Aliase).
    **Offline-Durchreiche:** aktuell `unavailable`/`disabled` schließt NICHT aus — ein bewusst
    aktives Gerät bleibt dem Modell präsentiert (die Offline-Warnung ist reine UI-Sache)."""
    store = get_store(hass)
    ent_reg = er.async_get(hass)
    area_reg = ar.async_get(hass)
    floor_reg = fr.async_get(hass)
    dev_reg = dr.async_get(hass)

    out: dict[str, dict] = {}
    for eid, srec in store.all_records().items():
        if not (srec["added"] and srec["active"]):
            continue
        entry = ent_reg.async_get(eid)
        if entry is None:        # Entität aus HA verschwunden → nicht auflösbar, überspringen
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
        out[eid] = {
            "llm_name": srec["llm_name"] or _friendly_name(hass, entry),
            "aliases": list(srec["aliases"]) or _aliases(entry),
            "description": (srec.get("description") or "").strip(),  # r3: gerendert (vage Auflösung)
            "domain": eid.split(".")[0],
            "area": area_name,
            "floor": floor_name,
            "expose": True,
            # SERVE-only: WRITE-Mapping-Range (mapping.norm → Tuple|None). Der geteilte Result-Layer
            # liest diesen Key NIE → kein Einfluss aufs Tool-JSON (train==serve bleibt intakt).
            "limit": mapping.norm(srec["limit_min"], srec["limit_max"]),
            # SERVE-only: media_player-Live-Kontext-Eligibility (conversation._live_context liest ihn).
            # Beeinflusst NUR den volatilen „Läuft gerade …"-Schwanz, nicht House/Prompt/Tool-JSON.
            "media_context": srec["media_context"],
        }
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
        ent = Entity(name=rec["llm_name"], domain=rec["domain"], aliases=tuple(rec["aliases"]),
                     description=rec.get("description", ""))
        groups.setdefault((rec["floor"], rec["area"] or ""), []).append(ent)
    areas = [Area(name=area_name, floor=floor,
                  entities=tuple(sorted(ents, key=lambda x: x.name)))
             for (floor, area_name), ents in groups.items()]
    areas.sort(key=lambda a: (a.floor or "￿", a.name))   # kanonisch, floor-los zuletzt
    return House(house_id="ha", areas=areas, timer_capable=timer_capable)
