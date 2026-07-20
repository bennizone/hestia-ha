# AGENTS.md — Orientierung für Entwickler & KI-Agenten

Kurzbriefing, damit ein Agent (oder Mensch) versteht, **worum es geht**, **wie es aufgebaut ist**
und **wie man es aufsetzt**. Für die Nutzer-Sicht siehe [README.md](README.md) / [FEATURES.md](FEATURES.md).

## Worum es geht

Hestia ist ein **selbst-gehosteter Conversation-Agent für Home Assistant**: Nutzer-Text → lokales
fine-getuntes LLM (LFM2.5 via llama.cpp) → Tool-Block → **nativer Executor** (`hass.services`) →
geerdetes Result → wahrheitsgemäße Antwort. HAs eingebauter llm-Tool-Layer wird bewusst **nicht**
genutzt; Hestia fährt den Loop selbst (volle Kontrolle über Grammar, Repair, Result-Shaping).

## Das eine Prinzip: train == serve

> Der Prompt, den diese Integration rendert (`hestia_cap/render.py:RENDER_VERSION`), muss **exakt**
> dem entsprechen, worauf das servierte Modell trainiert wurde.

`hestia_cap/` ist ein **vendorter Vertrag** (aus dem separaten Contract-Repo synchronisiert), den
Generator (Trainingsdaten), Bench und dieser Serve-Executor **teilen**. Prompt-Rendering, Tool-Parsing,
Result-Shaping und die verbalisierte Antwort kommen aus denselben reinen Funktionen → Trainings- und
Laufzeit-Verhalten sind byte-identisch. **Wer `RENDER_VERSION` ändert, muss ein passend trainiertes
Modell servieren** — sonst „redet das Modell an sich vorbei" (Text statt Tool-Calls, halluzinierte Args).

## Architektur / Loop

```
User-Text
  → conversation.py      ConversationEntity: baut Prompt (house_builder + hestia_cap.render)
  → llama.cpp /completion  lokales LFM2.5, GBNF-Grammar (hestia_cap/gbnf.py) erzwingt gültige Tool-Syntax
  → hestia_cap.parse     Tool-Block → strukturierte Calls
  → executor.py          native Ausführung über hass.services; schedule.py für when=Zeit
  → hestia_cap.result    geerdetes Result-Objekt (+ „say")
  → conversation.py      Modell verbalisiert das Result wahrheitsgemäß
```

## Modul-Landkarte (`custom_components/hestia/`)

| Datei | Rolle |
|---|---|
| `conversation.py` | ConversationEntity, der Turn-Loop, Truthfulness-Guard |
| `executor.py` | Tool-Calls → `hass.services` (Single-Exit `_exec_action`) |
| `schedule.py` | Zeitsteuerung: `when=Zeit` → getaggte HA-Automation (`Hestia:` + Ownership-Store), cancel/verschieben, Self-Cleanup |
| `house_builder.py` | HA-Exposure → `House`-Modell (Entitäten + Fähigkeiten) für den Prompt |
| `hestia_cap/` | **Vendorter Vertrag** — render, parse, result, chat_template, gbnf, house, cap_attrs, captag |
| `panel.py` + `panel/` | Admin-Panel (Exposure, Helfer, Custom-Sätze, Limits/Mapping) |
| `reqlog.py` | Request-Log (letzte Turns: text/live/model/result/answer), admin-WS |
| `helpers.py` · `sentences.py` · `mapping.py` · `store.py` · `websocket.py` | Helfer-Verwaltung, Custom-Sätze, Write-Mapping, Storage, WS-API |
| `config_flow.py` · `const.py` · `__init__.py` | Setup, Konstanten, Entry-Point |

## Aufsetzen (Dev / Prod)

1. **Modell servieren.** Einen llama.cpp-Server mit `/completion` starten, der ein kompatibles
   fine-getuntes LFM2.5-gguf lädt (q8 empfohlen; KV-q8 + FlashAttention). Merke die URL (z. B.
   `http://<box>:8099`). Das Modell muss zur `RENDER_VERSION` dieser Integration passen.
2. **Integration installieren.** Via HACS (Custom-Repo) oder `custom_components/hestia/` nach
   `<config>/custom_components/` kopieren → Home Assistant neu starten.
3. **Konfigurieren.** Integration „Hestia" hinzufügen → Serve-Endpoint-URL eintragen.
4. **Entitäten exponieren.** Im Hestia-Panel festlegen, welche Geräte der Assistent sehen/steuern darf
   (explizit, kein Domain-Default), optional Write-Limits/Mapping und Custom-Sätze.
5. **Als Conversation-Agent setzen** (Voice-Assistant-Pipeline oder Chat) → `conversation.hestia`.

## Gotchas

- **Kein `/v1/chat/completions`** — Hestia rendert den Prompt selbst und nutzt `/completion` (native
  LFM2-Tool-Semantik; der OpenAI-Chat-Endpoint bricht das Tool-Parsing).
- **Exposure ist explizit** — nur was im Panel freigegeben ist, ist steuerbar (kein Domain-Default).
- **Modell-Wechsel = Kontrakt-Wechsel** — neues `RENDER_VERSION` und Serve-Modell immer zusammen umschalten
  (train == serve). Rollback beides zusammen.
- Der Loop ist **judge-frei bei Aktionen** (objektives Result), Text-Antworten sind das Weiche.

## Verwandte Repos (nicht öffentlich)

- **Contract** — Quelle von `hestia_cap` (Vertrag; hier vendored).
- **Training** — Pull-basiertes Fine-Tuning-System (LFM2.5-LoRA), erzeugt die gguf-Modelle.
- **Bench** — gold-getriebener + judge-gestützter Benchmark (train==serve-Parität).

Die veröffentlichten Modell-Gewichte liegen auf HuggingFace (Link im README).
