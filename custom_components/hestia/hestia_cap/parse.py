"""cap-v1 Parser — Modell-Rohtext → validierte Call-Liste (B4).

Arbeitsteilung mit gbnf.py: die GBNF garantiert **Syntax + Enum-Mitgliedschaft**.
Dieser Parser garantiert **Semantik**: bekannter Verb, erlaubte Keys je Verb,
required-Args vorhanden, attribute↔value-Kopplung. (cap-v2: keine Dialog-Verben mehr.)

Der Executor (Addon F2) und der Generator-Round-Trip (C) importieren dies —
pythonic-Parse lebt genau EINMAL (kein Reimplement → FM2).
"""
from __future__ import annotations
import ast
import re
from dataclasses import dataclass, field
from .schema import (VERBS, TARGET_PARAMS, SETTABLE_ATTRS, ADJUSTABLE_ATTRS,
                     TOOL_CALL_START, TOOL_CALL_END, verb_param_keys)


@dataclass
class Call:
    verb: str
    args: dict          # kwarg-Name -> Python-Wert (str|int|float)
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class ParseResult:
    calls: list          # list[Call]
    errors: list = field(default_factory=list)   # top-level (Wrapper/List/Invariante)

    @property
    def ok(self) -> bool:
        return not self.errors and all(c.ok for c in self.calls)


def _strip_wrapper(raw: str) -> str:
    s = raw.strip()
    i, j = s.find(TOOL_CALL_START), s.rfind(TOOL_CALL_END)
    if i != -1 and j != -1:
        s = s[i + len(TOOL_CALL_START):j]
    return s.strip()


def _literal(node):
    """Wert eines kwarg-AST-Knotens (Konstante oder unäres Minus für Zahlen)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return -node.operand.value
    raise ValueError("non-literal argument")


def _validate_call(verb: str, args: dict) -> list:
    errs = []
    if verb not in VERBS:
        return [f"unknown verb '{verb}'"]
    spec = VERBS[verb]
    allowed = set(verb_param_keys(verb))
    for k in args:
        if k not in allowed:
            errs.append(f"{verb}: key '{k}' not allowed")
    for r in spec["required"]:
        if r not in args:
            errs.append(f"{verb}: missing required '{r}'")
    # Enum-Mitgliedschaft (Grammatik erzwingt das schon; hier für nicht-constrained-Pfade/Tier-2)
    merged = {}
    if spec["target"]:
        merged.update(TARGET_PARAMS)
    merged.update(spec["params"])
    for k, v in args.items():
        ks = merged.get(k)
        if ks and ks["type"] == "enum":
            vals = ks["values"]
            if v not in vals and not (ks.get("or_number") and isinstance(v, (int, float))):
                errs.append(f"{verb}: {k}={v!r} not in enum {vals}")
    # attribute↔value-Kopplung
    if verb == "set_state" and "attribute" in args and "value" in args:
        errs += _check_set_value(args["attribute"], args["value"])
    if verb == "adjust" and "attribute" in args:
        if args["attribute"] not in ADJUSTABLE_ATTRS:
            errs.append(f"adjust: attribute '{args['attribute']}' not adjustable")
    if "when" in args:                          # v23.9: optionaler Zeit-Slot an Aktions-Verben
        errs += _check_when(args["when"])
    return errs


_WHEN_AT = re.compile(r"^(\d{1,2}):(\d{2})$")
_WHEN_DUR = re.compile(r"^(\d+\s*(h|min|s))+$")


def _check_when(val) -> list:
    """`when` gültig: "now" (sofort) | "HH:MM" (absolut, 0-23:0-59) | "<N>h/min/s" (relativ). Sonst Fehler."""
    if val == "now":
        return []
    m = _WHEN_AT.match(str(val))
    if m and 0 <= int(m.group(1)) < 24 and 0 <= int(m.group(2)) < 60:
        return []
    if _WHEN_DUR.match(str(val).strip()):
        return []
    return [f"when={val!r} ungültig (now|HH:MM|<N>h/min/s)"]


def _check_set_value(attr: str, val) -> list:
    spec = SETTABLE_ATTRS.get(attr, {})
    kind = spec.get("kind")
    if kind == "pct":
        if isinstance(val, str) and val in ("max", "min"):
            return []
        # Über-/Unter-Range NICHT hier ablehnen — plan_set_state klemmt numerische pct-Werte auf
        # [lo,100] (done_clamped, §6.5), konsistent mit kind=="number". Parse-Reject würde die
        # Klemm-Logik überspringen → Über-Range-% liefe fälschlich auf `unparseable` (v23.7 D3-Bug).
        if isinstance(val, (int, float)):
            return []
        return [f"set_state: {attr} value {val!r} must be number|max|min"]
    if kind == "number":
        return [] if isinstance(val, (int, float)) else [f"set_state: {attr} value must be number"]
    if kind == "words":
        vals = spec["values"]
        return [] if (isinstance(val, str) and val in vals) else [f"set_state: {attr} value {val!r} not in {vals}"]
    if kind == "str":
        return [] if isinstance(val, str) else [f"set_state: {attr} value must be string"]
    # colorword/colortemp: string erlaubt (weiche Prüfung — Executor mappt/liefert invalid_value+allowed, H5)
    return []


def parse(raw: str) -> ParseResult:
    body = _strip_wrapper(raw)
    if not (body.startswith("[") and body.endswith("]")):
        return ParseResult(calls=[], errors=["no top-level call-list []"])
    try:
        tree = ast.parse(body, mode="eval").body
    except SyntaxError as e:
        return ParseResult(calls=[], errors=[f"syntax: {e.msg}"])
    if not isinstance(tree, ast.List):
        return ParseResult(calls=[], errors=["top-level is not a list"])
    if not tree.elts:
        return ParseResult(calls=[], errors=["empty call-list"])
    calls, top = [], []
    for el in tree.elts:
        if not isinstance(el, ast.Call) or not isinstance(el.func, ast.Name):
            top.append("list element is not a bare call")
            continue
        if el.args:
            top.append(f"{el.func.id}: positional args not allowed (kwargs only)")
        args = {}
        bad = False
        for kw in el.keywords:
            if kw.arg is None:
                top.append("**kwargs not allowed"); bad = True; continue
            try:
                args[kw.arg] = _literal(kw.value)
            except ValueError:
                top.append(f"{el.func.id}: non-literal value for {kw.arg}"); bad = True
        verb = el.func.id
        errs = _validate_call(verb, args) if not bad else ["unparsable args"]
        calls.append(Call(verb=verb, args=args, errors=errs))
    # cap-v2: keine Dialog-Verben mehr → keine Aktion-XOR-Dialog-Invariante (Dialog = freier Text ohne Tool-Block).
    return ParseResult(calls=calls, errors=top)
