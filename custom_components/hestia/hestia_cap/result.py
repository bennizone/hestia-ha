"""cap-v2 rev2-Result-Shaping — DIE eine Quelle (train == serve).

Analog zu render.py/parse.py: der rev2-Tool-Result (RESULT_SCHEMA.md) wird EINMAL
gebaut. Der HA-Serve-Executor (`hestia-ha/.../executor.py`) UND der Trainings-Generator
(`ha-llm-finetune/data_gen/v23/emit_capv2_multiturn.py`) importieren dieselben Shaper/
Error-Builder/Resolver → kein train≠serve auf dem Tool-JSON (Audit 2026-07-09, B2–B8/H2–H9).

Reinheit: HA-frei, dep-frei (nur stdlib `difflib`/`typing`). Alle Funktionen sind pure über
`(Call-args, exposure, State-Reads)`. Die Naht zwischen serve und train ist der **StateProvider**:
- serve: liest echtes HA (`hass.states.get` / `dt_util.now`),
- train: liest Haus-Config + simulierten State-Store (Generator-seitig).
Service-Calls (`hass.services.async_call`) bleiben serve-seitig; sie speisen das Result NIE —
die Result-Felder kommen aus `names`, `args` und State-READS.

Kontrakt: homelab-admin/hestia/v23/RESULT_SCHEMA.md (rev2, GELOCKT 2026-07-08).
Fehler-Codes: RESULT_SCHEMA §3 (additiv-only Enum) — hier die einzige Bau-Quelle.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Protocol, runtime_checkable

from . import cap_attrs
from .schema import (ADJUSTABLE_ATTRS, ALARM_STATES, COLOR_SYNONYMS, COLOR_WORDS,
                     FAN_DIRECTION, HVAC_MODES, LOCK_STATES, ONOFF, SETTABLE_ATTRS)

# ── Konstanten (aus executor.py gehoben — jetzt Single-Source) ────────────────
# Attribut → zuständige (EINDEUTIGE) Domain (set_state/adjust ohne explizites domain-Filter):
# „stell die Heizung auf 20" darf NUR climate treffen, nicht TVs/Lichter/Lüfter.
# Die NICHT-Enum-Attrs stehen explizit (Range/pct/Farbe/Safety/oscillate/direction); die Enum-Listen-Attrs
# (effect/hvac_mode/swing_mode/fan_mode + Batch1b sound_mode/mode/operation/activity/vacuum_fan_speed,
# alle single-domain) kommen aus der Spec-Tabelle (cap_attrs.SINGLE_DOMAIN, v23.6). Multi-Domain-Enums
# (`preset` climate/fan, `option` select/input_select) fehlen BEWUSST in ATTR_DOMAIN (kein Single-Narrowing
# → „Lüfter auf Schlaf" bleibt möglich), sind aber ausführbar via EXECUTABLE_ATTRS (per-Entität geplant,
# Dispatch splittet nach Domain). `direction` (Fix-Enum, oscillate-Klasse §10.5) ist explizit → fan.
_EXPLICIT_NONENUM_DOMAIN = {
    "temperature": "climate", "brightness": "light", "color": "light",
    "color_temp": "light", "volume": "media_player", "position": "cover",
    "fan_speed": "fan", "lock": "lock", "alarm": "alarm_control_panel",
    "oscillate": "fan", "tilt": "cover", "direction": "fan"}
ATTR_DOMAIN = {**_EXPLICIT_NONENUM_DOMAIN, **cap_attrs.SINGLE_DOMAIN}

# Set-State-Attribute, die der Executor DISPATCHEN kann (Executability-Gate, getrennt von der
# Narrowing-Map ATTR_DOMAIN): alle eindeutigen + die Multi-Domain-Enum-Attrs aus der Tabelle
# (`preset`, `option`), die per Entität geplant/nach Domain gesplittet werden.
EXECUTABLE_ATTRS = frozenset(ATTR_DOMAIN) | cap_attrs.MULTI_DOMAIN_ATTRS

# amount-Enum → Schrittweite (pct-Verben) bzw. Grad-Delta (temperature)
STEP_PCT = {"a_little": 10, "some": 25, "a_lot": 50}
STEP_DEG = {"a_little": 0.5, "some": 1.0, "a_lot": 2.0}
KELVIN = {"warm": 2700, "cool": 6500}

# state-Werte, die als „an/aktiv" zählen (any/all-Aggregat)
ON_STATES = {"on", "open", "home", "playing", "unlocked", "heat", "cool", "auto"}


# ── StateProvider (die train/serve-Naht) ──────────────────────────────────────
@runtime_checkable
class StateProvider(Protocol):
    """Abstrahiert den State-Zugriff. serve wrappt HA, train wrappt Haus+Sim-Store."""
    def read(self, eid: str) -> dict | None:
        """{"state": <str>, "attributes": {...}} für eine Entität, oder None (unbekannt)."""
        ...

    def now(self):
        """Aktuelle lokale Zeit (datetime) — für get_state(datetime)."""
        ...


# ── kleine Helfer ──────────────────────────────────────────────────────────────
def _norm(s) -> str:
    return (s or "").strip().casefold()


def _cap3(names: list) -> list:
    return names[:3]


def _num(x):
    """Kanonische Zahl-Repräsentation: ganze Floats → int (22.0 → 22). Fixt B3-Byte-Divergenz;
    identische Konvention wie serialize._fmt_value."""
    if isinstance(x, bool):
        return x
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


def _pct(v, lo=0):
    if v == "max":
        return 100
    if v == "min":
        return lo
    return int(v)


def _step(amount, table, default_key="some"):
    if isinstance(amount, (int, float)):
        return float(amount)
    return table.get(amount, table[default_key])


def names_of(exposure: dict, eids: list) -> list:
    return [exposure[e]["llm_name"] for e in eids if e in exposure]


# ── Error-Builder (RESULT_SCHEMA §3 = einzige Quelle) ─────────────────────────
def ok(**kw) -> dict:
    return {"ok": True, **kw}


def err_entity_not_found(query, did_you_mean=None) -> dict:
    d = {"ok": False, "error": "entity_not_found", "query": query}
    if did_you_mean:
        d["did_you_mean"] = list(did_you_mean)
    return d


def err_ambiguous(candidates=None, count=None, areas=None) -> dict:
    d = {"ok": False, "error": "ambiguous"}
    if count is not None:
        d["count"] = count
    if candidates is not None:
        d["candidates"] = _cap3(list(candidates))
    if areas is not None:
        d["areas"] = _cap3(list(areas))
    return d


def err_invalid_value(param, given, allowed) -> dict:
    return {"ok": False, "error": "invalid_value", "param": param,
            "given": given, "allowed": list(allowed)}


def err_no_targets(query="") -> dict:
    return {"ok": False, "error": "no_targets", "query": query}


def err_no_data(query="") -> dict:
    return {"ok": False, "error": "no_data", "query": query}


def err_unavailable(query="") -> dict:
    return {"ok": False, "error": "unavailable", "query": query}


def err_not_controllable(query="", available=None) -> dict:
    """not_controllable. `available` (v23.5 P1b, additiv) = die Attribute, die die Entität DOCH
    setzen kann — handlungsleitend für not_capable („kann keine Farbe — nur Helligkeit/Weißton")."""
    d = {"ok": False, "error": "not_controllable", "query": query}
    if available:
        d["available"] = list(available)
    return d


def err_unsafe(query="") -> dict:
    return {"ok": False, "error": "unsafe", "query": query}


# Hinweis-Felder eines Fehlers, die in einen partial-`failed`-Eintrag mitwandern (query → name ersetzt).
_FAIL_HINT_KEYS = ("available", "allowed", "did_you_mean", "param", "given")


def _failed_entry(name: str, err: dict) -> dict:
    """Fehler-dict (aus plan_set_state) → partial-`failed`-Eintrag {name,error[,hints]}.
    `query` fällt weg (der Ziel-Bezug ist jetzt `name`); die handlungsleitenden Hinweise bleiben."""
    e = {"name": name, "error": err.get("error")}
    for k in _FAIL_HINT_KEYS:
        if k in err:
            e[k] = err[k]
    return e


def shape_partial(targets: list, failed: list) -> dict:
    """PARTIAL (RESULT_SCHEMA §2a): Multi-Target, manche geglückt/manche gescheitert.
    ok=false (nicht voller Erfolg), aber die geglückten `targets` bleiben zitierbar + `failed`
    trägt pro Ziel den handlungsleitenden Fehler. `say`/Antwort nennt beide Seiten (§4)."""
    return {"ok": False, "targets": list(targets), "failed": list(failed)}


def err_timeout(query="") -> dict:
    return {"ok": False, "error": "timeout", "query": query}


def err_unparseable() -> dict:
    return {"ok": False, "error": "unparseable"}


# ── Resolution (ersetzt executor.resolve UND generator.resolve_targets, H7) ────
def resolve(args: dict, exposure: dict) -> tuple:
    """Ziel-Block → (entity_ids, None) ODER (None, fehler-dict).

    name → exakter/aliaser Match (fuzzy did_you_mean bei Fehlschlag); sonst area/floor/domain
    als Gruppen-Filter. Leerer Ziel-Block → no_targets (MVP; `ref` ist gestrichen)."""
    name = args.get("name")
    area, floor, domain = args.get("area"), args.get("floor"), args.get("domain")

    pool = []
    for eid, rec in exposure.items():
        if domain and rec["domain"] != domain:
            continue
        if area and _norm(rec.get("area")) != _norm(area):
            continue
        if floor and _norm(rec.get("floor")) != _norm(floor):
            continue
        pool.append((eid, rec))

    if name:
        nn = _norm(name)
        exact = [(eid, rec) for eid, rec in pool
                 if _norm(rec["llm_name"]) == nn or any(_norm(a) == nn for a in rec.get("aliases", ()))]
        if len(exact) == 1:
            return [exact[0][0]], None
        if len(exact) > 1:
            areas = sorted({r.get("area") or "" for _, r in exact if r.get("area")})
            if len(exact) > 3 and len(areas) > 1:
                return None, err_ambiguous(count=len(exact), areas=areas)
            return None, err_ambiguous(candidates=[r["llm_name"] for _, r in exact])
        # kein exakter Treffer → fuzzy-Hinweis über ALLE exponierten Namen
        allnames = [rec["llm_name"] for rec in exposure.values()]
        dym = difflib.get_close_matches(name, allnames, n=3, cutoff=0.5)
        return None, err_entity_not_found(name, did_you_mean=dym or None)

    # kein name → Gruppen-Aktion über Filter
    if not (area or floor or domain):
        return None, err_no_targets("")
    if not pool:
        return None, err_no_targets(area or floor or domain)
    return [eid for eid, _ in pool], None


# Read-only Domains ohne on/off-Semantik: dürfen NIE Ziel eines Gruppen-turn_on/off sein (H6).
_TURN_READONLY = ("sensor", "binary_sensor", "weather")


def strip_readonly_for_turn(eids: list, exposure: dict):
    """Gruppen-turn_on/off ohne Domain löst den GANZEN Raum auf → Sensoren/Wetter (read-only) raus,
    sonst erschiene ein Sensor als „eingeschaltet" (train≠serve-Wurzel H6). (eids, None) | (None, err)."""
    keep = [e for e in eids if exposure[e]["domain"] not in _TURN_READONLY]
    if not keep:
        return None, err_no_targets("")
    return keep, None


# stop = „Bewegung anhalten" (HassStopMoving) → nur Domains MIT Stopp-Semantik. fan/media/light haben
# keinen Stopp (nur aus) → Fake-„gestoppt" wäre unwahr (B3). GETEILT train==serve (Generator + Executor).
_STOP_DOMAINS = ("cover", "vacuum")


def strip_to_stoppable(eids: list, exposure: dict):
    """stop-Ziele auf cover/vacuum einengen. Kein stoppbares Ziel → not_controllable statt Fake-Erfolg.
    (kept_eids, None) | (None, err_not_controllable)."""
    keep = [e for e in eids if exposure[e]["domain"] in _STOP_DOMAINS]
    if not keep:
        return None, err_not_controllable("")
    return keep, None


def narrow_by_attr_domain(eids: list, attr, exposure: dict):
    """set_state/adjust ohne explizites domain → auf die vom Attribut implizierte Domain einengen.
    Liefert (eids, None) oder (None, no_targets-err)."""
    dom = ATTR_DOMAIN.get(attr)
    if not dom:
        return eids, None
    narrowed = [e for e in eids if exposure[e]["domain"] == dom]
    if not narrowed:
        return None, err_no_targets(attr)
    return narrowed, None


# value_query auf Sensoren: der Wire trägt die Metrik als `attribute` (device_class), eine Area/Floor-
# Auflösung liefert aber ALLE Sensoren des Raums → auf die Metrik-tragenden Reads einengen (Raum → der
# eine passende Sensor, oder leer → no_data). GETEILT train==serve (emit read_result + executor _get_state
# rufen identisch auf). Nur bei area/floor OHNE name und nur für Sensor-Wert-Attribute — name-basierte
# Einzel-Reads (inkl. climate-temperature ohne device_class) bleiben unangetastet.
SENSOR_VALUE_ATTRS = frozenset({"temperature", "humidity", "illuminance",
                                "battery", "power", "energy", "co2"})
_ATTR_DEVICE_CLASS = {"co2": "carbon_dioxide"}   # sonst gilt attr == device_class


def narrow_area_reads(args: dict, attr, reads: list) -> list:
    """Area/Floor-value_query: reads auf die device_class des Metrik-Attributs filtern. No-op für
    name-basierte Reads oder Nicht-Sensor-Attribute."""
    if attr not in SENSOR_VALUE_ATTRS:
        return reads
    if args.get("name") or not (args.get("area") or args.get("floor")):
        return reads
    dc = _ATTR_DEVICE_CLASS.get(attr, attr)
    return [r for r in reads if (r.get("attributes") or {}).get("device_class") == dc]


# ── Wert-Normalisierung set_state (kanonisch, fixt B3/B5-pct/color_temp + invalid_value) ──
def set_value_or_error(attr, val) -> tuple:
    """(canon_value, unit, err) für set_state. canon = Result-Wert (auch HA-Service-Argument-Basis);
    err = invalid_value-dict oder None. Zentralisiert Wert-Semantik für serve UND train."""
    kind = SETTABLE_ATTRS.get(attr, {}).get("kind")
    if attr == "brightness":
        return _pct(val, lo=1), "%", None
    if attr in ("volume", "position", "fan_speed", "tilt", "humidity"):
        return _pct(val), "%", None
    if attr == "temperature":
        return _num(float(val)), "°C", None
    if attr == "value":                      # generischer Zahl-Helfer (number/input_number)
        return _num(float(val)), None, None
    if attr == "color":
        cv = COLOR_SYNONYMS.get(str(val).strip().lower(), str(val).strip().lower())
        if cv not in COLOR_WORDS:            # dt/en-Synonyme normalisiert, echt gamut-fremd → Fehler
            return None, None, err_invalid_value("color", val, list(COLOR_WORDS))
        return cv, None, None                # kanonischer Enum-Wert (Service-Arg + Result-value)
    if attr == "color_temp":
        kelvin = KELVIN.get(val, val if isinstance(val, (int, float)) else None)
        if kelvin is None:
            return None, None, err_invalid_value("color_temp", val, ["warm", "cool", "<kelvin>"])
        return _num(kelvin), "K", None
    if kind == "words":                      # hvac_mode/preset/lock/alarm/oscillate
        return val, None, None
    if kind == "str":                        # effect/option (freier Name)
        return val, None, None
    return None, None, err_not_controllable(attr)


# ══ v23.5 P1b: Capability-Introspektion (dynamischer Executor, DYNAMIC_EXECUTOR.md) ══
# EINE geteilte Funktion normalisiert BEIDE Quellen (Live-HA-Attr ↔ synth. Cap-Haus) in
# denselben Cap-Struct; ein geteilter Planer entscheidet daraus → train==serve auf dem Result-
# JSON (wie read_attr). `capabilities_of` ist pure über (domain, {"state","attributes"}) — kennt
# die QUELLE nicht, also ist Parität by-construction, solange beide Seiten dieselben Attr-Keys
# tragen (Cap-Haus-Kontrakt, Phase 4). Determinismus-LOCKs: §6.5 (CLAMP_MARGIN, allowed-Sortierung
# = Enum-Reihenfolge, Truncation N=6). Vorrang not_capable > invalid_value (§6.3).

CLAMP_MARGIN_PCT = 5          # §6.5: done_clamped melden erst ab Übergrenze+5pp (bzw. 1 Range-Step)
_ALLOWED_TRUNC_N = 6          # §6.5: allowed/available auf 6 kappen (WLED-180 → nicht dumpen)
_ATTR_ORDER = tuple(SETTABLE_ATTRS)   # kanonische Attr-Reihenfolge für `available`-Sortierung

# supported_features-Bits NUR wo KEIN Listen-Attribut existiert (§2 Bitmask-Regel):
# cover position/tilt, media volume, fan oscillate. hvac_modes/preset_modes/effect_list/options/
# source_list werden IMMER direkt aus der Liste gelesen (lokalisiert, robust).
_FEAT_BITS = {
    ("cover", "position"): 4,       # CoverEntityFeature.SET_POSITION
    ("cover", "tilt"): 128,         # CoverEntityFeature.SET_TILT_POSITION
    ("media_player", "volume"): 4,  # MediaPlayerEntityFeature.VOLUME_SET
    ("fan", "oscillate"): 2,        # FanEntityFeature.OSCILLATE
    ("fan", "direction"): 4,        # FanEntityFeature.DIRECTION (v23.6 Batch1b, oscillate-Klasse)
}
_COLOR_CAP_MODES = frozenset({"hs", "rgb", "xy", "rgbw", "rgbww"})


@dataclass
class Spec:
    """Wert-Domäne EINES settable-Attributs auf EINER Entität.
      kind="range" : numerisch, [lo,hi] (step/unit) — Klemmung → done_clamped
      kind="enum"  : geschlossene, GERÄTE-echte Wertliste (kanonisch sortiert) — invalid_value
      kind="any"   : fähig, aber Introspektion blank → konservativ akzeptieren (kein invalid_value, §4-Q3)
    """
    kind: str
    lo: float | int | None = None
    hi: float | int | None = None
    step: float | int | None = None
    unit: str | None = None
    values: tuple = ()


@dataclass
class Caps:
    """Was eine konkrete Entität kann. `settable`: attr→Spec (fehlt ⇒ not_capable);
    `adjustable`: relativ verstellbare Teilmenge (für plan_adjust, §4-Q5 später)."""
    domain: str
    settable: dict = field(default_factory=dict)
    adjustable: frozenset = frozenset()


def _feat(attrs: dict, domain: str, cap: str) -> bool:
    bit = _FEAT_BITS.get((domain, cap))
    sf = attrs.get("supported_features")
    if bit is None or not isinstance(sf, (int, float)):
        return False
    return bool(int(sf) & bit)


def _ordered(present, canonical) -> tuple:
    """GERÄTE-Werte in KANONISCHER Reihenfolge (Enum-Definition), unbekannte alphabetisch hinten.
    §6.5-LOCK: stabile Sortierung statt set-/Quell-Iteration → byte-identisches allowed train==serve.
    Extras werden `sorted` (nicht in Quell-Reihenfolge) → auch der unbekannt-Zweig ist quell-order-
    unabhängig (Opus-Gate S2; greift real nur, falls HA einen nicht-Standard-hvac-Mode meldet)."""
    p = list(present or [])
    known = [c for c in canonical if c in p]
    extra = sorted(x for x in p if x not in canonical)
    return tuple(known + extra)


def _range(attrs, lo_key, hi_key, step_key, unit, adj=False):
    """Range-Spec aus min/max-Attributen; fehlen beide → kind='any' (konservativ, §2-Fallback)."""
    lo, hi = attrs.get(lo_key), attrs.get(hi_key)
    if lo is None and hi is None:
        return Spec("any", unit=unit)
    step = attrs.get(step_key)
    return Spec("range", lo=_num_or(lo), hi=_num_or(hi),
                step=_num_or(step), unit=unit)


def _num_or(x):
    return _num(float(x)) if isinstance(x, (int, float)) else x


def _feat_bit_set(attrs: dict, bit: int) -> bool:
    """supported_features-Bit gesetzt? (feat_bit-Gate für Over-Claim-Schutz, §10.4)."""
    sf = attrs.get("supported_features")
    return isinstance(sf, (int, float)) and bool(int(sf) & bit)


def _enum_caps_for(s: dict, domain: str, attrs: dict) -> None:
    """Spec-Tabellen-getriebene Enum-Listen-Caps für die UNIFORMEN Attrs (effect/preset/fan_mode/
    swing_mode + Batch1b sound_mode/mode/operation/activity/vacuum_fan_speed): truthy-Guard + RAW-Order
    (§6.5-LOCK S1) + omit⇒not_capable. Zusätzlich feat_bit-Gate, wo gesetzt (sound_mode SELECT_SOUND_MODE:
    Liste OHNE Bit ⇒ nicht fähig, Over-Claim-Schutz wie src). NUR diese teilen EIN Verhalten (§10.2);
    hvac_mode (Key-Präsenz + `_ordered`) und option (truthy + any-Fallback) bleiben eigene Zweige im
    Aufrufer. Mutiert `s` (caps.settable) in-place.
    ⚠ Die Insert-Reihenfolge in `s` folgt der Tabellen-Order (≠ ALT-Insert-Order) — das ist INERT:
    kein Konsument iteriert caps.settable roh fürs Result (alle sortieren via `_ATTR_ORDER` oder
    looken-up). Falls je ein roh-iterierender settable-Konsument entsteht, wird das byte-relevant."""
    for r in cap_attrs.ENUM_CAP_ATTRS:
        if r.attr not in cap_attrs.ENUM_CAPS_HELPER_ATTRS or domain not in r.domains:
            continue
        if r.feat_bit is not None and not _feat_bit_set(attrs, r.feat_bit):
            continue                                      # bit-gegatet (sound_mode): kein Bit ⇒ nicht fähig
        vals = attrs.get(r.list_key)
        if vals:                                          # None-safe (F1: HA legt Cap-Keys oft mit None an)
            s[r.attr] = Spec("enum", values=tuple(vals))


def capabilities_of(domain: str, state_like: dict) -> Caps:
    """(domain, {"state","attributes"}) → Caps. Geteilt train==serve. Liest NUR Attribute (§1-Quelle
    je Attribut); absente Capability-Introspektion ⇒ konservativ (kind='any'), nie über-ablehnen."""
    attrs = (state_like or {}).get("attributes") or {}
    s: dict = {}
    adj: set = set()

    if domain == "climate":
        s["temperature"] = _range(attrs, "min_temp", "max_temp", "target_temp_step", "°C"); adj.add("temperature")
        if "hvac_modes" in attrs:                         # EXPLIZIT (§10.2): Key-Präsenz + kanonisch `_ordered`
            s["hvac_mode"] = Spec("enum", values=_ordered(attrs["hvac_modes"], HVAC_MODES))
        else:
            s["hvac_mode"] = Spec("any")
        _enum_caps_for(s, "climate", attrs)               # Tabelle: preset/fan_mode/swing_mode (truthy+RAW+omit)

    elif domain in ("light",):
        modes = attrs.get("supported_color_modes")
        if modes is None or set(modes) != {"onoff"}:       # onoff-only kann keine Helligkeit
            s["brightness"] = Spec("range", lo=1, hi=100, unit="%"); adj.add("brightness")
        if modes is None:
            s["color"] = Spec("any")                        # blank → konservativ akzeptieren
        elif set(modes) & _COLOR_CAP_MODES:
            s["color"] = Spec("enum", values=COLOR_WORDS)   # echte Farbe → Farbwort-Enum
        # sonst: color NICHT fähig → omit ⇒ not_capable
        if modes is None:
            s["color_temp"] = Spec("any")
        elif "color_temp" in modes:
            s["color_temp"] = _range(attrs, "min_color_temp_kelvin", "max_color_temp_kelvin", None, "K"); adj.add("color_temp")
        _enum_caps_for(s, "light", attrs)                   # Tabelle: effect (RAW-Order §6.5-LOCK S1 — WLED-180 → Trunc im Result)

    elif domain == "fan":
        # §2-Fallback 0–100 unbedingt (auch ohne SET_SPEED-Bit) — bewusste Design-Entscheidung:
        # beide Seiten claimen es gleich (kein Paritätsproblem), aber preset-only-Fans ohne SET_SPEED
        # täuschen Erfolg vor (accept-and-ignore, §6.9-Q9-Klasse) → am P2-Gate ggf. per Bit gaten.
        s["fan_speed"] = Spec("range", lo=0, hi=100, unit="%"); adj.add("fan_speed")
        _enum_caps_for(s, "fan", attrs)                      # Tabelle: preset (RAW; None-safe F1: SET_SPEED-only trägt None)
        if _feat(attrs, "fan", "oscillate"):
            s["oscillate"] = Spec("enum", values=ONOFF)
        if _feat(attrs, "fan", "direction"):                 # v23.6 Batch1b: Fix-2-Enum (oscillate-Klasse), bit-gegatet
            s["direction"] = Spec("enum", values=FAN_DIRECTION)

    elif domain == "cover":
        if _feat(attrs, "cover", "position"):
            s["position"] = Spec("range", lo=0, hi=100, unit="%"); adj.add("position")
        if _feat(attrs, "cover", "tilt"):
            s["tilt"] = Spec("range", lo=0, hi=100, unit="%")

    elif domain == "media_player":
        if _feat(attrs, "media_player", "volume"):
            s["volume"] = Spec("range", lo=0, hi=100, unit="%"); adj.add("volume")
        _enum_caps_for(s, "media_player", attrs)  # v23.6 Batch1b: sound_mode (SELECT_SOUND_MODE-bit-gegated, truthy-Liste)

    elif domain in ("select", "input_select"):   # options RAW-Order (§6.5-LOCK S1: Cap-Haus = Live-Order verbatim)
        s["option"] = Spec("enum", values=tuple(attrs["options"])) if attrs.get("options") else Spec("any")  # None-safe (F1)

    elif domain in ("number", "input_number"):
        s["value"] = _range(attrs, "min", "max", "step", None)

    elif domain == "humidifier":
        s["humidity"] = _range(attrs, "min_humidity", "max_humidity", None, "%"); adj.add("humidity")
        _enum_caps_for(s, "humidifier", attrs)   # v23.6 Batch1b: mode (available_modes, truthy+RAW+omit)

    elif domain == "water_heater":               # v23.6 Batch1b: operation (operation_list, truthy+RAW+omit)
        _enum_caps_for(s, "water_heater", attrs)

    elif domain == "remote":                     # v23.6 Batch1b: activity (activity_list; Setter = remote.turn_on)
        _enum_caps_for(s, "remote", attrs)

    elif domain == "vacuum":                     # v23.6 Batch1b: vacuum_fan_speed (fan_speed_list, truthy+RAW+omit)
        _enum_caps_for(s, "vacuum", attrs)

    elif domain == "lock":
        s["lock"] = Spec("enum", values=LOCK_STATES)

    elif domain == "alarm_control_panel":
        s["alarm"] = Spec("enum", values=ALARM_STATES)

    return Caps(domain=domain, settable=s,
                adjustable=frozenset(adj & set(ADJUSTABLE_ATTRS)))


def _available_attrs(caps: Caps) -> list:
    """not_capable-`available` = welche Attribute der Assistent DOCH setzen kann. Nur ASSISTANT-
    ausführbare (∩ EXECUTABLE_ATTRS, Benni 2026-07-14): jede angebotene Alternative ist erfüllbar (rev2-
    Kernwert). v23.6 P3-wire + Batch1a/1b: effect/hvac_mode/preset/oscillate/tilt/swing_mode/fan_mode/
    option + sound_mode/mode/operation/activity/vacuum_fan_speed/direction sind executor-verdrahtet →
    sie erscheinen als Alternativen. Kanon. Reihenfolge (_ATTR_ORDER)."""
    avail = [a for a in caps.settable if a in EXECUTABLE_ATTRS]
    return sorted(avail, key=lambda a: (_ATTR_ORDER.index(a) if a in _ATTR_ORDER else 99, a))[:_ALLOWED_TRUNC_N]


def _clamp(canon, spec: Spec):
    """(effektiver_wert, clamped_flag). done_clamped MELDEN erst jenseits Grenze+MARGIN (§6.5);
    innerhalb der Marge still auf Grenzwert = `done`. Marge: 5pp (pct) bzw. 1 Range-Step."""
    lo, hi = spec.lo, spec.hi
    margin = CLAMP_MARGIN_PCT if spec.unit == "%" else (spec.step or 1)
    if hi is not None and canon > hi:
        return _num_or(hi), (canon > hi + margin)
    if lo is not None and canon < lo:
        return _num_or(lo), (canon < lo - margin)
    return canon, False


def plan_set_state(attr, value, caps: Caps | None):
    """(canon, unit, clamped, err) — set_value_or_error + entity-echte Fähigkeits-/Wert-Prüfung.
    Vorrang (§6.3): (1) Ziel-Fähigkeit `not_capable` → (2) globale Wert-Normalisierung → (3) entity-
    echter Constraint (Range→Klemmung/done_clamped, Enum→geräte-echtes invalid_value).
    caps=None ⇒ reiner set_value_or_error-Fallback (kein Gate — Introspektion nicht verfügbar)."""
    if caps is None:
        canon, unit, err = set_value_or_error(attr, value)
        return canon, unit, False, err
    spec = caps.settable.get(attr)
    if spec is None:                                    # (1) Attribut nicht fähig → not_capable
        return None, None, False, err_not_controllable(attr, available=_available_attrs(caps))
    canon, unit, err = set_value_or_error(attr, value)  # (2) pct/Farb-Synonym/Kelvin + globales invalid
    if err:
        return None, None, False, err                  # z.B. Farbe „gold" (gamut-fremd, globales allowed)
    if spec.kind == "any":
        return canon, unit, False, None
    if spec.kind == "enum":                             # (3a) geräte-echte Enum (AC ohne heat, WLED-effect)
        if canon in spec.values:
            return canon, unit, False, None
        # G1 fuzzy-Resolve (Regen-Strang R6/H3): Case-insensitiv gegen die Geräteliste — Nutzer/Modell
        # variieren Groß/Klein („Dolby Surround"/„dolby surround"); Case bestimmt KEINE Fähigkeit.
        # Rückgabe = exakter Geräte-Case (HA-Service-Wert), invalid_value nur bei echt fremdem Wert.
        _cf = str(canon).lower()
        _hit = next((v for v in spec.values if str(v).lower() == _cf), None)
        if _hit is not None:
            return _hit, unit, False, None
        return None, None, False, err_invalid_value(attr, value, list(spec.values[:_ALLOWED_TRUNC_N]))
    if spec.kind == "range":                            # (3b) Klemmung → done_clamped
        eff, clamped = _clamp(canon, spec)
        return eff, (spec.unit or unit), clamped, None
    return canon, unit, False, None


# ── Shaper (beide call-sites) ──────────────────────────────────────────────────
def shape_turn(names: list) -> dict:
    return ok(targets=names)


# Deferred-Verben (run_routine/manage_list/control_media/control_vacuum/set_timer/announce):
# Ziel-Shaping GETEILT (train==serve). Der HA-Service-/Intent-Dispatch lebt NUR im Executor —
# hier entsteht ausschließlich das Result-JSON, das der Model lernt.
#  · set_timer/announce = ABSTRAKT (Timer/Broadcast laufen im Intent-Layer, area = Dispatch-Detail,
#    kein Geräte-Ziel im Result) → targets=[].
#  · run_routine/manage_list/control_media/control_vacuum = reales Ziel (Szene·Liste·Player·Sauger)
#    → geteilter Resolver → targets=llm_names (konsistent mit turn_on/set_state). Fehler
#    (entity_not_found/ambiguous) fließt aus demselben Resolver → truthful auf beiden Seiten.
_DEFERRED_ABSTRACT = ("set_timer", "announce")
# Deferred-Geräteverben → implizierte Ziel-Domain(s). area-Auflösung liefert SONST den ganzen Raum
# (alle Domains) → auf die semantisch passende Domain einengen (analog narrow_by_attr_domain).
_DEFERRED_DOMAIN = {
    "control_media": ("media_player",),
    "control_vacuum": ("vacuum",),
    "run_routine": ("scene", "script", "automation"),
    "manage_list": ("todo",),
}


def deferred_result(verb: str, args: dict, exposure: dict) -> tuple:
    """(result, eids) für die deferred Verben. eids = aufgelöste Ziel-Entitäten (Executor-Dispatch)
    oder None. Empirie (v22-Master): media/vacuum-Cases tragen IMMER name/area → kein bare-no_targets."""
    if verb in _DEFERRED_ABSTRACT:
        return ok(targets=[]), None
    eids, err = resolve(args, exposure)
    if err:
        return err, None
    doms = _DEFERRED_DOMAIN.get(verb)
    if doms:                                  # area/name → auf die Verb-Domain einengen
        eids = [e for e in eids if exposure[e]["domain"] in doms]
        if not eids:
            return err_no_targets(args.get("name") or args.get("area") or ""), None
    return ok(targets=names_of(exposure, eids)), eids


def shape_set_state(names: list, canon, unit, clamped=False) -> dict:
    out = ok(targets=names, value=canon)
    if unit:
        out["unit"] = unit
    if clamped:                              # v23.5 P1b: done_clamped — echoter Wert = effektiv (geklemmt)
        out["clamped"] = True
    return out


def plan_group_set_state(attr, value, entries: list) -> tuple:
    """Gruppen-set_state über per-Entität-echte Caps → (result, dispatch). Geteilt train==serve.

    `entries`: list[(eid, name, caps|None)] — pro Ziel die aus `capabilities_of` gezogenen Caps.
    Politik (Benni 2026-07-14 „per-Entität → partial"): jede Entität wird EINZELN geplant
    (`plan_set_state`), dann aggregiert:
      · alle ok, EIN einheitlicher (Wert, clamped) → ein `shape_set_state`-Result (ggf. clamped).
      · alle ok, aber Wert/Klemmung divergiert → nur `targets` (Wert wäre mehrdeutig, adjust-Präzedenz).
      · manche ok / manche gescheitert → `partial` (geglückte targets + failed-Liste).
      · alle gescheitert: Einzelziel → roher Fehler (query=name); mehrere → partial mit leeren targets.
    `dispatch` = [(eid, canon, unit)] der geplant-ausführbaren Ziele (Serve dispatcht NUR diese;
    der Generator ignoriert dispatch — er baut kein HA)."""
    planned = [(eid, name, plan_set_state(attr, value, caps)) for eid, name, caps in entries]
    ok_items = [(eid, name, r[0], r[1], r[2]) for eid, name, r in planned if r[3] is None]
    failed = [(name, r[3]) for _, name, r in planned if r[3] is not None]
    dispatch = [(eid, canon, unit) for eid, name, canon, unit, _ in ok_items]

    if not failed:                                   # alle fähig + im gültigen Bereich
        names = [n for _, n, _, _, _ in ok_items]
        shapes = {(c, cl, u) for _, _, c, u, cl in ok_items}
        if len(shapes) == 1:                         # einheitlicher effektiver Wert → zitierbar
            canon, clamped, unit = next(iter(shapes))
            return shape_set_state(names, canon, unit, clamped), dispatch
        return ok(targets=names), dispatch           # divergent → Gruppe, Wert weglassen (mehrdeutig)

    ok_names = [n for _, n, _, _, _ in ok_items]
    failed_wire = [_failed_entry(n, err) for n, err in failed]
    if not ok_items:                                 # Total-Fehler
        if len(failed) == 1:
            name, err = failed[0]                    # Einzelziel: roher Fehler, query→name (say-Subject)
            if err.get("error") == "not_controllable":
                return err_not_controllable(name, available=err.get("available")), dispatch
            return err, dispatch                     # invalid_value trägt param/given/allowed (kein query nötig)
        return shape_partial([], failed_wire), dispatch
    return shape_partial(ok_names, failed_wire), dispatch


def adjust_delta(attr, amount, direction):
    """Vorzeichenbehaftetes Delta für ein relatives Verstellen (temperature/position/pct)."""
    sign = 1 if direction == "up" else -1
    table = STEP_DEG if attr == "temperature" else STEP_PCT
    return sign * _step(amount, table)


def shape_adjust(names: list, before: dict, after: dict, eids: list, unit) -> dict:
    """Relatives Verstellen → Result. Echot den RESULTIERENDEN Wert (after-Read) NUR bei
    eindeutigem Einzelziel (Gruppe → mehrdeutig, nur targets). `at_limit` = kein Effekt
    (after == before, echter Anschlag) — NICHT bei clamped (Audit B4)."""
    out = ok(targets=names)
    if len(eids) == 1:
        e = eids[0]
        val = after.get(e)
        if val is not None:
            out["value"] = _num(val)
            if unit:
                out["unit"] = unit
            if before.get(e) is not None and val == before[e]:
                out["at_limit"] = True
    return out


def read_attr(read: dict, attr) -> tuple:
    """(value, unit, effektives-attribut) für einen State-Read + gefragtes Attribut.
    `read` = {"state":..., "attributes":{...}} (StateProvider-Form)."""
    a = (read or {}).get("attributes", {})
    state = (read or {}).get("state")
    if attr in (None, "state"):
        return state, None, "state"
    if attr == "temperature":
        # climate trägt den Wert in attributes.temperature/current_temperature; ein Temperatur-
        # SENSOR trägt ihn im state (attributes = uom/device_class). Beide Formen lesen.
        v = a.get("temperature", a.get("current_temperature"))
        if v is None and state not in (None, "", "unavailable", "unknown"):
            try:
                v = float(state)
            except (TypeError, ValueError):
                v = None
        return _num(v) if isinstance(v, float) else v, a.get("unit_of_measurement", "°C"), "temperature"
    if attr == "brightness":
        b = a.get("brightness")
        return (round(b / 255 * 100) if b is not None else None), "%", "brightness"
    if attr == "position":
        return a.get("current_position"), "%", "position"
    if attr == "open":
        return (state == "open"), None, "open"
    # generischer numerischer Sensor-Read (humidity/illuminance/battery/power/…):
    # Einheit aus unit_of_measurement (H8 — nie erfinden).
    unit = a.get("unit_of_measurement")
    if unit is not None:
        try:
            v = float(state)
            return _num(v), unit, attr
        except (TypeError, ValueError):
            return state, unit, attr
    return state, None, "state"


def adj_read(read: dict, attr) -> tuple:
    """(wert, unit) des adjust-relevanten Attributs — Vorher/Nachher-Echo."""
    a = (read or {}).get("attributes", {})
    if attr == "brightness":
        b = a.get("brightness")
        return (round(b / 255 * 100) if b is not None else None), "%"
    if attr == "volume":
        v = a.get("volume_level")
        return (round(v * 100) if v is not None else None), "%"
    if attr == "temperature":
        v = a.get("temperature")
        return (_num(v) if isinstance(v, float) else v), "°C"
    if attr == "position":
        return a.get("current_position"), "%"
    return None, None


def shape_datetime(now) -> dict:
    return ok(reading={"attribute": "datetime",
                       "date": now.strftime("%Y-%m-%d"),
                       "time": now.strftime("%H:%M"),
                       "weekday": now.strftime("%A")})


# ── Weather (Bahn-2, v23.2) — geteilter Block-Builder = Single-Source ──────────
# Wetter ist ein Read-Verb (get_state attribute="weather"). Der Executor holt live
# `weather.get_forecasts`, der Generator echte InfluxDB-Folgetage → BEIDE mappen auf
# denselben normalisierten Struct und rufen denselben Builder → byte-identischer Block
# (train==serve, wie read_attr). Block sitzt im `value` eines readings-Eintrags →
# kein RESULT_SCHEMA-Bruch (readings existiert, value darf String sein).
#
# ⚠ Regel (WEATHER_CONCEPT.md): der Builder nutzt NUR Felder, die BEIDE Quellen liefern
# (condition, high, low). precipitation liefert InfluxDB NICHT → Regen QUALITATIV aus der
# Condition (nie ein mm-Wert, den das Training nicht reproduziert). Actionable Aggregate
# ("Schirm sinnvoll") stehen als GELABELTE Zeile, nicht inline pro Tag (350m band inline-
# Urteile sonst an den falschen Tag — Probe 2026-07-11).
_COND_DE = {
    "clear-night": "klar", "cloudy": "bewölkt", "fog": "neblig", "hail": "Hagel",
    "lightning": "Gewitter", "lightning-rainy": "Gewitter mit Regen",
    "partlycloudy": "wechselnd bewölkt", "pouring": "starker Regen", "rainy": "regnerisch",
    "snowy": "Schnee", "snowy-rainy": "Schneeregen", "sunny": "sonnig",
    "windy": "windig", "windy-variant": "windig", "exceptional": "extrem",
}
# Nass = Schirm/Regenschutz sinnvoll (actionable-Aggregat + faktisches Per-Tag-Wort)
_WET_RAIN = {"rainy", "pouring", "lightning-rainy", "lightning", "hail"}
_WET_SNOW = {"snowy", "snowy-rainy"}
_WD_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]   # date.weekday(): Mo=0
_REL_DE = ["Heute", "Morgen", "Übermorgen"]           # days[i] positional: 0=heute


