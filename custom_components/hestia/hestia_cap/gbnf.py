"""cap-v2 GBNF-Grammatik — GENERIERT aus schema.py (B4).

Arbeitsteilung (bewusst): die Grammatik garantiert **Syntax + Token-Legalität +
Enum-Mitgliedschaft + Wert-Typ** (malformed pythonic, ungültige Enum-Werte UND
untypisierte Werte — z.B. `temperature="heiß"` oder Zahl-als-String — unmöglich).
**Semantik** (required-Args vorhanden, attribute↔value-KOPPLUNG, keine Doppel-Keys)
bleibt Parser (parse.py) — die Kopplung hängt vom Schwester-kwarg ab, das kann GBNF nicht.

cap-v2-Tightening (§5, 2026-07-08): value-Regel typisiert (freier str-Fallback raus, s.u.).
Punkte „genau eine Call-Liste, nichts danach" (root endet mit End-Wrapper) und „Enums pro Verb"
(schon in _value_rule_for) waren bereits erfüllt.

Empirisch validiert (A2): der Special-Wrapper `<|tool_call_start|>` als Grammatik-Literal
wird von llama.cpp direkt erfüllt (keine Lazy-/Trigger-Grammar nötig), 0/500 malformed.
"""
from __future__ import annotations
from .schema import (VERBS, TARGET_PARAMS, TOOL_CALL_START, TOOL_CALL_END,
                     SETTABLE_ATTRS, COLOR_WORDS, COLOR_TEMP_WORDS)


def _gbnf_str_literal(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _rule_name(verb: str) -> str:
    # llama.cpp-GBNF-Regelnamen: nur [a-zA-Z0-9-] — KEINE Unterstriche.
    # Verb-Literale (z.B. "turn_on(") behalten den Unterstrich; nur der Regelname wird sanitisiert.
    return "call-" + verb.replace("_", "-")


def _value_rule_for(spec: dict) -> str:
    """Liefert den GBNF-Ausdruck (rechte Seite) für den Wert eines Params."""
    t = spec["type"]
    if t == "enum":
        alts = " | ".join(f'"\\"{v}\\""' for v in spec["values"])
        if spec.get("or_number"):
            alts += " | num"
        return alts
    if t == "value":
        # cap-v2-Tightening (§5): freier `str`-Fallback ENTFERNT → der Wert ist typisiert
        # (Zahl | max/min | Farbwort | Farbtemp-Wort). Killt "Zahl als String" (temperature="21")
        # und "beliebiger String als Wert" (temperature="heiß") schon am Decode. Die attribute↔value-
        # KOPPLUNG (temperature MUSS num, color MUSS Farbwort) bleibt bewusst Parser — GBNF kann sie
        # nicht ausdrücken (kind hängt vom Schwester-kwarg ab). Vollständigkeit: alle SETTABLE_ATTRS-kinds
        # sind num (pct/number/colortemp-Kelvin), max/min (pct) oder Wort-Enum (colorword/colortemp).
        color_alts = " | ".join(f'"\\"{c}\\""' for c in COLOR_WORDS)
        ct_alts = " | ".join(f'"\\"{c}\\""' for c in COLOR_TEMP_WORDS)
        return f'num | "\\"max\\"" | "\\"min\\"" | {color_alts} | {ct_alts}'
    return "str"  # freie Strings (name/area/floor/domain/content/message/item/duration/label) — bewusst frei


def build_grammar() -> str:
    lines: list[str] = []
    # root: Wrapper + Liste von Calls + Wrapper
    call_alts = " | ".join(_rule_name(v) for v in VERBS)
    start = _gbnf_str_literal(TOOL_CALL_START)
    end = _gbnf_str_literal(TOOL_CALL_END)
    lines.append(f'root ::= {start} "[" ws call (ws "," ws call)* ws "]" {end}')
    lines.append(f"call ::= {call_alts}")

    # je Verb: verb "(" kwargs? ")"  mit den erlaubten Keys als Alternation
    for verb, spec in VERBS.items():
        kw_rules = []
        keys = list(TARGET_PARAMS) if spec["target"] else []
        # eigene Params
        merged = {}
        if spec["target"]:
            merged.update(TARGET_PARAMS)
        merged.update(spec["params"])
        for k in (keys + list(spec["params"])):
            kw_rules.append(f'{_gbnf_str_literal(k + "=")} ( {_value_rule_for(merged[k])} )')
        kwarg = " | ".join(kw_rules)
        rn = _rule_name(verb)
        # A2-bewährtes Muster: benannte optionale args-Regel (nicht inline "(...)?" mit innerem Quantor).
        lines.append(f'{rn} ::= "{verb}(" ws {rn}-args? ws ")"')
        lines.append(f'{rn}-args ::= {rn}-kw (ws "," ws {rn}-kw)*')
        lines.append(f'{rn}-kw ::= {kwarg}')

    # gemeinsame Terminals
    lines.append('str ::= "\\"" char* "\\""')
    lines.append('char ::= [^"\\\\]')
    lines.append('num ::= "-"? [0-9]+')
    lines.append('ws ::= [ ]?')
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(build_grammar())
