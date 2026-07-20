# Hestia 🔥 — selbst-gehosteter Sprachassistent für Home Assistant

**Steuere dein Zuhause per Sprache/Text — komplett lokal, ohne Cloud.** Hestia registriert eine
Home-Assistant-**ConversationEntity**, die einen geschlossenen Loop auf eigener Hardware fährt:
Nutzer-Text → lokales fine-getuntes LLM (LFM2.5 via llama.cpp) → Tool-Block → **nativer Executor**
(`hass.services`) → geerdetes Result → wahrheitsgemäße Antwort.

Kein Cloud-Call, keine Daten verlassen dein Netz. Primär **deutschsprachig**. Läuft auf einer kleinen
eigenen GPU-/CPU-Box (das 350M-Modell ist bewusst klein & schnell). HAs eingebauter llm-Tool-Layer
wird bewusst **nicht** genutzt — Hestia fährt den Loop selbst (volle Kontrolle über Grammar & Repair).

- 📋 **Was es kann:** → [FEATURES.md](FEATURES.md)
- 🤖 **Modell-Gewichte (gguf):** → [HuggingFace](https://huggingface.co/bennizone) *(Link wird beim Publish finalisiert)*
- 🤝 **Neugierig, aber unsicher?** Sag deinem KI-Assistenten „schau dir dieses Repo an" — [AGENTS.md](AGENTS.md) brieft ihn, dir das Projekt zu erklären, einzuschätzen ob es für dich passt, und dich durch die Installation zu führen.

> **Status:** experimentell / in aktiver Entwicklung — Verhalten und Schnittstellen können sich ändern.

## Highlights

- **Aktionen, Auskunft, Zeitsteuerung** — an/aus, Werte & Modi setzen, relativ anpassen; Zustände &
  Aggregate abfragen; „schalt das Licht in 10 Minuten aus" (geplante HA-Automation).
- **Wahrhaftig** — sagt ehrlich „kann ich nicht", meldet Teil-Erfolge und Wert-außerhalb-des-Bereichs;
  nie ein falsches „erledigt".
- **Fähigkeits-bewusst** — kennt, was ein Gerät kann, und klemmt Werte an echte Grenzen.
- **train == serve** — der Prompt wird lokal exakt so gerendert, wie das Modell trainiert wurde.

## Funktionsweise (kurz)

- **Modell:** fine-getuntes **LFM2.5 (350M/1.2B)**, lokal via **llama.cpp `/completion`** serviert.
- **train == serve:** Prompt-Rendering, Tool-Parsing und Result-Shaping kommen aus einem geteilten,
  vendorten Vertrag (`hestia_cap`) — das Modell sieht zur Laufzeit exakt seinen Trainings-Prompt.
  Nutzt `/completion`, nie `/v1/chat/completions`.
- **Native Ausführung:** aufgelöste Tool-Calls laufen direkt über `hass.services`; der Loop liefert ein
  geerdetes, strukturiertes Result, das das Modell wahrheitsgemäß verbalisiert.
- **Distribution:** HACS-Custom-Integration — das Modell läuft **remote** auf eigener Box, nicht in HA.

## Schnellstart

1. **Modell servieren** — llama.cpp mit `/completion`-Endpoint + kompatiblem LFM2.5-gguf
   ([HuggingFace](https://huggingface.co/bennizone)). URL merken (z. B. `http://<box>:8099`).
2. **Installieren** — dieses Repo als **HACS-Custom-Repository** hinzufügen (Kategorie: Integration),
   „Hestia" installieren → Home Assistant neu starten. (Alternativ `custom_components/hestia/` manuell
   nach `<config>/custom_components/` kopieren.)
3. **Konfigurieren** — Integration „Hestia" hinzufügen, Serve-Endpoint-URL eintragen.
4. **Exponieren** — im Hestia-Panel Geräte freigeben (explizit), optional Write-Limits & Custom-Sätze.
5. **Nutzen** — als Conversation-Agent (`conversation.hestia`) in der Voice-Pipeline oder im Chat.

Debug-Log bei Bedarf: `logger.set_level {custom_components.hestia: debug}` — protokolliert pro Turn
Modell-Output und strukturiertes Result. Details, Modul-Landkarte und Gotchas: [AGENTS.md](AGENTS.md).

## Voraussetzungen

- Ein **selbst-gehosteter llama.cpp-Server** (`/completion`) mit kompatiblem fine-getuntem LFM2.5-Modell.
- Home Assistant (Core / Container / OS) mit HACS.
