#!/usr/bin/env python3
"""Härtetest-Setup: das VOLLE Haus exponieren (alle Geräte-Domains + ein paar Sensoren).

Setzt `conversation.should_expose` in `.storage/core.entity_registry` (options haben Vorrang
vor dem exposed_entities-Store) für alle steuerbaren Geräte-Domains + eine begrenzte Sensor-
Auswahl. Läuft mit sudo (Store gehört root), danach HA neustarten.

    sudo python3 expose_all.py            # exponiert Geräte + N Sensoren
    sudo python3 expose_all.py --reset    # setzt ALLES auf should_expose=False
"""
import json, sys

REG = "/home/hadmin/ha-testbed/config_monster/.storage/core.entity_registry"
DEVICE_DOMAINS = {"light", "switch", "climate", "cover", "fan", "media_player", "lock", "vacuum"}
SENSOR_LIMIT = 12   # ein paar Sensoren für get_state-Read-Coverage


def main(reset: bool):
    r = json.load(open(REG))
    ents = r["data"]["entities"]
    n_on = 0
    n_sensor = 0
    for e in ents:
        dom = e["entity_id"].split(".")[0]
        if reset:
            expose = False
        elif dom in DEVICE_DOMAINS:
            expose = True
        elif dom == "sensor" and n_sensor < SENSOR_LIMIT:
            expose = True
            n_sensor += 1
        else:
            expose = False
        opts = e.get("options") or {}
        conv = dict(opts.get("conversation") or {})
        conv["should_expose"] = expose
        opts["conversation"] = conv
        e["options"] = opts
        n_on += expose
    json.dump(r, open(REG, "w"), ensure_ascii=False)
    print(f"{'reset: all off' if reset else 'exposed'}: {n_on} entities ({n_sensor} sensors)")


if __name__ == "__main__":
    main("--reset" in sys.argv)
