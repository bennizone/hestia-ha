"""Kanonisches Haus-Modell (HA-frei, dep-frei) — Input für den Renderer (B2).

**HA-nativ geformt** (Etage → Raum → Gerät), weil die v23-Daten aus HAs Floor-/Area-/
Entity-Registry kommen (Addon-Introspektion). Das ermöglicht Floor-Targeting
(`get_state(floor=…)`), das v22 blind war. Fällt graceful auf flach zurück, wenn
kein Raum→Etage-Mapping vorliegt (z.B. alte v22-Fixtures).

Reihenfolge KANONISCH (sortiert) → gleiche Semantik ⇒ gleicher String ⇒ Prefix-Cache.
"""
from __future__ import annotations
from dataclasses import dataclass, field

UNGROUPED = None  # Areas ohne Etagen-Zuordnung


@dataclass(frozen=True)
class Entity:
    name: str            # kanonischer Anzeigename
    domain: str
    aliases: tuple = ()  # weitere Namen (Resolver-Grounding + ab r3 gerendert „auch: …")
    description: str = ""  # freitext-Zweck-Hinweis (ab r3 gerendert; vage/umschreibende Auflösung)
    # v23.5 Phase 4 (Cap-Haus): geräte-echtes Capability-Profil (supported_color_modes/hvac_modes/
    # min_temp/effect_list/preset_modes/options/…) + optionaler synth. `state`. Speist NICHT den
    # Renderer (Prompt bleibt schlank), sondern NUR den Sim-State-Store (states_from_house) →
    # capabilities_of → plan_set_state (train==serve). Leer ⇒ caps=None ⇒ konservativer Fallback.
    attributes: dict = field(default_factory=dict)
    state: str = ""


@dataclass(frozen=True)
class Area:
    name: str
    floor: str | None = None
    entities: tuple = ()   # kanonisch sortiert nach name


@dataclass
class House:
    house_id: str
    areas: list          # list[Area], kanonisch sortiert nach (floor, name)
    timer_capable: bool = False

    @staticmethod
    def from_dict(d: dict) -> "House":
        """Akzeptiert zwei Formen:
        (a) HA-nativ: {"floors":[{"name","areas":[{"name","entities":[{"name"/"names","domain"}]}]}],
                       "areas_without_floor":[...], "timer_capable"}
        (b) flach (v22): {"areas":[namen], "floors":[namen], "entities":[{"names","domain","areas"}]}
        """
        if "floors" in d and d["floors"] and isinstance(d["floors"][0], dict):
            return House._from_ha_native(d)
        return House._from_flat(d)

    @staticmethod
    def _mk_entity(e: dict) -> Entity:
        names = e.get("names") or ([e["name"]] if e.get("name") else [])
        return Entity(name=names[0], domain=e.get("domain", ""), aliases=tuple(names[1:]),
                      description=(e.get("description") or "").strip(),
                      attributes=dict(e.get("attributes") or {}), state=str(e.get("state") or ""))

    @staticmethod
    def _mk_area(name: str, floor: str | None, ents: list) -> Area:
        es = tuple(sorted((House._mk_entity(e) for e in ents), key=lambda x: x.name))
        return Area(name=name, floor=floor, entities=es)

    @staticmethod
    def _from_ha_native(d: dict) -> "House":
        areas = []
        for fl in d.get("floors", []):
            for a in fl.get("areas", []):
                areas.append(House._mk_area(a["name"], fl.get("name"), a.get("entities", [])))
        for a in d.get("areas_without_floor", []):
            areas.append(House._mk_area(a["name"], UNGROUPED, a.get("entities", [])))
        areas.sort(key=lambda a: (a.floor or "￿", a.name))
        return House(house_id=d.get("house_id", ""), areas=areas,
                     timer_capable=bool(d.get("timer_capable", False)))

    @staticmethod
    def _from_flat(d: dict) -> "House":
        # v22: kein Raum→Etage-Mapping → alle Areas ungrouped; Entities nach areas gruppieren.
        by_area: dict = {}
        for e in d.get("entities", []):
            names = e.get("names") or ([e["name"]] if e.get("name") else [])
            if not names:
                continue
            area = e.get("areas") or e.get("area") or ""
            if isinstance(area, list):
                area = area[0] if area else ""
            by_area.setdefault(area, []).append(e)
        names = set(d.get("areas") or []) | set(by_area)
        areas = [House._mk_area(n, UNGROUPED, by_area.get(n, [])) for n in names]
        areas.sort(key=lambda a: a.name)
        return House(house_id=d.get("house_id", ""), areas=areas,
                     timer_capable=bool(d.get("timer_capable", False)))

    # ── Zugriff ───────────────────────────────────────────────────────────
    @property
    def floors(self) -> list:
        return sorted({a.floor for a in self.areas if a.floor is not None})

    @property
    def has_floor_mapping(self) -> bool:
        return any(a.floor is not None for a in self.areas)

    def all_entities(self) -> list:
        return [e for a in self.areas for e in a.entities]
