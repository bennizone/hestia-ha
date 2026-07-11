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
# `ref` (it/here/there/last) GESTRICHEN (Benni 2026-07-09, Grain-Footgun #1 +
# serve-unaufgelöst = train≠serve). „Hier/das" läuft über Live-Kontext-Raum + area-Default.
TARGET_PARAMS = {
    "name":   {"type": "str"},   # Eigenname verbatim
    "area":   {"type": "str"},
    "floor":  {"type": "str"},
    "domain": {"type": "str"},   # light|switch|climate|cover|fan|lock|media_player|sensor|...
}

# ── Wort-Enums für set_state-Attribute (Vollständigkeit via Attribut-Enum, Benni 2026-07-09) ──
HVAC_MODES = ("heat", "cool", "auto", "off", "dry", "fan_only")
PRESETS = ("eco", "boost", "away", "comfort", "home", "sleep")     # climate preset_mode (Executor Postel-vergebend)
LOCK_STATES = ("locked", "unlocked")                              # + Safety-Gate (Zwei-Turn-Confirm)
ALARM_STATES = ("armed_home", "armed_away", "armed_night", "disarmed")  # + Safety-Gate
ONOFF = ("on", "off")                                            # oscillate/boolesche Attribute

# ── Attribute + Wert-Domänen ──────────────────────────────────────────────
# kind steuert Wert-Grammatik (GBNF) + Parser-Validierung + Executor-Mapping.
#   pct        : 0..100 | "max" | "min"
#   number     : Zahl (z.B. Grad, Helfer-Wert)
#   colorword  : Farbwort-Enum
#   colortemp  : "warm" | "cool" | Kelvin-Zahl
#   words      : geschlossenes Wort-Enum (values-Tupel) — hvac_mode/preset/lock/alarm/oscillate
#   str        : freier String (Effektname, Select-Option) — gerätespezifisch, nicht enumerierbar
# Universal-Setter (grain-nativ): Fähigkeit skaliert über Attribut-Enum, NICHT über neue Verben.
SETTABLE_ATTRS = {
    "brightness": {"kind": "pct"},
    "volume":     {"kind": "pct"},
    "position":   {"kind": "pct"},   # Cover auf/zu → set_state(position=100/0) (Grain-Lock)
    "fan_speed":  {"kind": "pct"},
    "tilt":       {"kind": "pct"},   # Cover-Lamellen
    "humidity":   {"kind": "pct"},   # humidifier target
    "temperature": {"kind": "number"},
    "value":      {"kind": "number"},  # number/input_number-Helfer (attribute="value")
    "color":      {"kind": "colorword"},
    "color_temp": {"kind": "colortemp"},
    "hvac_mode":  {"kind": "words", "values": HVAC_MODES},
    "preset":     {"kind": "words", "values": PRESETS},
    "lock":       {"kind": "words", "values": LOCK_STATES},
    "alarm":      {"kind": "words", "values": ALARM_STATES},
    "oscillate":  {"kind": "words", "values": ONOFF},
    "effect":     {"kind": "str"},   # Licht-Effekt (freier Name)
    "option":     {"kind": "str"},   # select/input_select-Option (freier Name)
}
ADJUSTABLE_ATTRS = ("brightness", "volume", "temperature", "position", "fan_speed", "color_temp")
# GET_ATTRS = Kern-Enum (breit, aber nicht Riesen-Enum). Feinere Discovery via `help`-Verb (Phase 3).
GET_ATTRS = ("state", "brightness", "temperature", "humidity", "illuminance",
             "battery", "power", "energy", "co2", "position", "volume",
             "fan_speed", "hvac_mode", "lock", "open", "datetime", "weather", "sun")
COLOR_WORDS = ("warm_white", "cold_white", "white", "red", "green", "blue",
               "yellow", "orange", "purple", "pink")
COLOR_TEMP_WORDS = ("warm", "cool")  # colortemp-Wortwerte (neben Kelvin-Zahl) — Single-Source fürs GBNF-value-Tightening

