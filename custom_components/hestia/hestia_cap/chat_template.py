"""LFM2.5-Chat-Template als reiner Python-Render — die Serve-Seite der train==serve-Naht.

Der Bench rendert via HuggingFace `tok.apply_chat_template(..., tokenize=False)`. In der
HA-Integration können wir kein transformers/torch laden → wir reproduzieren das offizielle
LFM2.5-Template (tokenizer_config.json `chat_template`) byte-genau in Python.

Byte-Parität ist VERIFIZIERT (test gegen echte apply_chat_template-Golden-Referenz, gpu4070
Trainer-Container). Gilt für den String-Content-Pfad (Multimodal-/Listen-Content nutzen wir nicht).

Template-Semantik (aus chat_template.jinja):
  bos + [system-Block (system_prompt + optional "\\nList of tools: [<tojson>, ...]")]
      + je Message "<|im_start|>{role}\\n{content}<|im_end|>\\n"
      + optional "<|im_start|>assistant\\n"  (add_generation_prompt)
  `tool | tojson`  ==  json.dumps(tool, ensure_ascii=False)  (Default-Separatoren ", "/": ").

NIEMALS /v1/chat/completions (llama.cpp #23838). Dieser Render + POST /completion IST der Kontrakt.
"""
from __future__ import annotations
import json

BOS_TOKEN = "<|startoftext|>"
IM_START = "<|im_start|>"
IM_END = "<|im_end|>"
STOP = IM_END  # /completion stop-Token


def _tojson(tool: dict) -> str:
    """Jinja `tool | tojson` unter HF: json.dumps(ensure_ascii=False, Default-Separatoren)."""
    return json.dumps(tool, ensure_ascii=False)


def render_prompt(messages: list[dict], tools: list[dict] | None = None,
                  add_generation_prompt: bool = True) -> str:
    """messages (role/content, content=str) + innere Tool-Defs → LFM2.5-Prompt-String.

    Erwartet: messages[0] optional system; alle content sind Strings. Reproduziert
    apply_chat_template(tokenize=False, add_generation_prompt=…) byte-genau.

    Live-Kontext-Schwanz (Zeit/Nutzer/Raum/laufende Timer+Medien): als ZWEITE System-Message
    (messages[1], role=system) übergeben. Sie wird — wie bei apply_chat_template — als eigener
    System-Turn NACH dem Tool-tragenden ersten System-Block gerendert → [Instruktionen+Haus+Tools]
    bleibt ein byte-stabiler, prefix-cachebarer Präfix; nur der Schwanz wird pro Request neu
    verarbeitet. train==serve byte-verifiziert (2-System-Message-Golden).
    """
    out = [BOS_TOKEN]
    msgs = list(messages)

    # 1. System-Prompt extrahieren (falls messages[0] == system)
    system_prompt = ""
    if msgs and msgs[0]["role"] == "system":
        system_prompt = msgs[0]["content"]
        msgs = msgs[1:]

    # 2. Tools an den System-Prompt anhängen (innere Defs, tojson) — Teil des statischen Präfix
    if tools:
        system_prompt += ("\n" if system_prompt else "") + "List of tools: ["
        system_prompt += ", ".join(_tojson(t) for t in tools)
        system_prompt += "]"

    # 3. System-Block nur wenn nicht leer  (eine evtl. 2. System-Message = Live-Kontext läuft
    #    unten in der Schleife als eigener System-Turn nach den Tools — train==serve-Naht)
    if system_prompt:
        out.append(f"{IM_START}system\n{system_prompt}{IM_END}\n")

    # 4. Restliche Messages (content immer String bei uns)
    for m in msgs:
        out.append(f"{IM_START}{m['role']}\n{m['content']}{IM_END}\n")

    # 5. Generation-Prompt
    if add_generation_prompt:
        out.append(f"{IM_START}assistant\n")

    return "".join(out)
