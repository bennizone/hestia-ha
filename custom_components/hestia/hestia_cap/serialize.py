"""cap-v1 Serializer — Call-Liste → pythonic Wire-String (Inverse von parse.py).

DIE eine Stelle, die cap-v1-Calls zu Text macht. Generator (C2-Gold-Emission),
Relabel-Mapper (C1) und Tests importieren dies — Serialisierung lebt genau EINMAL
(kein Reimplement → FM2). Garantie (Test): parse(dumps(calls)) rekonstruiert calls.

Key-Reihenfolge deterministisch = Schema-Reihenfolge (Ziel-Block zuerst, dann
Verb-Params) → byte-stabiles Gold, prefix-cache-freundlich.
"""
from __future__ import annotations
from .schema import VERBS, TARGET_PARAMS, TOOL_CALL_START, TOOL_CALL_END, verb_param_keys


def _fmt_value(v) -> str:
    """Python-Literal für einen Argument-Wert (str | int | float)."""
    if isinstance(v, bool):
        raise ValueError("bool not a valid cap-v1 value")
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        # ganze Floats als int-Literal (21.0 -> "21"), sonst repr
        return str(int(v)) if v.is_integer() else repr(v)
    raise ValueError(f"unserializable value type {type(v).__name__}: {v!r}")


def serialize_call(verb: str, args: dict) -> str:
    """Ein Call `verb(k=v, ...)`. Keys in Schema-Reihenfolge (deterministisch)."""
    if verb not in VERBS:
        raise ValueError(f"unknown verb {verb!r}")
    order = verb_param_keys(verb)
    extra = [k for k in args if k not in order]
    if extra:
        raise ValueError(f"{verb}: keys not in schema: {extra}")
    parts = [f"{k}={_fmt_value(args[k])}" for k in order if k in args]
    return f"{verb}(" + ", ".join(parts) + ")"


def dumps(calls, wrap: bool = True) -> str:
    """Call-Liste → Wire-String. calls: Iterable[(verb, args) | {"verb","args"} | Call].

    wrap=True kapselt in die Special-Tokens (Serving/Gold-Form); wrap=False = nur `[...]`.
    """
    items = []
    for c in calls:
        if isinstance(c, tuple):
            verb, args = c
        elif isinstance(c, dict):
            verb, args = c["verb"], c.get("args", {})
        else:  # Call-Dataclass o.ä.
            verb, args = c.verb, c.args
        items.append(serialize_call(verb, args))
    body = "[" + ", ".join(items) + "]"
    return f"{TOOL_CALL_START}{body}{TOOL_CALL_END}" if wrap else body
