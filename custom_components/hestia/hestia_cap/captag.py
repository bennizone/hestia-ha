"""Cap-Tag-Renderer (v23.6 P1, r4) — kompakte Geräte-Fähigkeits-Tags im Haus-Block.

Zweck: das Modell soll die Fähigkeiten eines Geräts KENNEN, statt blind zu handeln und auf
Executor-Korrektur zu hoffen — für proaktive Wahrhaftigkeit (kein „mach blau" an einer ct-only-
Lampe) und Disambiguierung (nur EINE von zwei Lampen kann Farbe).

Naht (train==serve): der Tag wird im statischen Prefix gerendert (render._entity_token) und ist
damit byte-identisch, WENN beide Seiten dieselbe `House` mit denselben `Entity.attributes` füttern.
  ✓ SERVE-WIRING ERLEDIGT (P1b, Batch1a 2026-07-15): `hestia-ha/house_builder.py::_cap_attributes`
    reicht cap-relevante Attribute aus der stabilen entity_registry-Capability (`entry.capabilities`
    + `supported_features`, NICHT Live-State — kein Flattern bei `unavailable`) in Entity.attributes;
    Cap-Tag rendert serve==train. Paritäts-Test über die ECHTE Serve-Bau-Route in hestia-ha.
  R5-Lock: kein Precompute/Store-Cache — der Tag wird pro Render aus den House-Attributen erzeugt.

Design-Entscheidungen (P1 — Fable+Opus-reviewt 2026-07-15; Divergenzen ggü. X-Sweep-Prototyp bewusst):
  D1 **Diskriminatoren aus `capabilities_of`** (⇒ Tag==Executor by-construction): was der Tag als
     fähig ausweist, akzeptiert auch der Executor (dieselbe Quelle). `src` wird zusätzlich per
     SELECT_SOURCE-Bit gegated (caps kennt kein source-Settable → sonst Over-Claim, Fable#6).
  D2 **Advertiser-Wertlisten** (effect/source/preset) aus ROHEN `Entity.attributes` (Geräte-Order);
     **hvac-Werte aus caps** (kanonisch `_ordered`). Schwelle **X=8** (GELOCKT 2026-07-15, X-Sweep):
     ≤8 Werte → inline, >8 → `labelN` (nur Größe → Modell introspiziert via get_state).
  D3 **Leere Attribute ⇒ leerer Tag** (byte-identisch zu r3; konservativer caps-Fallback würde sonst
     jede attributlose Lampe mit ':dim' taggen). Hinweis: auf Live-HA ist `attributes` selten leer
     (friendly_name) → D3 greift v.a. für alte/attributlose Fixtures; das Serve-Wiring (s.o.) muss
     die richtigen Attribute liefern, nicht bloß irgendeinen State.
  D4 **`any`-kind-Caps** (unbekannte Farb-Modi/hvac) werden NICHT beworben (still → introspizieren/
     klären) statt over-zu-claimen. Tag ⊆ Executor-akzeptiert (konservativ Richtung False-Negative).
  D5 **fan_speed** ist in caps ein §2-Fallback (IMMER da) → nicht-unterscheidend, nicht gerendert;
     die speed-vs-preset-only-Wahrheit kommt mit L6 (vor P10).
  D6 **Domain-Scope** = {light, climate, fan, media_player, cover, select} (select v23.6 Batch1a nach
     P4-Coverage-Audit ergänzt — options ist bimodal wie effect_list, G1). climate trägt jetzt zusätzlich
     fan_modes/swing_modes (Batch1a G3/G2). number/humidifier + Growth-Domains folgen in Batch1b.
  D7 **Sanitisierung** (Review Opus#1/Fable#7): geräte-kontrollierter Advertiser-Text (source/effect/
     preset-Namen) wird von Struktur-Zeichen (`/ · : [ ]` + Whitespace/Newline) befreit, bevor er in
     die Tag-Syntax gejoint wird — sonst fälscht `Rock/Pop` die Listenlänge/X=8 oder bricht `]` das Token.

SEQUENZ (advertised⊆executable, Benni-GO 2026-07-15): der Tag bewirbt effect/hvac_mode/preset/oscillate/
tilt (P3-wire) + swing_mode/fan_mode/option (Batch1a) — alle sind executor-verdrahtet (result.py
`EXECUTABLE_ATTRS`, executor `_dispatch_attr`), der Tag bewirbt also nur Ausführbares. Nichts mehr im
Tag-Scope deferred; Growth-Domains (vacuum/humidifier/…) folgen in Batch1b.
"""
from __future__ import annotations

import re

from . import cap_attrs
from .result import capabilities_of

CAP_TAG_X = 8   # Inline-Schwelle GELOCKT (2026-07-15, X-Sweep): len(werte)≤8 → inline, >8 → labelN
_SELECT_SOURCE = 2048   # MediaPlayerEntityFeature.SELECT_SOURCE (D1-Gate für src)
_STRUCT = re.compile(r"[/·:\[\]\r\n\t]+")   # Tag-Struktur-Zeichen (D7)

