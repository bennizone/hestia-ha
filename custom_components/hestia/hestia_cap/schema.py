"""cap-v2 — Single Source of Truth (Loop-Architektur, 2026-07-08).

HA-frei, dependency-frei. DIE eine Quelle für Verben/Enums/Wert-Grammatik.
Generator + Bench + Addon importieren dies; GBNF, Parser und Tool-Defs werden
HIERAUS generiert (nie handgepflegt → sonst stille Drift, FM2).

Kontrakt-Referenz: homelab-admin/hestia/v23/LOOP_ARCH_DESIGN.md (Delta cap-v1→cap-v2 §2).
**cap-v2-Delta:** Dialog-Pseudo-Verben (ask/decline/respond) GESTRICHEN → freier Antworttext
im Loop (kein Tool-Block). Aktions-Verben unverändert. Prototyp/grüne Wiese (kein sakrosankter
Freeze mehr, Benni 2026-07-08); Änderungen bewusst + dokumentiert.
"""
from __future__ import annotations

CAP_VERSION = "cap-v2"

# ── Wire-Wrapper (LFM-nativ, empirisch A2) ────────────────────────────────
TOOL_CALL_START = "<|tool_call_start|>"
TOOL_CALL_END = "<|tool_call_end|>"

# ── Geteilter Ziel-Block (jeder Aktions-/Abfrage-Verb, alle optional) ─────
REF_VALUES = ("it", "here", "there", "last")
TARGET_PARAMS = {
    "name":   {"type": "str"},   # Eigenname verbatim
    "area":   {"type": "str"},
    "floor":  {"type": "str"},
    "domain": {"type": "str"},   # light|switch|climate|cover|fan|lock|media_player|sensor|...
    "ref":    {"type": "enum", "values": REF_VALUES},
}

# ── Attribute + Wert-Domänen ──────────────────────────────────────────────
# kind steuert Wert-Grammatik (GBNF) + Parser-Validierung + Executor-Mapping.
#   pct        : 0..100 | "max" | "min"
#   number     : Zahl (z.B. Grad)
#   colorword  : Farbwort-Enum
#   colortemp  : "warm" | "cool" | Kelvin-Zahl
SETTABLE_ATTRS = {
    "brightness": {"kind": "pct"},
    "volume":     {"kind": "pct"},
    "position":   {"kind": "pct"},
    "fan_speed":  {"kind": "pct"},
    "temperature": {"kind": "number"},
    "color":      {"kind": "colorword"},
    "color_temp": {"kind": "colortemp"},
}
ADJUSTABLE_ATTRS = ("brightness", "volume", "temperature", "position", "fan_speed", "color_temp")
GET_ATTRS = ("state", "brightness", "temperature", "position", "open", "datetime")  # +datetime (additiv, GetDateTime)
COLOR_WORDS = ("warm_white", "cold_white", "white", "red", "green", "blue",
               "yellow", "orange", "purple", "pink")
COLOR_TEMP_WORDS = ("warm", "cool")  # colortemp-Wortwerte (neben Kelvin-Zahl) — Single-Source fürs GBNF-value-Tightening

# ── Enums ─────────────────────────────────────────────────────────────────
DIRECTION = ("up", "down")
AMOUNT = ("a_little", "some", "a_lot")
AGGREGATE = ("value", "any", "all", "count", "avg", "min", "max")
# TIMER_ACTION: v1-Kern (set,cancel,check) + additive Lifecycle (2026-07-07, C1-Scope-Gap):
#   cancel_all (HassCancelAllTimers) · add/subtract (Increase/DecreaseTimer, nutzen duration relativ) · pause/resume (Pause/UnpauseTimer)
TIMER_ACTION = ("set", "cancel", "cancel_all", "check", "add", "subtract", "pause", "resume")
# MEDIA_ACTION: v1-Kern + additive mute/unmute (HassMediaPlayerMute/Unmute)
MEDIA_ACTION = ("play", "pause", "next", "previous", "stop", "play_content", "mute", "unmute")
LIST_ACTION = ("add", "remove", "complete")  # HassListAddItem/RemoveItem/CompleteItem
VACUUM_ACTION = ("start", "return_to_base", "clean_area")  # HassVacuumStart/ReturnToBase/CleanArea (stop → verb `stop`)

