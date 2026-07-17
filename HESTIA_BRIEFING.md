# Hestia — Capability Briefing (für eine externe Claude-Code-Instanz)

> **Zweck dieses Dokuments.** Du (Claude Code bei einem Freund des Hestia-Autors) sollst nach dem Lesen
> das *Projekt Hestia* so gut verstehen wie die Instanz, die daran arbeitet — **Möglichkeiten UND Grenzen** —
> damit dein Nutzer seine Wünsche mit dir realistisch durchsprechen und einen **groben, umsetzbaren Plan**
> zurückschicken kann. Dies ist ein **Design-/Fähigkeits-Briefing**, keine Bedienungsanleitung und kein Code.

> **Tieferer Einblick (wenn du mehr Kontext brauchst).** Du liest diese Datei vermutlich aus dem Repo
> **`bennizone/hestia-ha`** — das ist die **Home-Assistant-Integration = die Executor-Seite**. Zieh dir das
> Repo (`git clone https://github.com/bennizone/hestia-ha` oder browse es), wenn du tiefer schauen willst:
> - `custom_components/hestia/executor.py` — der Executor (führt Tool-Calls gegen HA aus, baut das Ergebnis)
> - `custom_components/hestia/conversation.py` — der Sprach-Agent (Prompt-Aufbau, Loop, Aufruf ans Modell)
> - `custom_components/hestia/hestia_cap/result.py` + `schema.py` — Fähigkeits-Logik & der Tool-/Verb-Kontrakt
> - `custom_components/hestia/house_builder.py`, `store.py`, `websocket.py` — Haus-Aufbau & Exposure (Panel)
>
> **Wichtige Grenze:** das *Modell* selbst, die Trainingsdaten und der Generator liegen in einem separaten,
> **nicht-öffentlichen** Projekt — die LLM-/Trainings-Seite ist hier NICHT einsehbar. Für alles, was das
> Modell betrifft, ist **dieses Briefing** die maßgebliche Quelle.

---

## 1. Was Hestia ist

Hestia ist ein **lokaler, privater Sprachassistent für Home Assistant (HA)**. Kein Cloud-Dienst — ein
**kleines, feingetuntes Sprachmodell (~350M Parameter)**, das on-device läuft, **deutschsprachig**.
Ziel: „besser als Alexa" für Smart-Home-Steuerung, aber offline, privat, und ehrlich (es tut nur, was
wirklich geht, und sagt klar, wenn etwas nicht geht).

Es besteht aus zwei gekoppelten Teilen:
- **das Modell** (formuliert Nutzer-Absicht in strukturierte Aktionen ODER in freien Text),
- **hestia-ha** (eine HA-Integration = der *Executor*, der die Aktionen deterministisch gegen HA ausführt
  und ein Ergebnis zurückgibt).

---

## 2. Wie es funktioniert (der Kontrakt — das Wichtigste)

```
Nutzer-Utterance
      │
      ▼
  MODELL  ──►  entweder eine Liste TOOL-CALLS (aus einem GESCHLOSSENEN Verb-Kontrakt)
               oder FREIER TEXT (Smalltalk, Rückfrage bei Mehrdeutigkeit, ehrliche Absage)
      │
      ▼
  EXECUTOR (hestia-ha)  ──►  führt die Calls gegen HA aus, RECHNET deterministische Fakten,
                             gibt ein Ergebnis-JSON zurück
      │
      ▼
  MODELL  ──►  verbalisiert das Ergebnis kurz und wahrheitsgetreu ("Wohnzimmer ist jetzt 22 Grad.")
```

**Zwei eiserne Prinzipien** (danach richtet sich JEDE Erweiterung):

1. **`train == serve`.** Das Modell wird auf exakt die Kontrakt-Form trainiert, die der Executor auch
   zur Laufzeit sieht. Kontrakt-Änderungen müssen auf beiden Seiten identisch sein.
2. **Der Executor rechnet, das Modell formuliert nur.** Alles Deterministische (Datums-Mathe, Bereichs-
   Grenzen, Nachschlagen, Recurrence) passiert im Executor — **nicht** im 350M-Modell (das kann sowas
   nicht zuverlässig). Das Modell *routet* die Absicht und *verbalisiert* das Ergebnis.

---

## 3. Was Hestia HEUTE kann

**Verb-Universum (der geschlossene Kontrakt):**
`turn_on`, `turn_off`, `set_state` (absoluter Wert), `adjust` (relativ), `get_state` (lesen),
`run_routine` (Szene/Skript), `set_timer`, `control_media`, `announce`, `manage_list` (Einkaufs-/To-do-Listen),
`control_vacuum`, `stop`, `help`.