# Advertiser-Paare (tag_label, list_key) aus der Spec-Tabelle — Single-Source (Byte-identisch zu den
# alten Literalen). Der Domain-Block bleibt HAND-strukturiert (Byte-Order = Position der _adv-Aufrufe
# hier, §10.2), aber die Label→list_key-Zuordnung kommt aus cap_attrs → Batch-1b-Advertiser = eine
# Tabellen-Zeile. Nur Zeilen MIT tag_label (Filter): hvac_mode (tag_label="") + src (kein Settable)
# werden hand-gerendert → ein versehentliches _adv(a,"hvac_mode") knallt als KeyError statt still
# einen kaputten Tag zu rendern.
_ADV_PAIRS = {r.attr: (r.tag_label, r.list_key) for r in cap_attrs.ENUM_CAP_ATTRS if r.tag_label}


def _adv(a: dict, attr: str, x: int) -> str | None:
    """`label:v1/v2/…` (≤x) bzw. `labelN` für ein tabellen-getriebenes Advertiser-Attribut."""
    label, list_key = _ADV_PAIRS[attr]
    return _lst(label, a.get(list_key), x)


def _san(s) -> str:
    """Geräte-Text tag-sicher machen (D7): Struktur-Zeichen → Space, Whitespace kollabiert, gestrippt."""
    return re.sub(r"\s+", " ", _STRUCT.sub(" ", str(s))).strip()


def _g(x) -> str:
    """Zahl kompakt rendern (16 statt 16.0)."""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def _lst(label: str, vals, x: int) -> str | None:
    """`label:v1/v2/…` bei ≤x Werten (sanitisiert), sonst `labelN` (Größe). Leer/None ⇒ None."""
    v = [w for w in (_san(w) for w in (vals or [])) if w]
    if not v:
        return None
    return f"{label}:{'/'.join(v)}" if len(v) <= x else f"{label}{len(v)}"


def cap_tag(domain: str, attributes: dict | None, x: int = CAP_TAG_X) -> str:
    """Kompakter Fähigkeits-Tag für EINE Entität, oder "" (kein Tag). Rückgabe mit führendem ':'
    → passt in `name[domain{tag}]` (z.B. `Stehlampe[light:rgb·fx:Party/Solid]`). Diskriminatoren aus
    `capabilities_of` (D1), Advertiser-Listen aus `attributes` (D2), sanitisiert (D7). Leer ⇒ "" (D3)."""
    a = attributes or {}
    if not a:                                    # D3: keine Introspektion → kein Tag (r3-identisch)
        return ""
    caps = capabilities_of(domain, {"attributes": a})
    s = caps.settable
    parts: list[str] = []

    if domain == "light":
        col = "color" in s and s["color"].kind == "enum"          # konkrete Farbe (nicht 'any', D4)
        ct = "color_temp" in s and s["color_temp"].kind == "range"
        if "brightness" not in s:
            parts.append("on/off")                                 # onoff-only (keine Helligkeit)
        else:
            parts.append("rgb+ct" if (col and ct) else "rgb" if col else "ct" if ct else "dim")
        fx = _adv(a, "effect", x)                                  # Advertiser aus Tabelle (RAW-Order, D2/D7)
        if fx:
            parts.append(fx)

    elif domain == "climate":
        hv = s.get("hvac_mode")
        if hv is not None and hv.kind == "enum":                   # kanonisch _ordered aus caps (D2)
            modes = [_san(m) for m in hv.values if m != "off"]     # off ist universell → weglassen
            modes = [m for m in modes if m]
            if modes:
                parts.append("/".join(modes) if len(modes) <= x else f"mode{len(modes)}")
        t = s.get("temperature")
        if t is not None and t.kind == "range" and t.lo is not None and t.hi is not None:
            parts.append(f"{_g(t.lo)}-{_g(t.hi)}")                 # beide Enden nötig (kein '16-None')
        pre = _adv(a, "preset", x)                                 # Advertiser aus Tabelle (RAW-Order, D2/D7)
        if pre:
            parts.append(pre)
        fm = _adv(a, "fan_mode", x)                                # v23.6 Batch1a: climate-Lüftermodus (≠ fan-Domain)
        if fm:
            parts.append(fm)
        sw = _adv(a, "swing_mode", x)                              # v23.6 Batch1a: Schwenk-Modus
        if sw:
            parts.append(sw)

    elif domain == "fan":
        pre = _adv(a, "preset", x)                                 # D5: fan_speed nicht rendern
        if pre:
            parts.append(pre)
        if "oscillate" in s:                                       # bit-gegated in caps
            parts.append("osc")

    elif domain == "media_player":
        if "volume" in s:                                          # bit-gegated in caps (D1)
            parts.append("vol")
        sf = int(a.get("supported_features") or 0)
        if sf & _SELECT_SOURCE:                                    # D1: src nur wenn wirklich umschaltbar
            src = _lst("src", a.get("source_list"), x)             # Advertiser (RAW-Order, D2/D7)
            if src:
                parts.append(src)

    elif domain == "cover":                                        # D6: heute executor-verdrahtet
        if "position" in s:                                        # bit-gegated (SET_POSITION) in caps
            parts.append("pos")
        if "tilt" in s:                                            # bit-gegated (SET_TILT) in caps
            parts.append("tilt")

    elif domain in ("select", "input_select"):                     # v23.6 Batch1a: options-Enum (G1)
        opt = _adv(a, "option", x)                                  # Advertiser aus Tabelle (RAW-Order, D2/D7); bimodal wie fx
        if opt:
            parts.append(opt)

    return ":" + "·".join(parts) if parts else ""
