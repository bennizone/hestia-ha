# Hestia — Features

Was der Assistent kann. Alles läuft **lokal** auf eigener Hardware (kein Cloud-Call), primär
auf **Deutsch**. Jede Aktion wird nativ über `hass.services` ausgeführt und **wahrheitsgemäß**
zurückgemeldet — Hestia behauptet nie einen Erfolg, den es nicht gab.

## Geräte steuern
- **An/Aus** — „mach das Licht an", „schalt den Ventilator aus".
- **Werte setzen** — Helligkeit, Temperatur, Farbe, Lautstärke, Position: „stell die Heizung auf 21 Grad", „dimm das Wohnzimmer auf 30 %".
- **Relativ anpassen** — „mach's wärmer", „etwas heller", „lauter".
- **Modi & Presets (Enums)** — hvac_mode, preset, fan_mode, swing_mode, effect, sound_mode u. a. (14 Fähigkeits-Attribute): „stell die Klima auf Eco", „Ventilator auf Nachtmodus".
- **Stoppen** — laufende Aktionen/Geräte anhalten.

## Fähigkeits-Bewusstsein (Cap-Awareness)
- Hestia kennt, **was ein Gerät kann** — und lehnt Unmögliches **ehrlich** ab statt es vorzutäuschen („die Lampe kann keine Farbe").
- **Wert-Klemmung** an echte Geräte-Grenzen (z. B. Ziel 90 % Helligkeit bleibt im erlaubten Band).
- Grundlage ist derselbe Cap-Vertrag, auf den das Modell trainiert wurde (train == serve).

## Zeitsteuerung ⏰ *(v23.9)*
- **Geplante Aktionen** — „schalt das Licht in 10 Minuten aus", „mach die Kaffeemaschine um 7 Uhr an". Legt eine getaggte Home-Assistant-Automation an, die zur Zeit feuert und sich selbst aufräumt.
- **Sofort vs. geplant** in EINEM Verb (optionaler `when`-Slot) — „mach's aus" schaltet sofort, „in einer Stunde aus" plant.
- **Verwalten** — laufende Pläne auflisten, abbrechen, verschieben.

## Auskunft & Lesen
- **Zustände** — „ist die Tür zu?", „wie warm ist es im Bad?".
- **Aggregate** — „welche Lampen sind an?", „ist irgendwo ein Fenster offen?".
- **Wetter & Sonnenstand** — „regnet es morgen?", „wann geht die Sonne unter?".

## Dialog & Wahrhaftigkeit
- **Rückfragen bei Mehrdeutigkeit** — „welche Lampe meinst du, Decke oder Stehlampe?" (mit Auswahl).
- **Listen-Loop** — Einkaufs-/To-do-Liste führen: mehrere Einträge nacheinander hinzufügen.
- **Ehrliche Ergebnisse** — „hat nicht geklappt", Teil-Erfolg („3 von 4"), Wert-außerhalb-des-Bereichs — nie ein falsches „erledigt".
- **Sicherheit** — sicherheitskritische Anfragen werden begründet abgelehnt.

## Betrieb & Steuerung
- **Selbst-gehostet** — Modell läuft auf eigener GPU-/CPU-Box (llama.cpp), nicht in Home Assistant.
- **Admin-Panel** — Geräte-Exposure (was der Assistent sehen darf), Helfer & Custom-Sätze anlegen/bearbeiten, Write-Limits & Mapping pro Gerät.
- **Request-Log** — die letzten Turns (Text → Modell-Call → Result → Antwort) admin-einsehbar zur Fehlersuche.

---

Modell & Gewichte: siehe [HuggingFace](https://huggingface.co/bennizone) · Für Neugierige: lass deinen
KI-Assistenten via [AGENTS.md](AGENTS.md) das Projekt erklären und dich durch die Installation führen.
