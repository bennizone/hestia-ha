# End-to-End-Härtetest

Fährt das **volle Haus** (alle exponierten Geräte) gegen ein echtes HA + Modell und misst,
ob NL-Requests real die richtigen Entitäts-States erzeugen. Misst **end-to-end** (Modell +
Integration); Fehler werden diagnostisch klassifiziert, damit Modell-Schwäche von
Integrationsbug getrennt werden kann.

## Ablauf
```bash
# 1. Volles Haus exponieren (auf der HA-Box, Store gehört root):
sudo python3 expose_all.py          # alle Geräte-Domains + 12 Sensoren
#    danach HA neu starten + Debug-Log an:
#    docker restart ha-testbed
#    logger.set_level {custom_components.hestia: debug}

# 2. Harness laufen lassen (AUF der HA-Box — liest home-assistant.log für Turn-Traces):
python3 hardening.py                 # alle generierten Fälle
python3 hardening.py --limit 40      # Kurz-Smoke

# zurücksetzen:
sudo python3 expose_all.py --reset
```

## Methodik
- Fälle werden **capability-aware** aus der Live-Registry generiert (Brightness nur bei
  dimmbaren Lampen, Position nur bei positions-fähigen Covern, …).
- Jede mutierende Anfrage setzt ihre **eigene Baseline** (Gegenteil des Ziels) → interferenzfrei,
  Reihenfolge egal. Nach dem Request wird der **echte HA-State** zurückgelesen und geprüft
  (nicht nur, was das Modell sagt).
- `unavailable`/`unknown`-Entitäten und degenerierte Demo-Spiegel (`switch.heat_*`, kollidiert
  mit `climate`-Namen) werden übersprungen.
- Fehler-Klassen: `model_no_tool` (Text statt Tool) · `resolve` (Tool ok:false) · `executor`
  (ok:true aber State falsch — inkl. Modell-Verb/Ziel-Fehler) · `answer` (get_state-Wert falsch)
  · `safety_breach` · `false_success` · `not_clarify`. Der emittierte Tool-Call steht bei jedem
  Fehler dabei → Modell-Fehler vs. echter Bug direkt ablesbar.

## Ergebnis 25k-Q8-350m (2026-07-08, `results_25k_2026-07-08.json`)
**98/108 = 90,7 %** über 110 Requests. **1 echter Executor-Bug gefunden+gefixt:**
`homeassistant.turn_on/off` aktuiert Cover NICHT → turn_on/off routet Cover jetzt auf
`cover.open_cover`/`close_cover` (turn_on danach 100 %). Die restlichen 10 Fehler sind
**ausnahmslos 25k-Modell-Schwächen** (per emittiertem Tool-Call belegt), Ziele fürs Voll-Training:
- „schließe {Cover}" → Modell emittiert `turn_on` statt `turn_off` (5×; Cover-close unter-trainiert).
- Name-Kürzung bei Kollision („tado Thermostat" → „Thermostat").
- Multi-Call: Modell emittiert nur eine der zwei Aktionen.
- clarify-vs-pick bei Mehrdeutigkeit; Grenzfall-Refuse.