def _cond_de(cond) -> str:
    return _COND_DE.get(cond, cond or "unbekannt")


def _wd_de(iso_date) -> str | None:
    """ISO-Datum ("2026-06-20") → deutsches Wochentags-Kürzel (locale-frei, deterministisch)."""
    if not iso_date:
        return None
    try:
        return _WD_DE[_date.fromisoformat(iso_date).weekday()]
    except (TypeError, ValueError):
        return None


def _t(x):
    """Temperatur-Anzeige: auf ganze Grad runden (Block ist Vorlese-Text, keine Präzision)."""
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return None


def _precip_word(cond) -> str:
    if cond in _WET_SNOW:
        return "Schnee"
    if cond in _WET_RAIN:
        return "Regen"
    return "trocken"


def _temp_range(lo, hi) -> str:
    """Tief–Hoch als Vorlese-Spanne. Bei negativem Tief „bis" statt en-dash — „-4–1°" kollidiert
    optisch (Minus/Strich); „-4 bis 1°" ist eindeutig. Sonst en-dash (gelockte Form „20–32°")."""
    lo_i, hi_i = _t(lo), _t(hi)
    if lo_i is not None and hi_i is not None and lo_i != hi_i:
        sep = " bis " if lo_i < 0 else "–"
        return f"{lo_i}{sep}{hi_i}°"
    if hi_i is not None:
        return f"{hi_i}°"
    if lo_i is not None:
        return f"{lo_i}°"
    return "?"


