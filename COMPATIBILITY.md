# Hestia — Modell ↔ Addon-Kompatibilität & Distribution

> Diese Integration (`hestia-ha`) ist die **Executor-/Serve-Seite**. Sie funktioniert nur zusammen mit
> einem **passend trainierten Sprachmodell**. Dieses Dokument hält fest, *welches Modell zu welcher
> Addon-Version gehört* und *woher man das Modell bekommt*. Es wird **pro Release gepflegt**.

## Prinzip: das Modell wird auf den Executor-Kontrakt trainiert (`train == serve`)

Hestia ist ein **feingetuntes Sprachmodell**, das gelernt hat, genau die **Tool-Calls + Fähigkeits-
Darstellung** zu erzeugen, die dieser Executor erwartet. Modell und Addon sprechen denselben Kontrakt —
sie werden **gemeinsam versioniert**.

Der entscheidende Kopplungs-Schlüssel ist die **`RENDER_VERSION`** (in
`custom_components/hestia/hestia_cap/render.py`): sie bestimmt, wie Haus & Geräte-Fähigkeiten in den
Prompt gerendert werden. **Ein Modell, das auf `rN` trainiert wurde, muss mit einem Addon auf `rN`
serviert werden.** Passt das nicht, driftet die Modell-Sicht von der Executor-Realität ab → Fehlverhalten.

## Das Modell

- **Basis:** LiquidAI **LFM2.5-350M** (Fine-Tune), ~350M Parameter — klein, läuft **lokal**, **deutschsprachig**.
- **Format & Serving:** **GGUF**, serviert über **llama.cpp** am **`/completion`-Endpoint** (bewusst
  *nicht* `/v1/chat/completions` — der bricht das native Tool-Parsing). Das Addon zeigt per Konfig
  `llama_url` auf diesen Endpoint und rendert den Prompt selbst. Kein Cloud-Dienst.
- **Grenzen:** siehe `HESTIA_BRIEFING.md` (geschlossener Kontrakt, keine Datums-/Rechen-Logik im Modell,
  kein offenes NLU — das Deterministische macht der Executor).

## Kompatibilitäts-Matrix (living — bei jedem Release aktualisieren)

| hestia-ha (Addon) | Kontrakt `RENDER_VERSION` | Passendes Modell (Daten-Version) | Modell-Artefakt |
|---|---|---|---|
| **v0.2.0** *(aktuell public)* | **r8** | Hestia **v23.9** (LFM2.5-350M, 125k) — Zeitsteuerung/`when`-Slot + Cap-Enums | HuggingFace (s. „Distribution") |
| v0.1.5 – v0.1.9 *(überholt)* | r3 | Hestia v23.4 (LFM2.5-350M) | — |

*(v0.2.0 bündelt v23.6 Cap-Enums + v23.7/v23.9 Zeitsteuerung; die Zwischen-Kontrakte r4–r7 waren nur
intern/branch, nie als Addon-Release veröffentlicht — daher der Sprung r3 → r8.)*

**Goldene Regel:** die `RENDER_VERSION` des Modells muss = die `RENDER_VERSION` des Addons sein. Ein Addon-
Update, das `RENDER_VERSION` ändert, braucht **immer** ein neu trainiertes Modell — nie das eine ohne das
andere ausrollen.

*(RENDER_VERSION-Historie: r2 = HA-nativ · r3 = Aliase + Beschreibungen · r4 = Cap-Tags im `[domain]`-Token ·
r5 = +select/climate-fan/swing · r6 = +Growth-Domains sound_mode/humidifier/water_heater/remote/vacuum ·
r7 = Zeitsteuerung (set_timer+do_verb, verworfen) · r8 = Zeitsteuerung via `when`-Slot an Aktions-Verben.)*

## Distribution / woher man das Modell bekommt

Das trainierte GGUF wird bei Bedarf öffentlich bereitgestellt (**Hugging Face** o.ä.); die **aktuelle
Bezugsquelle** steht in den Release-Notes des jeweiligen Addon-Releases bzw. ist beim Autor zu erfragen.
Danach lokal über llama.cpp servieren und das Addon per `llama_url` darauf zeigen.

## Pflege dieses Dokuments

- Bei **jedem** gekoppelten Release (Addon + Modell) eine Zeile ergänzen: Addon-Version, `RENDER_VERSION`,
  Modell-Daten-Version, Bezugsquelle.
- Änderungen an `RENDER_VERSION` **niemals** ohne passendes Modell releasen (das ist die `train==serve`-Disziplin).