**Fähigkeiten obendrauf:**
- **Cap-Awareness:** Das Modell kennt pro Gerät die *Fähigkeiten* (z.B. welche HVAC-Modi, welcher
  Temperatur-Bereich, welche Presets/Effekte). Es lehnt **ehrlich ab**, wenn etwas nicht geht
  („Kühlen kenne ich dafür nicht — Heizen oder Aus?"), statt zu halluzinieren.
- **Mehr-Turn:** Rückfragen bei Mehrdeutigkeit (endet auf „?"), Listen-Schleifen (mehrere Items nacheinander).
- **Read-Verben:** Wetter, Sonnenstand, Sensor-/Zustands-Auskunft — das Modell holt einen vom Executor
  vorgerechneten Fakt und verbalisiert ihn.
- **Wahrheitstreue:** Antworten nennen nur, was *wirklich* passiert ist; bei Fehlern ehrlich.

---

## 4. Die GRENZEN (bitte ernst nehmen — das rahmt jeden Wunsch)

- **Geschlossener Kontrakt, kein offener Chatbot.** Hestia ist *kein* GPT. Es kann nur, was im Verb-Kontrakt
  steht. „Frag irgendwas"-Fähigkeiten existieren nicht und sind teuer nachzurüsten.
- **Kleines Modell (~350M).** Kein Rechnen, keine Datums-Arithmetik, kein mehrstufiges Schlussfolgern,
  kein offenes Sprachverstehen über beliebige Datenstrukturen. Alles Harte gehört in den Executor.
- **Neue Fähigkeit = echter Zyklus, kein Schalter.** Eine neue Fähigkeit hinzuzufügen bedeutet:
  Kontrakt erweitern (train==serve) → Trainingsdaten generieren → Modell **neu trainieren** → benchen.
  Das ist bewusst und aufwändig — **Fähigkeiten werden eng geschnitten**, nicht breit hingeworfen.
- **Sicherheit vor Reichweite.** Lieber eine kleine, robuste, vorhersagbare Fähigkeit als eine große,
  unscharfe. Unscharfe Fähigkeiten sind kaum trainierbar und im Alltag unzuverlässig.

---

## 5. Wie man eine NEUE Fähigkeit gut zuschneidet (die Rezeptur)

Wenn dein Nutzer etwas Neues will, prüft man es an diesen vier Fragen — je mehr „ja", desto realistischer:

1. **Geschlossenes Enum statt offenem Freitext?** Fixe Kategorien/Werte (wie ein Auswahlmenü) sind
   trainierbar; „beliebiger Text" ist es kaum.
2. **Kann der Executor die harte Arbeit übernehmen?** Datums-Mathe, Grenzen, Nachschlagen → Executor.
   Das Modell soll nur *routen* + *verbalisieren*.
3. **Besitzen WIR das Schema?** Wenn die Daten über hestia-ha (das Panel) angelegt werden und wir ihre
   Struktur kennen, ist es sicher & findbar. Abhängigkeit von beliebigen Fremd-Datenformaten = fragil.
4. **Read statt Action?** Eine Fakten-Abfrage („wann ist X") ist billiger & sicherer als eine neue
   Steuer-Aktion mit Nebenwirkungen.

---

## 6. Durchgespieltes Beispiel: Kalender / Termine (ein echter Wunsch)

Wunsch des Nutzers: *„Wann ist die nächste Müllabholung?"*, *„Wann hat XX Geburtstag / Jahrestag?"*

**Naiver Ansatz (zu groß, abgelehnt):** beliebige HA-Kalender frei abfragen. Problem: HA-Kalender kommen
aus vielen Integrationen ohne einheitliches Schema (Google/CalDAV/Müll-Integrationen/…), Namensmatching
über Freitext, Datums-Recurrence — offenes NLU, kaum trainierbar.

**Zugeschnittener Ansatz (klein, sicher, trainierbar — nach der Rezeptur oben):**
- **Geschlossenes Kategorie-Enum:** `Geburtstag`, `Jahrestag`, `Müll`, `Termin`, … (fix, wie unsere
  anderen Enums). Modell emittiert z.B. `query_calendar(category=birthday, subject="Oma")`.
- **WIR legen die Einträge an & besitzen sie:** über das hestia-ha-Panel, gespeichert als HA-**Local
  Calendar**-Events (nativ, im Backup, unterstützt wiederkehrende Termine per RRULE). Damit kennt der
  Executor die Kalender/Struktur → deterministisch findbar.
- **Executor rechnet:** ruft `calendar.get_events`, wählt die nächste (ggf. wiederkehrende) Instanz,
  macht die Datums-Mathe → Fakt. Das Modell sagt „Die nächste Müllabholung ist am Dienstag, den 22."
- **Müll passt in denselben Mechanismus** als wiederkehrendes RRULE-Event („alle 2 Wochen dienstags").
  Geburtstag/Jahrestag = jährliche All-Day-Events. Ein Mechanismus für alle Kategorien.

Das ist die Art, wie ein Wunsch von „Riesending" auf „ein Read-Verb + geschlossenes Enum + selbst-besessene
Daten" schrumpft. **Genau so sollten Wünsche formuliert werden.**

---

## 7. Was dein Nutzer zurückschicken sollte

Ein **grober Plan / Wunschliste**, pro Wunsch idealerweise:
- **Was** soll gefragt/gesteuert werden (eine konkrete Beispiel-Utterance).
- **Read oder Action?** (Fakt abfragen vs. etwas verändern).
- **Lässt es sich auf ein geschlossenes Enum/Kategorien eindampfen?** Wenn ja, welche.
- **Woher kommen die Daten?** (idealerweise: über hestia-ha selbst angelegt, nicht fremd).
- **Was müsste der Executor rechnen** (damit das Modell es nicht muss)?

Damit kann der Hestia-Autor jeden Wunsch direkt gegen die Rezeptur (Abschnitt 5) halten und Aufwand/
Machbarkeit einschätzen. Perfekt strukturiert ist nicht nötig — die vier Punkte oben genügen.

---

*Kontext-Stand: aktuelle Hestia-Generation (Cap-Awareness), 350M-Prod-Modell. Dieses Briefing beschreibt
Architektur & Design-Grenzen bewusst ohne Homelab-Interna. Fragen/Feedback laufen über den Hestia-Autor.*