def build_weather_block(struct: dict) -> str:
    """Normalisierter Wetter-Struct → tag-geankerter Vorlese-Block (B2). Pure/deterministisch.

    struct = {"now": {"cond": str, "temp": num}?,           # optional aktueller Zustand
              "days": [{"cond": str, "high": num, "low": num, "date": "YYYY-MM-DD"?}, ...]}
    days sind POSITIONAL: [0]=heute, [1]=morgen, [2]=übermorgen (max 3 genutzt).
    Gemeinsame Felder (train UND serve): cond/high/low. Regen qualitativ aus cond."""
    lines = []
    now = struct.get("now") or {}
    if now.get("cond") is not None:
        nt = _t(now.get("temp"))
        temp = f", ~{nt}°" if nt is not None else ""
        lines.append(f"Jetzt: {_cond_de(now.get('cond'))}{temp}.")

    days = (struct.get("days") or [])[:3]
    for i, d in enumerate(days):
        rel = _REL_DE[i] if i < len(_REL_DE) else f"Tag+{i}"
        wd = _wd_de(d.get("date"))
        head = f"{rel} ({wd})" if wd else rel
        span = _temp_range(d.get("low"), d.get("high"))
        lines.append(f"{head}: {_cond_de(d.get('cond'))}, {span}, {_precip_word(d.get('cond'))}")

    # ── Aggregate (deterministisch vorgebacken, gelabelt — nicht inline) ──
    hi_days = [(i, _t(d.get("high"))) for i, d in enumerate(days) if _t(d.get("high")) is not None]
    if len(days) >= 2 and hi_days:
        wi, wh = max(hi_days, key=lambda t: t[1])
        rel = (_REL_DE[wi] if wi < len(_REL_DE) else f"Tag+{wi}").lower()
        lines.append(f"Wärmster Tag: {rel} ({wh}°).")
    wet = [(_REL_DE[i] if i < len(_REL_DE) else f"Tag+{i}").lower()
           for i, d in enumerate(days) if d.get("cond") in _WET_RAIN or d.get("cond") in _WET_SNOW]
    if wet:
        lines.append(f"Schirm sinnvoll: {', '.join(wet)}.")

    return "\n".join(lines)


