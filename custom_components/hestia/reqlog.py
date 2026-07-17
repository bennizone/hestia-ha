"""reqlog — rotierendes Request-Log der Conversation-Turns (Observability, serve-only).

Zweck: nachvollziehen, was hestia-ha bekommt, tut und ausspuckt — ohne auf ephemeres Debug-Logging
angewiesen zu sein. Fängt intermittierende Fälle (z.B. Area-Awareness-Misroutes), weil die letzten
`REQLOG_MAX` Turns rotierend erhalten bleiben (in-memory deque + persistenter Store → überlebt Neustart).

Ein Eintrag pro Nutzer-Turn:
  ts · text (Eingabe) · device_id · room (aufgelöste Caller-Area) · exposure_n · path
  (custom_sentence|loop|exhausted) · iters[{model, result}] · answer (finaler Sprech-Text).

KEIN Modell-/Prompt-Einfluss (train==serve unberührt) — reine Serve-Beobachtung. Admin-only lesbar
via WS `hestia/log/recent`.
"""
from __future__ import annotations

import logging
from collections import deque

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, REQLOG_MAX

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "hestia.reqlog"
STORAGE_VERSION = 1
_SAVE_DELAY = 8.0                 # debounced Persist (Schreib-Last niedrig halten)
_MAX_FIELD = 4000                 # pro String-Feld kappen (Result-JSON kann groß sein)


def _clip(v):
    s = v if isinstance(v, str) else str(v)
    return s if len(s) <= _MAX_FIELD else s[:_MAX_FIELD] + "…[clip]"


class RequestLog:
    """Bounded Ring-Buffer der letzten Turns, debounced auf `.storage/hestia.reqlog` persistiert."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._buf: deque = deque(maxlen=REQLOG_MAX)

    async def async_load(self) -> None:
        try:
            raw = await self._store.async_load()
        except Exception as e:  # noqa: BLE001 — korrupter Store darf Setup nicht killen
            _LOGGER.warning("reqlog: Store-Load fehlgeschlagen (%s) — starte leer", e)
            raw = None
        entries = (raw or {}).get("entries") if isinstance(raw, dict) else None
        if isinstance(entries, list):
            self._buf.extend(entries[-REQLOG_MAX:])

    def record(self, *, text, device_id, room, exposure_n, path, iters, answer) -> None:
        """Einen Turn festhalten (in-memory sofort, Persist debounced)."""
        entry = {
            "ts": dt_util.now().isoformat(timespec="seconds"),
            "text": _clip(text or ""),
            "device_id": device_id,
            "room": room,
            "exposure_n": exposure_n,
            "path": path,
            "iters": [{"model": _clip(it.get("model", "")),
                       "result": _clip(it.get("result", ""))} for it in (iters or [])],
            "answer": _clip(answer or ""),
        }
        self._buf.append(entry)
        self._store.async_delay_save(lambda: {"entries": list(self._buf)}, _SAVE_DELAY)

    def recent(self, limit: int | None = None) -> list:
        items = list(self._buf)
        items.reverse()                                      # neueste zuerst
        return items[:limit] if limit else items


def get_reqlog(hass: HomeAssistant) -> RequestLog | None:
    return hass.data.get(DOMAIN, {}).get("_reqlog")
