"""cap-v1 Renderer (B2) — Haus-Config → deterministischer Prompt-String.

DIE train==serve-Naht: Generator (Trainings-Gold) UND Addon (Serving) rufen
DIESELBE Funktion → byte-identischer statischer Prefix ⇒ Prefix-Cache trägt,
kein Divergenz-Bug (FM2). Reimplementieren = Bug per Definition.

Layout (FROZEN, A3): statischer Prefix [Instruktionen · Haus] zuerst, ALLE Tools
statisch (via tooldefs), volatiler Schwanz (User-Turn) zuletzt. **Zeit NICHT hier**
(GetLiveContext-Schwanz). HA-nativ hierarchisch (Etage → Raum → Gerät) wenn
Floor-Mapping vorliegt, sonst flach.
"""
from __future__ import annotations
from .captag import cap_tag
from .house import House
from .tooldefs import all_tool_defs

RENDER_VERSION = "r8"  # r8 = Zeitsteuerung via optionalem `when` an Aktions-Verben (turn_on/off/set_state/adjust/stop); set_timer wieder reiner Timer (v23.9, v23.7-do_verb verworfen); r7 = set_timer+do_verb (v23.7); r6 = Batch1b Growth-Domains; r5 = Cap-Tags +select/climate-fan+swing; r4 = Cap-Tags im [domain]-Token; r3 = Aliase+Beschreibung; r2 = HA-native

INSTRUCTIONS = (
    "Du bist Hestia, der Sprachassistent für dieses Smart Home. Wandle die Nutzer-Anfrage in eine "
    "Liste von Tool-Calls (1..n Aktionen) um ODER antworte in freiem Text — nie beides gemischt. "
    "Freier Text ist für Smalltalk/Identität, für Rückfragen bei Mehrdeutigkeit (mit Auswahl, endet auf „?“) "
    "und wenn keine Aktion möglich ist. Nach einem Tool-Call bekommst du das Ergebnis als JSON zurück; "
    "antworte dann kurz und geerdet (nenne nur, was wirklich passiert ist — bei Fehlern ehrlich). "
    "Absolut vs. relativ steckt im Verb (set_state vs. adjust). Nutze Eigennamen wortwörtlich."
)


def _entity_token(e) -> str:
    """Ein Gerät im Haus-Block. r4: Cap-Tag im `[domain…]`-Token (captag.py) — Fähigkeiten fürs Modell.
    r3: Aliase („auch: …") + Beschreibung. Ohne Attribute+Extras byte-identisch zu r3 (leerer Tag)."""
    tok = f"{e.name}[{e.domain}{cap_tag(e.domain, getattr(e, 'attributes', None))}]"
    if e.aliases:
        tok += " (auch: " + ", ".join(e.aliases) + ")"
    if getattr(e, "description", ""):
        tok += f" – „{e.description}“"
    return tok


def _area_line(area) -> str:
    name = area.name or "Ohne Raum"   # globale Entitäten (Schlösser/Wetter) ohne Area
    if area.entities:
        devs = ", ".join(_entity_token(e) for e in area.entities)
        return f"- {name}: {devs}"
    return f"- {name}: (keine Geräte)"


def render_house(house: House) -> str:
    """Deterministischer Haus-Block. Hierarchisch nach Etage, wenn Mapping da; sonst flach."""
    lines = []
    if house.has_floor_mapping:
        # nach Etage gruppieren (Etagen sortiert), Areas je Etage sortiert, floor-lose zuletzt
        floors = house.floors + ([None] if any(a.floor is None for a in house.areas) else [])
        for fl in floors:
            header = fl if fl is not None else "Ohne Etage"
            lines.append(f"{header}:")
            for area in [a for a in house.areas if a.floor == fl]:  # areas kanonisch vorsortiert
                lines.append(_area_line(area))
    else:
        lines.append("Räume und Geräte:")
        for area in house.areas:
            lines.append(_area_line(area))
    lines.append("Timer verfügbar: " + ("ja" if house.timer_capable else "nein") + ".")
    return "\n".join(lines)


def render_system_content(house: House) -> str:
    """Kompletter statischer System-Content (cachebarer Prefix, ohne Tools/Zeit)."""
    return INSTRUCTIONS + "\n\n" + render_house(house)


def build_messages(house: House, user_utterance: str) -> tuple[list, list]:
    """(messages, tools) — bereit fürs LFM-Chat-Template (gepinnt). Parität via B3-Harness."""
    return (
        [{"role": "system", "content": render_system_content(house)},
         {"role": "user", "content": user_utterance}],
        all_tool_defs(),
    )
