"""cap_attrs — deklarative Spec-Tabelle der Enum-Listen-Fähigkeitsattribute (v23.6 Phase A).

**Blatt-Knoten** (Import-Layering §10.3): importiert NICHTS aus dem Paket. Reihenfolge im Paket:
`cap_attrs → schema → result → captag`. Hält (a) die fixen Wort-Enums (schema re-exportiert sie,
Byte-Neutralität) und (b) die `EnumCapAttr`-Tabelle der Enum-Listen-Attribute (geräte-echte Wertliste
→ wähle EINEN Wert).

Die Tabelle ist NICHT ein Voll-Code-Generator, sondern **(a) Single-Source für die WIRKLICH
uniformen Ableitungen** und **(b) ein test-erzwungenes Konsistenz-Rückgrat** (Gate-0-Review,
V23_6_CAP_SPEC_TABLE_REFACTOR.md §10). Konkret TREIBT die Tabelle (§10.1):
  · executor `_dispatch_attr`  — EIN generischer Enum-Dispatch über `service` (statt N elif-Cases),
  · `_ATTR_DE`/`_ATTR_NEG_DE`  — deutsche Nomen/Verneinung (Lookup-Map, order-frei),
  · `ATTR_DOMAIN`/`EXECUTABLE_ATTRS` — Single-/Multi-Domain-Split (Keyset test-gepinnt),
  · captag-Advertiser-Paare (`tag_label`,`list_key`) für fx/pre/fan/swing/opt.

EXPLIZIT (nur test-validiert, §10.2 — NICHT über die Tabelle generiert):
  · `capabilities_of` hvac_mode (Key-Präsenz + `_ordered`) und option (truthy + any-Fallback) bleiben
    EIGENE Zweige — die Tabelle trägt KEINE guard/order/fallback-Flags; NUR effect/preset/fan_mode/
    swing_mode teilen EIN Verhalten (truthy + RAW + omit) via `result._enum_caps_for`.
  · captag hvac_mode (`tag_label=""` → hand-gerendert) + src bleiben hand-strukturiert.
  · `schema.SETTABLE_ATTRS`-Order bleibt Literal (Frozen-Test); Generator-`_cap_profile` = Hand-Daten.

─────────────────────────────────────────────────────────────────────────────────────────────────
NEUES ATTRIBUT HINZUFÜGEN (Batch 1b usw.) — es ist bewusst MEHR als eine Zeile (§10.2). Checkliste:
  1. Zeile in `ENUM_CAP_ATTRS` (unten) mit kwargs. Sonderfälle:
       · Multi-Domain (svc+param MÜSSEN domain-invariant sein): `domains=("a","b")`, ha_domain-Slot
         von `service` egal (Dispatch splittet über `domains` in dieser Order).
       · Setter ≠ `set_X`: beliebiges `service`-Tupel — z.B. remote `("remote","turn_on","activity")`.
       · pct-Namenskollision (vacuum): eigener attr-Name `vacuum_fan_speed`, list_key `fan_speed_list`.
       · Bit-Gate (sound_mode SELECT_SOUND_MODE): `feat_bit=…` — result `_enum_caps_for` + captag gaten
         darauf (Phase-B-verdrahtet). Fix-Enum ohne Liste (fan.direction) = KEINE Zeile → oscillate-Klasse
         (schema+result+captag+executor hand-verdrahtet, §10.5).
  2. `schema.SETTABLE_ATTRS`: Eintrag `{attr:{"kind":"str"}}` ans ENDE (Key-Order ist Prompt-byte-tragend).
  3. captag: `_adv`-Aufruf an der gewünschten Position im (evtl. neuen) Domain-Block.
  4. Generator `_cap_profile`: Archetyp-Block + Wert-Pool (Hand-Daten, §10.2).
  5. Frozen-Literale in `tests/test_cap_attrs_table.py` BEWUSST erweitern (sonst rot).
  6. Golden BEWUSST regen (`HESTIA_REGEN_GOLDEN=1`, Diff gehört ins Review) + `tools/vendor_sync.py`.
─────────────────────────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Fixe Wort-Enums (aus schema.py hierher gezogen, §10.3; schema re-exportiert) ──
HVAC_MODES = ("heat", "cool", "auto", "off", "dry", "fan_only")
PRESETS = ("eco", "boost", "away", "comfort", "home", "sleep")     # climate preset_mode (Executor Postel-vergebend)
LOCK_STATES = ("locked", "unlocked")                              # + Safety-Gate (Zwei-Turn-Confirm)
ALARM_STATES = ("armed_home", "armed_away", "armed_night", "disarmed")  # + Safety-Gate
ONOFF = ("on", "off")                                            # oscillate/boolesche Attribute
FAN_DIRECTION = ("forward", "reverse")                           # fan.direction — Fix-2-Enum (oscillate-Klasse, §10.5)


@dataclass(frozen=True)
class EnumCapAttr:
    """Eine Zeile = ein Enum-Listen-Attribut (geräte-echte Wertliste, X=8-Advertiser, caps-enum-gated).

    attr      : SETTABLE_ATTRS-Key + Modell-Token (GBNF attribute-Enum).
    domains   : Entity-Domains, die dieses Attr tragen (Single → ATTR_DOMAIN-Narrowing; Multi → nur
                EXECUTABLE, Dispatch splittet über `domains` in DIESER Order).
    list_key  : Geräte-Attribut mit der Wertliste (capabilities_of/captag lesen es).
    service   : (ha_domain, service, param) für den HA-Service-Call. Bei Multi-Domain ist ha_domain
                bedeutungslos (Split über `domains`); service+param MÜSSEN domain-invariant sein.
    tag_label : captag-Advertiser-Präfix (`label:v1/v2/…`). "" ⇒ KEIN generischer Advertiser
                (hvac_mode wird in captag HAND-gerendert: off-Filter + `_ordered` + modeN-Hinweis).
    de_noun   : `_ATTR_DE`-Nomen. de_neg: `_ATTR_NEG_DE`-Verneinung (Genus korrekt).
    feat_bit  : optionales supported_features-Gate (Phase B verdrahtet, §10.4). Gesetzt NUR bei
                sound_mode (SELECT_SOUND_MODE=65536): über-claim-sicher wie `src` — ein media_player
                mit `sound_mode_list` aber ohne SELECT_SOUND_MODE-Bit ist NICHT fähig (result
                `_enum_caps_for` überspringt ihn; captag gatet den Advertiser mit demselben Bit).
                Alle anderen Zeilen tragen ein echtes Listen-Attribut → truthy-Guard reicht (feat_bit=None).
    """
    attr: str
    domains: tuple[str, ...]
    list_key: str
    service: tuple[str, str, str]
    tag_label: str
    de_noun: str
    de_neg: str
    feat_bit: int | None = None


# ── DIE Tabelle (Phase A: die 6 bestehenden Enum-Listen-Attribute) ──
# Zeilen-Order hier = reine Lese-Konvention, NIRGENDS byte-tragend: captag iteriert die Tabelle nicht
# (per-Attr `_adv`-Aufrufe an fixer Position im Hand-Block, captag.py), alle Ableitungen unten sind
# order-freie Dicts/Sets, und die `_enum_caps_for`-Insert-Order in caps.settable ist inert (alle
# Konsumenten sortieren/looken-up). Die Advertiser-Byte-Order liegt in captag.py (climate pre→fan→swing).
ENUM_CAP_ATTRS = (
    EnumCapAttr(attr="effect", domains=("light",), list_key="effect_list",
                service=("light", "turn_on", "effect"), tag_label="fx",
                de_noun="Effekt", de_neg="keinen Effekt"),
    # hvac_mode: tag_label="" → captag hand-gerendert; capabilities_of-Zweig EXPLIZIT (Key-Präsenz, §10.2)
    EnumCapAttr(attr="hvac_mode", domains=("climate",), list_key="hvac_modes",
                service=("climate", "set_hvac_mode", "hvac_mode"), tag_label="",
                de_noun="Modus", de_neg="keinen Betriebsmodus"),
    EnumCapAttr(attr="preset", domains=("climate", "fan"), list_key="preset_modes",
                service=("climate", "set_preset_mode", "preset_mode"), tag_label="pre",
                de_noun="Voreinstellung", de_neg="kein Programm"),
    EnumCapAttr(attr="fan_mode", domains=("climate",), list_key="fan_modes",
                service=("climate", "set_fan_mode", "fan_mode"), tag_label="fan",
                de_noun="Lüftermodus", de_neg="keinen Lüftermodus"),
    EnumCapAttr(attr="swing_mode", domains=("climate",), list_key="swing_modes",
                service=("climate", "set_swing_mode", "swing_mode"), tag_label="swing",
                de_noun="Schwenkmodus", de_neg="keinen Schwenkmodus"),
    # option: multi-domain (select/input_select); capabilities_of-Zweig EXPLIZIT (any-Fallback, §10.2)
    EnumCapAttr(attr="option", domains=("select", "input_select"), list_key="options",
                service=("select", "select_option", "option"), tag_label="opt",
                de_noun="Einstellung", de_neg="keine Einstellung"),
    # ── v23.6 Batch 1b (§10.5): Growth-Domains, additiv. Alle uniform (truthy+RAW+omit via
    #    _enum_caps_for); sound_mode zusätzlich bit-gegated (feat_bit, Over-Claim-Schutz wie src). ──
    EnumCapAttr(attr="sound_mode", domains=("media_player",), list_key="sound_mode_list",
                service=("media_player", "select_sound_mode", "sound_mode"), tag_label="snd",
                de_noun="Klangmodus", de_neg="keinen Klangmodus", feat_bit=65536),  # SELECT_SOUND_MODE
    EnumCapAttr(attr="mode", domains=("humidifier",), list_key="available_modes",
                service=("humidifier", "set_mode", "mode"), tag_label="mode",
                de_noun="Modus", de_neg="keinen Modus"),
    EnumCapAttr(attr="operation", domains=("water_heater",), list_key="operation_list",
                service=("water_heater", "set_operation_mode", "operation_mode"), tag_label="op",
                de_noun="Betriebsart", de_neg="keine Betriebsart"),
    # remote: Setter ≠ set_X → remote.turn_on mit optionalem `activity`-String (§10.4-Sonderfall)
    EnumCapAttr(attr="activity", domains=("remote",), list_key="activity_list",
                service=("remote", "turn_on", "activity"), tag_label="act",
                de_noun="Aktivität", de_neg="keine Aktivität"),
    # vacuum: eigener Attr-Name `vacuum_fan_speed` (pct-Kollision mit fan-Domain fan_speed vermieden, §10.4)
    EnumCapAttr(attr="vacuum_fan_speed", domains=("vacuum",), list_key="fan_speed_list",
                service=("vacuum", "set_fan_speed", "fan_speed"), tag_label="spd",
                de_noun="Saugstufe", de_neg="keine Saugstufe"),
)

# capabilities_of-Helfer `_enum_caps_for` deckt NUR diese ab (truthy + RAW + omit→not_capable; sound_mode
# zusätzlich feat_bit-gegated); hvac_mode (Key-Präsenz + `_ordered`) und option (truthy + any-Fallback)
# bleiben EXPLIZITE Zweige (§10.2). Batch1b (sound_mode/mode/operation/activity/vacuum_fan_speed) sind uniform.
ENUM_CAPS_HELPER_ATTRS = ("effect", "preset", "fan_mode", "swing_mode",
                          "sound_mode", "mode", "operation", "activity", "vacuum_fan_speed")

BY_ATTR = {r.attr: r for r in ENUM_CAP_ATTRS}
# ATTR_DOMAIN-Beitrag (Single-Domain) bzw. EXECUTABLE-Beitrag (Multi-Domain):
SINGLE_DOMAIN = {r.attr: r.domains[0] for r in ENUM_CAP_ATTRS if len(r.domains) == 1}
MULTI_DOMAIN_ATTRS = frozenset(r.attr for r in ENUM_CAP_ATTRS if len(r.domains) > 1)
DE_NOUN = {r.attr: r.de_noun for r in ENUM_CAP_ATTRS}
DE_NEG = {r.attr: r.de_neg for r in ENUM_CAP_ATTRS}
