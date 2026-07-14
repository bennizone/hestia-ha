# Hestia — Home-Assistant Conversation-Agent (selbst-gehostetes LLM)

Selbst-gehosteter Sprach-/Text-Assistent für Home Assistant. Registriert eine
**ConversationEntity**, die einen geschlossenen Loop komplett auf eigener Hardware fährt:
Nutzer-Text → lokales LLM (LFM2.5 via llama.cpp) → Tool-Block → **nativer Executor**
(`hass.services`) → geerdetes Result → geerdete Antwort.

HAs eingebauter llm-API-Tool-Layer wird bewusst **nicht** genutzt — Hestia führt ihre
Tools selbst aus (volle Kontrolle über Loop, Grammar und Repair).

## Funktionsweise

- **Modell:** fine-getuntes LFM2.5 (350M/1.2B), lokal via **llama.cpp `/completion`** serviert.
- **train == serve:** Der Prompt wird lokal gerendert (vendored `hestia_cap`, offizielles
  LFM2.5-Chat-Template, innere Tool-Defs) — das Modell sieht exakt, worauf es trainiert wurde.
  Nutzt `/completion`, nie `/v1/chat/completions`.
- **Native Ausführung:** aufgelöste Tool-Calls laufen direkt über `hass.services`; der Loop
  liefert ein geerdetes, strukturiertes Result, das das Modell wahrhaftig verbalisiert —
  inkl. ehrlichem „kann ich nicht", Teil-Erfolg und Wert-außerhalb-des-Bereichs.
- **Distribution:** HACS-Custom-Integration — das Modell läuft remote auf einer eigenen
  GPU-/CPU-Box, nicht in Home Assistant selbst.

## Voraussetzungen

- Ein **selbst-gehosteter llama.cpp-Server** mit `/completion`-Endpoint, der ein kompatibles
  fine-getuntes LFM2.5-Modell serviert. Die Endpoint-URL wird in der Integration konfiguriert.
- Home Assistant (Core / Container / OS) mit HACS.

> **Status:** experimentell / in aktiver Entwicklung — Verhalten und Schnittstellen können sich ändern.

## Installation

1. Dieses Repository als **HACS-Custom-Repository** hinzufügen (Kategorie: Integration).
2. **Hestia** über HACS installieren und Home Assistant neu starten.
3. Integration hinzufügen und die llama.cpp-Endpoint-URL konfigurieren.
   Die Geräte-Freigabe folgt HAs Standard-Einstellung „Für Assistenten freigeben".

Debug-Log bei Bedarf: `logger.set_level {custom_components.hestia: debug}` — protokolliert
pro Turn den Modell-Output und das strukturierte Result.

## Layout

```
custom_components/hestia/
  __init__.py      config_flow.py   const.py
  conversation.py  ← ConversationEntity + Control-Loop
  executor.py      ← Tool-Call → Entität → hass.services + strukturiertes Result
  house_builder.py ← HA-Registry → House-Modell + Exposure-Set
  hestia_cap/      ← vendored Contract (render / parse / serialize / schema + Chat-Template)
```