def shape_weather(name: str, struct: dict) -> dict:
    """Read-Result fürs Wetter: der Block sitzt im `value` eines readings-Eintrags.
    Beide Seiten (Executor/Generator) rufen dies → identisches Result-JSON (train==serve)."""
    return ok(readings=[{"name": name, "attribute": "weather",
                         "value": build_weather_block(struct)}])


# ── Sonnenstand (v23.2) — flacher Read (datetime-Geschwister, kein cap-v2) ────
# Basic: heutiger Auf-/Untergang + is_dark (vorgebacken). Serve liest sun.sun (state=
# above/below_horizon + next_rising/next_setting), Train berechnet die Zeiten astronomisch
# (sun_times.py) — beide füllen dasselbe flache reading (train==serve auf der FORM, Werte
# dürfen divergieren wie bei Weather). is_dark ist die deterministische Vorkau-Antwort auf
# „ist es dunkel?" (Modell rechnet nicht).
def _min_hhmm(s):
    """„HH:MM"(:SS) → Minuten-nach-Mitternacht, oder None."""
    try:
        h, m = str(s).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def shape_sun(sunrise, sunset, is_dark=None) -> dict:
    """Flaches Sonnenstand-reading {attribute:"sun", sunrise, sunset[, is_dark]}. sunrise/sunset =
    lokale „HH:MM". is_dark (bool) nur wenn bekannt (Serve: sun.sun-state; Train: now vs Zeiten)."""
    r = {"attribute": "sun", "sunrise": sunrise, "sunset": sunset}
    if is_dark is not None:
        r["is_dark"] = bool(is_dark)
    return ok(reading=r)


