"""hestia_cap — HA-freie Single-Source des cap-vN-Kontrakts (train==serve==bench).

Importiert von: hestia (Addon), ha-llm-finetune (Generator), Bench.
Keine HA-/Framework-Abhängigkeiten — reine Schema-/Render-/Parse-/GBNF-Logik.
Kontrakt: homelab-admin/hestia/v23/CAP_V1_FROZEN.md (WIRE frozen 2026-07-07).
"""
from .schema import CAP_VERSION, VERBS, TOOL_CALL_START, TOOL_CALL_END
from .tooldefs import all_tool_defs, tool_def
from .gbnf import build_grammar
from .parse import parse, Call, ParseResult
from .serialize import dumps, serialize_call
from .house import House, Area, Entity
from .render import (RENDER_VERSION, INSTRUCTIONS, render_house,
                     render_system_content, build_messages)
from .chat_template import render_prompt, render_live_context, BOS_TOKEN, STOP
from . import result
from .result import StateProvider, resolve, exposure_from_house

__all__ = ["CAP_VERSION", "VERBS", "TOOL_CALL_START", "TOOL_CALL_END",
           "all_tool_defs", "tool_def", "build_grammar",
           "parse", "Call", "ParseResult", "dumps", "serialize_call",
           "House", "Area", "Entity", "RENDER_VERSION", "INSTRUCTIONS",
           "render_house", "render_system_content", "build_messages",
           "render_prompt", "render_live_context", "BOS_TOKEN", "STOP",
           "result", "StateProvider", "resolve", "exposure_from_house"]