# Farb-Synonyme (dt + en Varianten) → kanonisches COLOR_WORDS-Enum. Angewandt in
# result.set_value_or_error VOR der Enum-Prüfung (serve==train). Deutsche Farbnamen
# konvertieren (Benni 2026-07-10, „ausführliche map"); genuin gamut-fremde Farben
# (türkis/cyan, braun, grau, gold …) bleiben ABSICHTLICH ungemappt → invalid_value +
# allowed-Suggestion (H5). Enum-native englische Werte (red/green/…) laufen über den
# .get-Default durch, brauchen also keinen Identity-Eintrag.
COLOR_SYNONYMS = {
    "rot": "red", "hellrot": "red", "dunkelrot": "red", "weinrot": "red",
    "grün": "green", "gruen": "green", "hellgrün": "green", "hellgruen": "green",
    "dunkelgrün": "green", "dunkelgruen": "green",
    "blau": "blue", "hellblau": "blue", "dunkelblau": "blue", "navy": "blue",
    "marineblau": "blue",
    "gelb": "yellow",
    "orangefarben": "orange",
    "rosa": "pink", "rose": "pink", "rosé": "pink", "magenta": "pink",
    "fuchsia": "pink", "pinkfarben": "pink",
    "lila": "purple", "violett": "purple", "violet": "purple", "purpur": "purple",
    "aubergine": "purple", "indigo": "purple", "flieder": "purple",
    "weiß": "white", "weiss": "white",
    "warmweiß": "warm_white", "warmweiss": "warm_white", "warmwhite": "warm_white",
    "warmes weiß": "warm_white", "warmes weiss": "warm_white",
    "kaltweiß": "cold_white", "kaltweiss": "cold_white", "coldwhite": "cold_white",
    "kühlweiß": "cold_white", "kuehlweiss": "cold_white", "kaltes weiß": "cold_white",
    "kaltes weiss": "cold_white", "tageslichtweiß": "cold_white",
}


def settable_value_words() -> tuple[str, ...]:
    """Alle Wort-Werte, die IRGENDEIN SETTABLE_ATTR annehmen kann (deduped, für GBNF-value-Union).
    Single-Source: neue Wort-Enums propagieren automatisch in GBNF + Parser."""
    out: list[str] = []
    for spec in SETTABLE_ATTRS.values():
        k = spec["kind"]
        if k == "colorword":
            out += list(COLOR_WORDS)
        elif k == "colortemp":
            out += list(COLOR_TEMP_WORDS)
        elif k == "words":
            out += list(spec["values"])
    seen: set[str] = set()
    return tuple(w for w in out if not (w in seen or seen.add(w)))


def settable_allows_free_str() -> bool:
    """True, wenn ein SETTABLE_ATTR freie Strings als Wert zulässt (effect/option) → GBNF-value braucht str-Alt."""
    return any(spec["kind"] == "str" for spec in SETTABLE_ATTRS.values())

# ── Enums ─────────────────────────────────────────────────────────────────
DIRECTION = ("up", "down")
AMOUNT = ("a_little", "some", "a_lot")
AGGREGATE = ("value", "any", "all", "count", "avg", "min", "max")
# TIMER_ACTION: v1-Kern (set,cancel,check) + additive Lifecycle (2026-07-07, C1-Scope-Gap):
#   cancel_all (HassCancelAllTimers) · add/subtract (Increase/DecreaseTimer, nutzen duration relativ) · pause/resume (Pause/UnpauseTimer)
TIMER_ACTION = ("set", "cancel", "cancel_all", "check", "add", "subtract", "pause", "resume")
# MEDIA_ACTION: v1-Kern + additive mute/unmute (HassMediaPlayerMute/Unmute) + source (Quelle wählen, content=Quellenname)
MEDIA_ACTION = ("play", "pause", "next", "previous", "stop", "play_content", "mute", "unmute", "source")
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
    # ── Discovery (2026-07-09): Model navigiert Fähigkeiten/Attribute selbst statt Riesen-Enum.
    #    Executor-`help`-Endpoint + Trainingsverteilung = Phase 3 (im selben 150k-Regen).
    "help": {
        "target": False,
        "params": {"topic": {"type": "str"}},   # optional: worum geht's (Attribut/Gerät/Fähigkeit)
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