# ── Verben (cap-v2, 12 — alle Aktion; Dialog läuft als freier Text im Loop) ──
# Jeder Eintrag: target(bool) · params{name: spec} · required[list] · dialog(bool)
# param-spec: {"type":"str"} | {"type":"enum","values":(...)} | {"type":"value","attr_of":"attribute"}
#             optional-Flag ⇒ nicht in required.
VERBS = {
    "turn_on":  {"target": True,  "params": {}, "required": []},
    "turn_off": {"target": True,  "params": {}, "required": []},
    "set_state": {
        "target": True,
        "params": {
            "attribute": {"type": "enum", "values": tuple(SETTABLE_ATTRS)},
            "value": {"type": "value", "attr_of": "attribute"},
        },
        "required": ["attribute", "value"],
    },
    "adjust": {
        "target": True,
        "params": {
            "attribute": {"type": "enum", "values": ADJUSTABLE_ATTRS},
            "direction": {"type": "enum", "values": DIRECTION},
            "amount": {"type": "enum", "values": AMOUNT, "or_number": True},
        },
        "required": ["attribute", "direction"],
    },
    "get_state": {
        "target": True,
        "params": {
            "attribute": {"type": "enum", "values": GET_ATTRS},
            "aggregate": {"type": "enum", "values": AGGREGATE},
        },
        "required": [],
    },
    "run_routine": {"target": False, "params": {"name": {"type": "str"}}, "required": ["name"]},
    "set_timer": {
        "target": True,   # additiv (2026-07-07): area-scoped Timer (Voice-Satellit-Area, v22 HassTimerStatus/CancelAllTimers)
        "params": {
            "action": {"type": "enum", "values": TIMER_ACTION},
            "duration": {"type": "str"},
            "label": {"type": "str"},
        },
        "required": ["action"],
    },
    "control_media": {
        "target": True,
        "params": {
            "action": {"type": "enum", "values": MEDIA_ACTION},
            "content": {"type": "str"},
        },
        "required": ["action"],
    },
    # ── Additive Verben (2026-07-07, C1-Scope-Gap: v22-Familien ohne v1-Kern-Landing) ──
    "announce": {
        "target": True,   # optionaler Ziel-Block (Broadcast an alle | an einen Raum)
        "params": {"message": {"type": "str"}},
        "required": ["message"],
    },
    "manage_list": {
        "target": False,  # Liste ist kein Geräte-Ziel; `name` = Listenname
        "params": {
            "name": {"type": "str"},
            "action": {"type": "enum", "values": LIST_ACTION},
            "item": {"type": "str"},
        },
        "required": ["name", "action", "item"],
    },
    "control_vacuum": {
        "target": True,   # area für clean_area / Gerätename
        "params": {"action": {"type": "enum", "values": VACUUM_ACTION}},
        "required": ["action"],
    },
    "stop": {             # Bewegung anhalten — domain-polymorph (cover.stop_cover | vacuum.stop), spiegelt HassStopMoving
        "target": True,
        "params": {},
        "required": [],
    },
    # ── cap-v2: ask/decline/respond GESTRICHEN → freier Antworttext im Loop (kein Tool-Block). ──
}

ACTION_VERBS = tuple(v for v, s in VERBS.items() if not s.get("dialog"))
DIALOG_VERBS = tuple(v for v, s in VERBS.items() if s.get("dialog"))


def verb_param_keys(verb: str) -> list[str]:
    """Alle erlaubten Keys für einen Verb: Ziel-Block (falls target) + eigene Params."""
    spec = VERBS[verb]
    keys = list(TARGET_PARAMS) if spec["target"] else []
    keys += list(spec["params"])
    return keys


def all_param_keys() -> list[str]:
    """Union aller je gültigen Keys (für permissive GBNF / Parser-Whitelist)."""
    keys = list(TARGET_PARAMS)
    for spec in VERBS.values():
        for k in spec["params"]:
            if k not in keys:
                keys.append(k)
    return keys
