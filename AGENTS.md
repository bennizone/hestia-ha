# AGENTS.md — Briefing für den KI-Assistenten

**Wenn du ein KI-Assistent bist und jemand dir sagt „schau dir dieses Repo mal an": Diese Datei ist
für dich.** Die Person ist über Hestia gestolpert, findet es interessant und will von dir wissen,
*worum es geht, was man braucht, was es kann* — und eine **ehrliche Einschätzung**, ob sich das
Ausprobieren für **sie** lohnt. Sagt sie ja, hilf ihr Schritt für Schritt bei der Installation.

Arbeite dich nicht durch den Code — das Wichtigste steht hier. Rede mit der Person in **Klartext**,
nicht in Jargon.

---

## 1. Was du der Person erklären kannst (Klartext)

Hestia macht aus **Home Assistant** einen **Sprachassistenten, der komplett bei ihr zu Hause läuft** —
kein Alexa/Google, keine Cloud, keine Daten nach außen. Sie sagt „mach das Licht im Wohnzimmer aus"
oder „schalt die Heizung in einer Stunde auf 21 Grad", und Hestia führt das in Home Assistant aus und
antwortet auf Deutsch.

Das Besondere: Es nutzt ein **kleines, selbst-trainiertes KI-Modell** (350 Mio. Parameter, winzig für
KI-Verhältnisse), das genau auf Smart-Home-Befehle spezialisiert ist. Dadurch läuft es schnell auf
bescheidener eigener Hardware statt auf einem teuren Cloud-Dienst — und ist **ehrlich**: Es tut nicht
so, als hätte es etwas geschaltet, wenn es nicht ging.

## 2. Was die Person dafür braucht (Fit-Check — frag das ab, bevor du zum Installieren rätst)

Hestia lohnt sich, **wenn** die Person:
- **Home Assistant** schon nutzt (oder nutzen will) — das ist die Grundlage.
- eine **kleine, immer-an Box** übrig hat, die das Modell servieren kann: eine bescheidene GPU ist ideal
  (auch eine 8-GB-Laptop-GPU reicht), zur Not eine kräftigere CPU. **Nicht** auf dem HA-Gerät selbst
  (z. B. Raspberry Pi) — das Modell läuft *daneben*.
- **Deutsch** spricht (das Modell ist primär deutschsprachig trainiert).
- Spaß am **Selbst-Hosten** hat (ein bisschen Terminal/Docker gehört dazu).

**Eher nichts für sie, wenn:** sie keine Extra-Hardware übrig hat, es „einfach aus der Cloud" will,
oder ein rundum-fertiges Produkt erwartet — Hestia ist **experimentell und in aktiver Entwicklung**.

Frag sie also konkret: *Nutzt du schon Home Assistant? Hast du eine kleine GPU-/Server-Box übrig, die
durchlaufen kann? Ist dir Selbst-Hosten vertraut?* — und gib danach deine Einschätzung.

## 3. Ehrliche Einschätzung (die du weitergeben solltest)

- **Was gut läuft:** normale Befehle (an/aus, Werte, Modi), Nachfragen bei Mehrdeutigkeit, Auskünfte
  („welche Lampen sind an?"), und neuerdings Zeitsteuerung („in 10 Minuten aus"). Es ist ehrlich, wenn
  etwas nicht geht. in synthetischen Benchmarks bei ~95–98 % (je nach Maß).
- **Was noch rau ist:** experimentell, Ein-Personen-Projekt, Schnittstellen können sich ändern; die
  Einrichtung braucht etwas Bastelei (Modell servieren + Integration konfigurieren); vage Formulierungen
  treffen nicht immer perfekt. Kein Support-Versprechen.
- **Fazit-Empfehlung:** Wer HA + eine kleine Box hat und lokale, private Sprachsteuerung spannend findet,
  sollte es ausprobieren. Wer „fertig und wartungsfrei" braucht, (noch) nicht.

