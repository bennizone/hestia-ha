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
**MVP läuft end-to-end** (2026-07-08, gegen das 25k-Modell im .111-Testbed). Verifiziert:
turn_on/turn_off (Area+Domain & Name), set_state (Thermostat auf 20/22°C real gesetzt),
adjust (dimmen), get_state (geerdet „21,0 Grad"), Casual/Identität, ehrlicher Refuse bei
nicht-exponierten Geräten. Der volle Pfad render→`/completion`→parse→Executor→rev2-Result→
geerdete Antwort ist bestätigt; der LFM2.5-Prompt-Render ist byte-genau gegen `apply_chat_template`.

Design/Kontrakt: `homelab-admin/hestia/v23/HA_INTEGRATION_DRAFT.md` · `SERVE_PIPELINE.md` ·
`RESULT_SCHEMA.md` · `LOOP_ARCH_DESIGN.md`.

**Deferred (F1+):** Exposure-Editor im Config-Flow (aktuell: Membership = HAs explizite
conversation-Exposure), rapidfuzz-Resolver (aktuell difflib), volle Verb-Abdeckung
(run_routine/set_timer/control_media/announce/manage_list/control_vacuum → ehrlich
`not_controllable`), get_state attributlose Raum-Frage als YAML-Block, Safety-UI-Lock, Telemetrie.

## Test-Setup
- HA-Testbed (Monster-Haus) + llama.cpp-Q8-Modell beide auf **.111** (`:8123` / `:8099`).
- Prod später: HA → llama.cpp auf **.112**.
- Debug-Log: `logger.set_level {custom_components.hestia: debug}` → je Turn `model=…`/`result=…`.

## Layout
```
custom_components/hestia/
  __init__.py      config_flow.py   const.py
  conversation.py  ← ConversationEntity + cap-v2-Loop
  executor.py      ← Wire→Entität→hass.services + rev2-Result (Resolver + Verb-Dispatch)
  house_builder.py ← HA-Registry → hestia_cap.House + Exposure-Set
  hestia_cap/      ← vendored Contract-Anker (render/parse/serialize/schema + chat_template)
```