def shape_get_state(attr, aggregate, reads: list) -> dict:
    """reads = list[{"name":str, "state":str, "attributes":{...}}] (schon aufgelöst+gelesen).
    Baut readings / aggregate (count/any/all/avg/min/max) nach RESULT_SCHEMA §2b."""
    if aggregate == "count":
        return ok(aggregate="count", value=len(reads))

    readings, numeric, on_flags = [], [], []
    for r in reads:
        val, unit, a = read_attr(r, attr)
        readings.append({"name": r["name"], "attribute": a, "value": val,
                         **({"unit": unit} if unit else {})})
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            numeric.append(val)
        on_flags.append(str(r.get("state")).lower() in ON_STATES)

    if aggregate in ("any", "all"):
        v = (any(on_flags) if aggregate == "any" else all(on_flags))
        detail = [readings[i]["name"] for i, f in enumerate(on_flags) if f != v]
        out = ok(aggregate=aggregate, value=v)
        if detail:
            out["detail"] = detail[:3]
        return out
    if aggregate in ("avg", "min", "max") and numeric:
        agg = (sum(numeric) / len(numeric) if aggregate == "avg"
               else min(numeric) if aggregate == "min" else max(numeric))
        return ok(aggregate=aggregate, value=_num(round(agg, 1)))

    if not readings:
        return err_no_data("")
    return ok(readings=readings)