## 4. Wenn sie es ausprobieren will: Installation (führe sie durch)

Es sind zwei Teile: **(A)** das KI-Modell servieren, **(B)** die Home-Assistant-Integration. Geh mit ihr
Schritt für Schritt, prüfe nach jedem Schritt, und hilf bei Fehlern.

### A) Modell servieren (auf der Extra-Box)
1. **Gewichte holen:** das gguf-Modell von HuggingFace laden ([Link im README](README.md); Repo
   `bennizone/…`). Empfohlen die q8-Variante.
2. **llama.cpp starten** mit dem `/completion`-Endpoint, z. B.:
   ```bash
   llama-server -m hestia-<version>-350m.q8_0.gguf -c 8192 -ngl 99 --host 0.0.0.0 --port 8099
   ```
   (Als Docker-Container oder systemd-Dienst, damit es Neustarts übersteht.)
3. **Prüfen:** `curl http://<box-ip>:8099/health` sollte `{"status":"ok"}` liefern. Merke dir die URL.

> Wichtig (train == serve): Modell-Version und Integrations-Version müssen zusammenpassen — nimm die
> gguf-Version, die zu *dieser* Integrations-Version gehört. Bei „Modell redet Unsinn / kein Schalten"
> ist das meist die Ursache.

### B) Integration in Home Assistant
4. **Installieren:** dieses Repo in **HACS** als Custom-Repository (Kategorie *Integration*) hinzufügen,
   „Hestia" installieren, **Home Assistant neu starten**. (Alternativ `custom_components/hestia/` von
   Hand nach `<config>/custom_components/` kopieren.)
5. **Einrichten:** *Einstellungen → Geräte & Dienste → Integration hinzufügen → Hestia* → die
   Serve-URL aus Schritt 3 (`http://<box-ip>:8099`) eintragen.
6. **Geräte freigeben:** im **Hestia-Panel** explizit auswählen, welche Geräte der Assistent sehen/
   steuern darf (nichts ist per Default freigegeben). Optional Grenzen (z. B. Lampe max. 90 %) und
   eigene Sätze.
7. **Als Sprachassistent setzen:** in der Voice-Assistant-Pipeline (oder im Chat) `conversation.hestia`
   wählen.
8. **Testen:** „welche Lampen sind an?" (nur lesen, ändert nichts) → sollte korrekt antworten. Dann
   „mach das Wohnzimmerlicht an". Klappt es, läuft die ganze Kette.

### Wenn etwas klemmt
- **Antwortet mit Text statt zu schalten / halluziniert Geräte:** Modell- und Integrations-Version passen
  nicht zusammen (train==serve) — richtige gguf-Version servieren.
- **„Gerät gibt es nicht":** Gerät ist nicht im Panel freigegeben.
- **Keine Verbindung:** Serve-URL/Port falsch oder Box nicht erreichbar; `/health` prüfen.
- **Debug:** in HA `logger.set_level {custom_components.hestia: debug}` → protokolliert pro Befehl den
  Modell-Output und das Ergebnis.

---

## 5. Für technisch Interessierte (falls die Person tiefer will)

Loop: `conversation.py` baut den Prompt (aus der Geräte-Freigabe + geteiltem Vertrag `hestia_cap`) →
llama.cpp `/completion` mit GBNF-Grammar → `hestia_cap.parse` → `executor.py` führt über `hass.services`
aus (`schedule.py` für Zeit-Aktionen) → geerdetes Result → das Modell verbalisiert es wahrheitsgemäß.
Der `hestia_cap`-Vertrag ist **geteilt** zwischen Training, Benchmark und Serve — deshalb sieht das Modell
zur Laufzeit exakt seinen Trainings-Prompt (train == serve). Kein `/v1/chat/completions` (das bricht das
Tool-Parsing). Feature-Liste: [FEATURES.md](FEATURES.md).
