"""cap-v1 Tool-Definitionen (JSON-Schema) — GENERIERT aus schema.py.

Das ist die Form, in der das LFM die Tools im System-Prompt sieht (via nativem
apply_chat_template(tools=...)). Beschreibungen = Prompt-Tuning-Fläche (serve-seitig),
Struktur/Enums kommen aus der Single-Source. Kein Handpflegen der Parameter.
"""
from __future__ import annotations
from .schema import VERBS, TARGET_PARAMS, SETTABLE_ATTRS

# Menschliche Beschreibungen (Prompt-Fläche; DE, LFM-anchored). Nur Prosa, keine Struktur.
DESCRIPTIONS = {
    "turn_on":  "Schaltet ein Gerät oder eine Gruppe EIN (an/einschalten/anmachen/aktivieren).",
    "turn_off": "Schaltet ein Gerät oder eine Gruppe AUS (aus/ausschalten/ausmachen/deaktivieren).",
    "set_state": "Setzt eine Eigenschaft auf einen ABSOLUTEN Wert (z.B. Helligkeit auf 30%, Heizung auf 21 Grad).",
    "adjust":   "Ändert eine Eigenschaft RELATIV (heller/dunkler, wärmer/kälter, lauter/leiser, hoch/runter).",
    "get_state": "Fragt den Zustand ab oder aggregiert über mehrere Geräte (z.B. 'ist noch Licht an?', 'sind alle Fenster zu?').",
    "run_routine": "Startet eine benannte Szene, Skript oder Routine.",
    "set_timer": "Setzt, bricht ab, verlängert/verkürzt, pausiert/setzt fort oder fragt einen Timer/Wecker ab.",
    "control_media": "Steuert Medien-Wiedergabe (Play/Pause/Nächster/Stop/Inhalt abspielen/stumm).",
    "announce": "Sagt eine Durchsage/Nachricht an (Broadcast an alle oder an einen Raum).",
    "manage_list": "Verwaltet eine Einkaufs-/To-do-Liste (Eintrag hinzufügen/entfernen/abhaken).",
    "control_vacuum": "Steuert den Staubsauger-Roboter (starten, zur Basis zurück, Bereich reinigen).",
    "stop": "Hält eine laufende Bewegung an (Rollladen/Jalousie stoppen, Roboter anhalten).",
    # cap-v2: ask/decline/respond gestrichen — Rückfrage/Ablehnung/Smalltalk laufen als freier Antworttext.
}
PARAM_DESC = {
    "value": "Zahl (Skalar), 'max', 'min' oder Farbwort — Typ folgt aus attribute.",
    "duration": "z.B. '10min', '1h30min' (bei set/add/subtract).",
    "name": "Eigenname der Entität/Routine/Liste, wortwörtlich aus der Äusserung.",
    "content": "Titel/Sender/Playlist bei play_content.",
    "message": "Die Durchsage-Nachricht in natürlicher Sprache.",
    "item": "Der Listen-Eintrag (z.B. 'Milch').",
}


def _prop(spec: dict) -> dict:
    t = spec["type"]
    if t == "enum":
        p = {"type": "string", "enum": list(spec["values"])}
    elif t == "value":
        p = {"type": "string"}  # Wert-Grammatik hart via GBNF; hier nur Typ-Hinweis
    else:
        p = {"type": "string"}
    return p


def tool_def(verb: str) -> dict:
    spec = VERBS[verb]
    props: dict = {}
    if spec["target"]:
        for k, ks in TARGET_PARAMS.items():
            props[k] = _prop(ks)
    for k, ks in spec["params"].items():
        props[k] = _prop(ks)
        if k in PARAM_DESC:
            props[k]["description"] = PARAM_DESC[k]
    return {
        "name": verb,
        "description": DESCRIPTIONS[verb],
        "parameters": {"type": "object", "properties": props, "required": list(spec["required"])},
    }


def all_tool_defs() -> list[dict]:
    """Alle ~10 Verben als JSON-Tool-Defs, in Schema-Reihenfolge (statisch, kein Domain-Gating)."""
    return [tool_def(v) for v in VERBS]