# ── Exposure-Bau aus dem kanonischen Haus (train-Seite; serve baut aus HA-Registry) ──
def exposure_from_house(house) -> dict:
    """hestia_cap.House → exposure-Dict {eid: {llm_name, aliases, domain, area, floor}}.
    eids sind synthetisch/deterministisch (kein echtes HA-entity_id nötig — resolve nutzt sie
    nur als opaque Schlüssel). Serve baut ein äquivalentes Dict aus der echten HA-Registry."""
    exp = {}
    n = 0
    for area in house.areas:
        for e in area.entities:
            eid = f"e{n}"
            n += 1
            exp[eid] = {"llm_name": e.name, "aliases": list(e.aliases),
                        "domain": e.domain, "area": area.name, "floor": area.floor}
    return exp


def states_from_house(house) -> dict:
    """hestia_cap.House → {eid: {"state","attributes"}} — der Sim-State-Store des Action-Pfads
    (Cap-Haus, Phase 4). eid-Vergabe BYTE-IDENTISCH zu exposure_from_house (gleiche Iteration) →
    `states[eid]` und `exposure[eid]` bezeichnen dieselbe Entität. Serve baut das Äquivalent aus
    der echten HA-Registry (`hass.states.get` je eid). Entitäten OHNE Cap-Profil (leeres attributes)
    liefern `{}` ⇒ capabilities_of → konservativ (kein Gate). Beide Seiten speisen dieselbe reine
    Funktion `capabilities_of` → Parität by-construction (wie read_attr)."""
    st = {}
    n = 0
    for area in house.areas:
        for e in area.entities:
            st[f"e{n}"] = {"state": e.state, "attributes": dict(e.attributes or {})}
            n += 1
    return st


