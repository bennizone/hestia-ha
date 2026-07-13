"""Exposure-Metadaten-Store (HAs `.storage` → automatisch im HA-Backup).

Eigener Store (nicht bloß am Label), damit Metadaten das **Deaktivieren überleben**
(Benni-Lock: Bettheizung im Sommer abgebaut → deaktivieren → im Winter 1 Klick zurück,
ohne Name/Aliase/Beschreibung neu zu kuratieren).

Drei Zustände pro Gerät = zwei Flags:
  - **Nicht hinzugefügt** → kein Record (bzw. `added=False`). Taucht nur im Add-Dialog auf.
  - **Aktiv**         → `added=True, active=True`  → dem Modell präsentiert (Sysprompt-Membership).
  - **Deaktiviert**   → `added=True, active=False` → Metadaten bleiben, unsichtbar fürs Modell,
                        KEINE Offline-Warnung.

Sysprompt-Membership = `added AND active` (s. house_builder.build_exposure).
"""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "hestia.exposure"
STORAGE_VERSION = 1

# Feld-Defaults eines Entity-Records. `added`/`active` sind die Zustands-Flags;
# der Rest sind kuratierbare Metadaten, die das Deaktivieren überleben.
# `limit_min`/`limit_max` = reale Prozent-Range fürs WRITE-Mapping (Arduino map(), s. mapping.py);
# Default 0/100 = Identität (kein Mapping). Nur für pct-steuerbare Entitäten (Licht/Medien/Rollladen/Lüfter)
# semantisch relevant; für den Rest schlicht ignoriert.
_RECORD_DEFAULTS: dict = {
    "added": False,
    "active": True,
    "llm_name": "",      # leer → house_builder fällt auf HA-friendly_name zurück
    "aliases": [],
    "description": "",
    "limit_min": 0,
    "limit_max": 100,
    # Live-Kontext-Eligibility (nur media_player): spielt dieser Player, sieht das Modell
    # „Läuft gerade …". Default True = einbezogen; bewusstes Opt-out schließt ihn aus (bleibt
    # aber steuerbar). Greift NUR für Member (added AND active) — s. conversation._live_context.
    "media_context": True,
}
# Nur diese Felder dürfen per WS-`set` gepatcht werden.
PATCHABLE = frozenset(_RECORD_DEFAULTS.keys())


class ExposureStore:
    """Dünner async-Wrapper um HAs `Store` mit In-Memory-Cache.

    Datenform on-disk: `{"entities": {entity_id: {added, active, llm_name, aliases, description}}}`.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, dict] | None = None   # entity_id -> record

    async def async_load(self) -> dict[str, dict]:
        if self._data is None:
            raw = await self._store.async_load()
            self._data = dict((raw or {}).get("entities", {}))
        return self._data

    def _record(self, entity_id: str) -> dict:
        """Record mit aufgefüllten Defaults (nie None). Kopie — kein Live-Alias."""
        base = dict(_RECORD_DEFAULTS)
        base.update(self._data.get(entity_id, {}))
        return base

    def get(self, entity_id: str) -> dict:
        """Effektiver Record (Defaults aufgefüllt). Voraussetzung: async_load lief."""
        assert self._data is not None, "async_load() zuerst aufrufen"
        return self._record(entity_id)

    def all_records(self) -> dict[str, dict]:
        """entity_id -> effektiver Record, für jeden hinzugefügten Eintrag."""
        assert self._data is not None, "async_load() zuerst aufrufen"
        return {eid: self._record(eid) for eid in self._data}

    def is_member(self, entity_id: str) -> bool:
        """Sysprompt-Membership: hinzugefügt UND aktiv."""
        rec = self.get(entity_id)
        return bool(rec["added"] and rec["active"])

    async def async_set(self, entity_id: str, patch: dict) -> dict:
        """Nur PATCHABLE-Felder mergen, persistieren, effektiven Record zurückgeben.

        `aliases` wird auf saubere String-Liste normalisiert. Ein Record mit `added=False`
        bleibt erhalten (Metadaten-Retention) — Aufräumen ist bewusst NICHT automatisch.
        """
        assert self._data is not None, "async_load() zuerst aufrufen"
        clean = {k: v for k, v in patch.items() if k in PATCHABLE}
        if "aliases" in clean:
            clean["aliases"] = [a.strip() for a in clean["aliases"]
                                if isinstance(a, str) and a.strip()]
        for k in ("limit_min", "limit_max"):     # int + auf 0..100 klemmen; Unfug fällt raus
            if k in clean:
                try:
                    clean[k] = max(0, min(100, int(clean[k])))
                except (TypeError, ValueError):
                    del clean[k]
        if "media_context" in clean:              # Live-Kontext-Flag → sauberer bool
            clean["media_context"] = bool(clean["media_context"])
        cur = dict(self._data.get(entity_id, {}))
        cur.update(clean)
        self._data[entity_id] = cur
        await self._async_save()
        return self._record(entity_id)

    async def async_rename(self, old_entity_id: str, new_entity_id: str) -> bool:
        """Entity-Rename-Migration: kuratierten Record von old→new mitziehen (Key = entity_id).

        Ohne diese Migration fiele eine umbenannte Entität still aus Modell+Panel (der Record
        verwaist unter dem alten Key), und alle kuratierten Metadaten (llm_name/Aliase/Beschreibung/
        limit_min-max/media_context) gingen effektiv verloren. Rückgabe True, wenn ein Record
        verschoben wurde. Kollidiert `new` mit einem (stale) Record — er gehörte einer inzwischen
        durch den Rename ersetzten Entität — gewinnt der umbenannte; der alte wird überschrieben."""
        assert self._data is not None, "async_load() zuerst aufrufen"
        if old_entity_id not in self._data:
            return False
        rec = self._data.pop(old_entity_id)
        if new_entity_id in self._data:
            _LOGGER.warning("Hestia exposure: Rename %s → %s überschreibt bestehenden Record",
                            old_entity_id, new_entity_id)
        self._data[new_entity_id] = rec
        await self._async_save()
        return True

    async def _async_save(self) -> None:
        await self._store.async_save({"entities": self._data})


def get_store(hass: HomeAssistant, entry_id: str | None = None) -> ExposureStore:
    """Den (einen) ExposureStore aus hass.data holen. Single-Instance je HA-Config."""
    bucket = hass.data.setdefault(DOMAIN, {})
    return bucket["_store"]
