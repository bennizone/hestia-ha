# Hestia — HA Conversation-Agent Integration (cap-v2 Loop)

Blackbox-Sprachassistent für Home Assistant. Registriert einen **ConversationEntity**, der
den cap-v2-**Loop** fährt: Nutzer-Text → eigenes LLM (LFM2.5 via llama.cpp) → Tool-Block →
**nativer Executor** (`hass.services`) → geerdetes Result → geerdete Antwort. HAs llm-API-Tool-Layer
wird bewusst NICHT genutzt — Hestia führt ihre Tools selbst aus (volle Kontrolle über Loop/Grammar/Repair).

- **Modell:** LFM2.5-350M/1.2B, fine-getunt (cap-v2-Multi-Turn-Gold), serviert via **llama.cpp `/completion`**.
- **train==serve:** Prompt wird lokal gerendert (vendored `hestia_cap`, offizielles LFM2.5-Template, innere Tool-Defs).
  NIEMALS `/v1/chat/completions` (llama.cpp #23838).
- **Distribution:** HACS-Custom-Integration (nicht Supervisor-App/Add-on — Modell lebt remote auf der GPU-Box).

## Status
**Grundgerüst** (2026-07-08). Skelett lädt in HA (ConversationEntity + Config-Flow); der Loop
(`conversation.py`) + Executor (`executor.py`) sind markierte TODO-Stubs. Design:
`homelab-admin/hestia/v23/HA_INTEGRATION_DRAFT.md` · `SERVE_PIPELINE.md` · `RESULT_SCHEMA.md` · `LOOP_ARCH_DESIGN.md`.

## Test-Setup
- HA-Testbed (Monster-Haus) + llama.cpp-Q8-Modell beide auf **.111** (`:8123` / `:8099`).
- Prod später: HA → llama.cpp auf **.112**.

## Layout
```
custom_components/hestia/
  __init__.py      config_flow.py   const.py
  conversation.py  ← ConversationEntity + Loop (TODO)
  executor.py      ← Wire→Entität→hass.services + rev2-Result (TODO)
  hestia_cap/      ← vendored Contract-Anker (render/parse/serialize/schema)
```