# ── v23.4 `say`-Feld: natürlichsprachige Executor-Wahrheit im Result (train==serve) ──
# Der Executor kennt als Einziger die AUSGEFÜHRTE Wahrheit (Ziel+Aktion+Wert) und legt sie als
# fertige Phrase (`say`) ins Erfolgs-Result. Das Modell formuliert `say` um statt Entity/Aktion
# selbst zu GENERIEREN → fixt den Say-vs-Do-Gap. KANONISCH: Generator (train) UND Serve-Executor
# rufen beide `with_say` → keine Divergenz mehr (Reconcile 2026-07-13, war v23.4-Deployment-Gap).
_COLOR_DE = {
    "warm_white": "warmweiß", "cold_white": "kaltweiß", "white": "weiß", "red": "rot",
    "green": "grün", "blue": "blau", "yellow": "gelb", "orange": "orange",
    "purple": "lila", "pink": "pink", "cyan": "türkis", "violet": "lila", "magenta": "magenta",
}
_TURN_SAY = {"turn_on": "eingeschaltet", "turn_off": "ausgeschaltet", "stop": "gestoppt"}
_SET_PCT_VERB = {"brightness": "gedimmt", "position": "gefahren"}   # sonst "gestellt"
_UNIT_WORD = {"°C": "Grad", "K": "Kelvin", "%": "Prozent"}
_MEDIA_SAY = {"pause": "pausiert", "play": "gestartet", "stop": "gestoppt", "next": "übersprungen",
              "previous": "zurückgesetzt", "volume_up": "lauter gestellt", "volume_down": "leiser gestellt",
              "mute": "stummgeschaltet", "unmute": "wieder laut gestellt"}
_VACUUM_SAY = {"start": "losgeschickt", "stop": "gestoppt", "pause": "pausiert",
               "return": "zurück zur Basis geschickt", "return_to_base": "zurück zur Basis geschickt",
               "locate": "geortet", "clean_area": "losgeschickt", "clean": "losgeschickt",
               "clean_room": "losgeschickt", "clean_spot": "losgeschickt"}


def _fmt_num(v) -> str:
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def _color_de(c) -> str:
    return _COLOR_DE.get(str(c).strip().lower(), str(c))


def _say_entity(targets: list, args: dict):
    """Ziel-Phrase aus den aufgelösten Zielen (dedupt, Reihenfolge-stabil)."""
    uniq = list(dict.fromkeys(targets or []))
    if not uniq:
        return None
    return uniq[0] if len(uniq) == 1 else " und ".join(uniq)


# ── v23.5 Phase 4 — say-Render der dyn. Executor-Effekte (§6.3, geteilt train==serve) ──
# Attribut → deutsches Nomen (für not_capable-`available` + not_capable-Verneinung). KANONISCH
# hier (eine Stelle, §6.5-Zahl-/Wort-Lokalisierung), NICHT in 30 Templates.
# Nicht-Enum-Attrs explizit; die Enum-Listen-Attrs (effect/hvac_mode/preset/fan_mode/swing_mode/
# option) kommen aus der Spec-Tabelle (cap_attrs.DE_NOUN/DE_NEG — Genus dort gepflegt). Merge ist
# order-frei (reine Lookup-Map).
_ATTR_DE = {"color": "Farbe", "brightness": "Helligkeit", "color_temp": "Weißton",
            "temperature": "Temperatur", "volume": "Lautstärke", "position": "Position",
            "fan_speed": "Geschwindigkeit", "tilt": "Neigung", "oscillate": "Schwenken",
            "humidity": "Luftfeuchte", "value": "Wert", "source": "Quelle",
            "direction": "Richtung",             # v23.6 Batch1b (oscillate-Klasse, kein Tabellen-Attr)
            **cap_attrs.DE_NOUN}
_ATTR_NEG_DE = {"color": "keine Farbe", "brightness": "keine Helligkeit", "color_temp": "keinen Weißton",
                "temperature": "keine Temperatur", "volume": "keine Lautstärke",
                "position": "keine Position", "fan_speed": "keine Geschwindigkeit",
                "oscillate": "kein Schwenken", "tilt": "keine Lamellen-Neigung",
                "direction": "keine Laufrichtung",
                **cap_attrs.DE_NEG}


def _join_de(items) -> str:
    """[a,b,c] → „a, b und c" (deutsche Aufzählung, Reihenfolge-stabil)."""
    xs = [x for x in items if x]
    if not xs:
        return ""
    if len(xs) == 1:
        return xs[0]
    return ", ".join(xs[:-1]) + " und " + xs[-1]


def _clamp_direction(requested, effective) -> str:
    """Klemm-Richtung fürs done_clamped-say: „mehr/weniger geht nicht". requested (args.value) vs
    effektiver (geklemmter) Wert. min/max-Wortmarken werden auf die Richtung abgebildet."""
    try:
        return "up" if float(requested) > float(effective) else "down"
    except (TypeError, ValueError):
        if requested == "min":
            return "down"
        return "up"                              # „max"/unbekannt → oberes Limit (häufigster Fall)


def _clamp_suffix(phrase: str, args: dict, effective, r: dict) -> str:
    """done_clamped: „…auf 100 Prozent — mehr geht nicht" (§6.3). Nur wenn clamped:true."""
    if not r.get("clamped"):
        return phrase
    d = _clamp_direction(args.get("value"), effective)
    return phrase + (" — mehr geht nicht" if d == "up" else " — weniger geht nicht")


def _not_capable_say(args: dict, r: dict) -> str:
    """§6.3 not_capable: „Die Deckenlampe kann keine Farbe — nur Helligkeit und Weißton." Subjekt =
    `query` (der Ziel-Name, aus plan_group bei Einzelziel), Attribut aus args, available aus dem Result."""
    name = r.get("query") or "Das Gerät"
    attr = args.get("attribute")
    neg = _ATTR_NEG_DE.get(attr, f"kein {_ATTR_DE.get(attr, attr)}")
    avail = _join_de(_ATTR_DE.get(a, a) for a in (r.get("available") or []))
    base = f"{name} kann {neg}"
    return f"{base} — nur {avail}." if avail else f"{base}."


def _fail_clause(f: dict) -> str:
    """Kurz-Klausel für einen partial-`failed`-Eintrag (Ziel + Grund)."""
    name = f.get("name") or "Ein Gerät"
    err = f.get("error")
    if err == "not_controllable":
        av = _join_de(_ATTR_DE.get(a, a) for a in (f.get("available") or []))
        return f"{name} kann das nicht" + (f" — nur {av}" if av else "")
    if err == "unavailable":
        return f"{name} war nicht erreichbar"
    if err == "invalid_value":
        given = f.get("given")
        if f.get("param") == "color":            # DE-Lokalisierung wie Single-Call (cyan → türkis)
            given = _color_de(given)
        return f"{name}: {given} geht nicht"
    return f"{name} hat nicht geklappt"


