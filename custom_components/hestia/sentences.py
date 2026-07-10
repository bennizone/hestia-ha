"""Custom-Sätze — roher Fuzzy-Router VOR dem LLM (Bahn-1, PRODUCT_ROADMAP TEIL B).

Mehrere Sätze pro Aktion → normalisierter (near-)exakter Match → feuert genau EINE Ziel-Entität
(Szene/Skript/Schalter/Licht…), Modus EIN/AUS/toggle. Das LLM ist NICHT beteiligt: matcht ein
Satz, feuern wir die Aktion und geben einen kurzen Bestätigungstext zurück — kein /completion.

Design-Locks (Benni 2026-07-10):
  - Antwort-Text OPTIONAL pro Satz (leer → generisch „Ok.").
  - Ziel = feste Entität (global, keine Raum-Auflösung — das ist Bahn 2).
  - Bei mehreren Treffern gewinnt der BESTE Fuzzy-Score (Gleichstand → erster = Anlege-Reihenfolge).
  - Präzision > Recall: nur (near-)exakt matchen (ratio ≥ MATCH_THRESHOLD), sonst fängt der Router
    normale LLM-Anfragen fälschlich ab.

Store in HAs `.storage` (→ HA-Backup), analog store.py (Exposure). Safemode-konsistent: beim Feuern
greift dasselbe effektive Deny wie im Executor — ein Satz auf Schloss/Alarm feuert nur bei unsafe_mode.
"""
from __future__ import annotations

import difflib
import logging
import re
import uuid

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "hestia.sentences"
STORAGE_VERSION = 1

MATCH_THRESHOLD = 0.9        # near-exact; darunter kein Router-Treffer (LLM übernimmt)
MODES = ("on", "off", "toggle")
DEFAULT_RESPONSE = "Ok."
_UNSAFE_TEXT = "Das kann ich aus Sicherheitsgründen nicht."
_FIRE_FAIL_TEXT = "Das hat leider nicht geklappt."

# Umlaut-Faltung + Satzzeichen-Strip: beide Seiten (Eingabe & gespeicherter Satz) gleich normalisiert,
# darum ist die konkrete Faltung egal, solange konsistent (ä→a, ö→o, ü→u, ß→ss).
_UMLAUT = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss"})


def normalize(text: str) -> str:
    """lower → Umlaute falten → Satzzeichen zu Space → Whitespace kollabieren → trim."""
    t = (text or "").lower().translate(_UMLAUT)
    t = re.sub(r"[^\w ]+", " ", t, flags=re.UNICODE)   # Satzzeichen/Sonderzeichen weg
    return re.sub(r"\s+", " ", t).strip()


class SentenceStore:
    """Dünner async-Wrapper um HAs `Store`. On-disk: `{"sentences": [ {record}, … ]}`.

    Record: `{id, phrases[], target_entity, mode: on|off|toggle, response}`.
    Reihenfolge = Anlege-Reihenfolge (Tie-Break beim Match).
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: list[dict] | None = None

    async def async_load(self) -> list[dict]:
        if self._data is None:
            raw = await self._store.async_load()
            self._data = list((raw or {}).get("sentences", []))
        return self._data

    def all(self) -> list[dict]:
        assert self._data is not None, "async_load() zuerst aufrufen"
        return list(self._data)

    async def async_add(self, phrases: list[str], target_entity: str,
                        mode: str, response: str = "") -> dict:
        assert self._data is not None, "async_load() zuerst aufrufen"
        rec = {
            "id": uuid.uuid4().hex[:8],
            "phrases": [p.strip() for p in phrases if isinstance(p, str) and p.strip()],
            "target_entity": target_entity,
            "mode": mode if mode in MODES else "on",
            "response": (response or "").strip(),
        }
        self._data.append(rec)
        await self._async_save()
        return rec

    async def async_delete(self, sentence_id: str) -> bool:
        assert self._data is not None, "async_load() zuerst aufrufen"
        before = len(self._data)
        self._data = [r for r in self._data if r.get("id") != sentence_id]
        if len(self._data) < before:
            await self._async_save()
            return True
        return False

    def match(self, text: str) -> tuple[dict, float] | None:
        """Bester (near-)exakter Treffer über alle Sätze/Phrasen, oder None.

        ratio ≥ MATCH_THRESHOLD zählt; höchster Score gewinnt, strikt > → bei Gleichstand
        gewinnt der zuerst angelegte Satz (Anlege-Reihenfolge)."""
        assert self._data is not None, "async_load() zuerst aufrufen"
        norm = normalize(text)
        if not norm:
            return None
        best: dict | None = None
        best_score = -1.0
        for rec in self._data:
            for ph in rec.get("phrases", []):
                np = normalize(ph)
                if not np:
                    continue
                score = 1.0 if np == norm else difflib.SequenceMatcher(None, np, norm).ratio()
                if score >= MATCH_THRESHOLD and score > best_score:
                    best_score, best = score, rec
        return (best, best_score) if best is not None else None

    async def _async_save(self) -> None:
        await self._store.async_save({"sentences": self._data})


async def async_fire(hass: HomeAssistant, rec: dict, context: Context, deny: list) -> str:
    """Ziel-Aktion feuern, Bestätigungstext zurückgeben.

    Safemode-konsistent: liegt die Ziel-Domain im effektiven Deny (lock/alarm ohne unsafe_mode),
    NICHT feuern → Sicherheits-Absage (spiegelt Executor `err_unsafe`). Szenen kennen nur
    turn_on; alles andere geht über `homeassistant.turn_on/off/toggle` (domain-generisch)."""
    target = rec.get("target_entity", "")
    domain = target.split(".")[0]
    if domain in (deny or ()):
        return _UNSAFE_TEXT
    mode = rec.get("mode", "on")
    try:
        if domain == "scene":
            await hass.services.async_call("scene", "turn_on", {"entity_id": target},
                                           blocking=True, context=context)
        else:
            svc = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}.get(mode, "turn_on")
            await hass.services.async_call("homeassistant", svc, {"entity_id": target},
                                           blocking=True, context=context)
    except Exception as e:  # noqa: BLE001 — Ziel weg / Service-Fehler → ehrlicher Fallback
        _LOGGER.warning("Hestia custom-sentence fire failed (%s → %s): %s", target, mode, e)
        return _FIRE_FAIL_TEXT
    return (rec.get("response") or "").strip() or DEFAULT_RESPONSE


def get_sentence_store(hass: HomeAssistant) -> SentenceStore:
    """Den (einen) SentenceStore aus hass.data holen (single-instance je HA-Config)."""
    return hass.data.setdefault(DOMAIN, {})["_sentences"]