def _partial_say(verb: str, args: dict, r: dict):
    """§6.3 partial: geglückte Ziele + gescheiterte Gründe in EINER Phrase (Truthfulness §4: beide
    Seiten nennen). Wert-frei für die geglückten (Gruppen-Wert mehrdeutig) — nur die Aktion."""
    ok_names = list(dict.fromkeys(r.get("targets") or []))
    parts = []
    if ok_names:
        ent = _join_de(ok_names)
        verb_word = _TURN_SAY.get(verb)          # turn_on/off/stop → ein-/ausgeschaltet/gestoppt
        parts.append(f"{ent} {verb_word}" if verb_word else f"{ent} eingestellt")
    parts += [_fail_clause(f) for f in (r.get("failed") or [])]
    parts = [p for p in parts if p]
    return "; ".join(parts) if parts else None


def partial_say(result: dict):
    """say für ein AGGREGIERTES partial-Result (Multi-Call / verb-loses Aggregat) — targets (erledigt)
    + failed (Gründe). Verb-frei (Multi-Call mischt Verben) → generische Erfolgs-Phrase. Geteilt,
    damit Generator (action_result) und Serve (execute_calls) byte-identisch `say` ans Aggregat hängen."""
    return _partial_say(None, {}, result)


# ── B1 Failure-say (v23.5): truthful phrase für Sackgassen-Fehler von Aktions-Verben ──
# Ohne say halluziniert das 350M Erfolg bei ok:false (der EINE echte Truthfulness-Fehler der Bench,
# Cases succ#36: turn_off Erdgeschoss → {ok:false,no_targets} → Modell „das Licht ist aus"). Wir geben
# dem Modell eine wahre Phrase zum Umformulieren. NUR „Sackgassen"-Fehler ohne Klärungspfad; Klärungs-
# Fehler (ambiguous, entity_not_found+did_you_mean, invalid_value) bleiben None → Gold trägt die
# „?"-Rückfrage (H, P1b-Enrichment). unsafe bleibt None → refuse-Rubrik/Gold. Read-Fehler (no_data)
# erreichen say_for_call nie (Reads laufen ohne with_say). Phrasen an _FAIL_MARKERS (Generator) geerdet.
_FAIL_SAY = {
    "no_targets": "Das hat nicht geklappt — ich habe kein passendes Gerät gefunden.",
    "not_controllable": "Das lässt sich nicht steuern.",
    "timeout": "Das hat gerade nicht funktioniert.",
    "unparseable": "Das hat gerade nicht funktioniert.",
}


def fail_say_for_call(verb: str, r: dict):
    """Wahrheits-Phrase für einen Sackgassen-Fehler (kein Klärungspfad) eines Aktions-Verbs.
    None → Klärungs-Fehler (dym/ambiguous/invalid_value), unsafe, oder unbekannter Code → Gold trägt es."""
    err = r.get("error")
    if err == "entity_not_found":
        if r.get("did_you_mean"):
            return None                      # → Klärung „meintest du X?" (Gold, endet auf „?")
        q = r.get("query")
        return f"Ich habe {q} nicht gefunden." if q else _FAIL_SAY["no_targets"]
    if err == "unavailable":
        q = r.get("query")
        return f"{q} ist gerade nicht erreichbar." if q else "Das Gerät ist gerade nicht erreichbar."
    return _FAIL_SAY.get(err)


def say_for_call(verb: str, args: dict, r: dict):
    """Deterministische Wahrheits-Phrase aus (Verb, Args, Result-Ziele/Wert). None → kein `say`
    (Klärungs-/Read-Fehler oder Fälle ohne eindeutige Ausführungs-Wahrheit → Gold trägt sie)."""
    if r.get("failed") is not None:              # v23.5 P4: partial (Gruppen-set_state, ok:false + failed)
        return _partial_say(verb, args, r)
    if not r.get("ok"):
        if verb == "set_state" and r.get("error") == "not_controllable" and r.get("available"):
            return _not_capable_say(args, r)     # v23.5 P4: not_capable mit geräte-echtem available (§6.3)
        return fail_say_for_call(verb, r)
    ent = _say_entity(r.get("targets") or [], args)
    if verb in _TURN_SAY:
        return f"{ent} {_TURN_SAY[verb]}" if ent else None
    if verb == "set_state":
        if not ent:
            return None
        attr, val, unit = args.get("attribute"), r.get("value"), r.get("unit")
        if attr == "color":
            return f"{ent} auf {_color_de(val)} gestellt"
        if attr == "lock":
            return (f"{ent} abgeschlossen" if val == "locked" else
                    f"{ent} aufgeschlossen" if val == "unlocked" else f"{ent} auf {val} gestellt")
        if attr == "open":
            return f"{ent} geöffnet" if val else f"{ent} geschlossen"
        if attr == "oscillate":       # v23.6 P3-wire: ONOFF-canon nicht roh zitieren („auf on gestellt")
            return f"{ent} schwenkt jetzt" if val == "on" else f"{ent} schwenkt nicht mehr"
        if attr == "direction":       # v23.6 Batch1b: Fix-Enum forward/reverse nicht roh zitieren
            return f"{ent} läuft jetzt vorwärts" if val == "forward" else f"{ent} läuft jetzt rückwärts"
        if unit == "%":
            return _clamp_suffix(f"{ent} auf {_fmt_num(val)} Prozent {_SET_PCT_VERB.get(attr, 'gestellt')}",
                                 args, val, r)
        if unit in ("°C", "K"):
            return _clamp_suffix(f"{ent} auf {_fmt_num(val)} {_UNIT_WORD[unit]} gestellt", args, val, r)
        return f"{ent} auf {val} gestellt" if val is not None else None
    if verb == "adjust":
        val, unit = r.get("value"), r.get("unit")
        if not ent or r.get("at_limit"):
            return None                       # Anschlag/Gruppe → value-freie Gold-Richtungsantwort
        if unit and isinstance(val, (int, float)) and not isinstance(val, bool):
            return f"{ent} auf {_fmt_num(val)} {_UNIT_WORD.get(unit, unit)} gestellt"
        return None
    if verb == "manage_list":
        item = (args.get("item") or "").strip()
        if not item:
            return None
        lst = (r.get("targets") or [args.get("name", "")])[0]
        return (f"{item} zu {lst} hinzugefügt" if args.get("action", "add") == "add"
                else f"{item} von {lst} entfernt")
    if verb == "control_media":
        act = args.get("action")
        content = (args.get("content") or "").strip()
        if act in ("play_content", "play_media", "play") and content:
            return f"{content} auf {ent} gestartet" if ent else f"{content} gestartet"
        w = _MEDIA_SAY.get(act)
        return f"{ent} {w}" if ent and w else None
    if verb == "control_vacuum":
        w = _VACUUM_SAY.get(args.get("action"))
        return f"{ent} {w}" if ent and w else None
    if verb == "run_routine":
        return f"{ent} ausgeführt" if ent else None
    if verb == "set_timer":
        act = args.get("action", "set")
        dur = args.get("duration")
        if act == "set":
            return f"Timer über {dur} gestellt" if dur else "Timer gestellt"
        if act == "cancel":
            return "Timer abgebrochen"
        if act == "cancel_all":
            return "Alle Timer abgebrochen"
        if act == "pause":
            return "Timer pausiert"
        if act == "resume":
            return "Timer fortgesetzt"
        if act == "add":
            return f"Timer um {dur} verlängert" if dur else "Timer verlängert"
        if act == "subtract":
            return f"Timer um {dur} verkürzt" if dur else "Timer verkürzt"
        return None                          # check → Gold trägt die Restzeit (remaining erst P2)
    if verb == "announce":
        return "Durchsage abgespielt"
    return None


def with_say(r: dict, verb: str, args: dict) -> dict:
    """Hängt `say` an ein Erfolgs-Result (kopiert, um geteilte Shaper-Dicts nicht zu mutieren)."""
    s = say_for_call(verb, args, r)
    if s:
        r = dict(r)
        r["say"] = s
    return r
