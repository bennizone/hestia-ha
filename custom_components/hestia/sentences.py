"""Custom-Sätze — roher Fuzzy-Router VOR dem LLM (Bahn-1, PRODUCT_ROADMAP TEIL B).

Mehrere Sätze pro Aktion → normalisierter (near-)exakter Match → feuert genau EINE Ziel-Entität
(Szene/Skript/Schalter/Licht…), Modus EIN/AUS/toggle. Das LLM ist NICHT beteiligt: matcht ein
Satz, feuern wir die Aktion und geben einen kurzen Bestätigungstext zurück — kein /completion.

Design-Locks (Benni 2026-07-10):
  - Antwort-Text OPTIONAL pro Satz (leer → generisch „Ok.").
  - Ziel = feste Entität (global, keine Raum-Auflösung — das ist Bahn 2).
  - Bei mehreren Treffern gewinnt der BESTE (Exact vor 1-Edit; Gleichstand → erster = Anlege-Reihenfolge).
  - Präzision > Recall: nur exakt oder 1-Zeichen-Tippfehler matchen, sonst fängt der Router normale
    LLM-Anfragen fälschlich ab. **KEIN difflib-ratio** — das matcht Antonyme (Licht AN vs AUS) in langen
    Sätzen fälschlich (ratio ~0.93) und würde die GEGENTEIL-Aktion feuern. Edit-Distanz ≤1 ist immun
    (an→aus sind 2 Edits); der Space-invariante Key fängt „kino abend" ≈ „kinoabend".

Store in HAs `.storage` (→ HA-Backup), analog store.py (Exposure). Safemode-konsistent: beim Feuern
greift dasselbe effektive Deny wie im Executor — ein Satz auf Schloss/Alarm feuert nur bei unsafe_mode.
"""
from __future__ import annotations

import logging
import re
import uuid

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "hestia.sentences"
STORAGE_VERSION = 1

MAX_EDITS = 1               # erlaubte Levenshtein-Distanz (1 Zeichen); antonym-sicher (an/aus = 2 Edits)
MODES = ("on", "off", "toggle")
DEFAULT_RESPONSE = "Ok."
_UNSAFE_TEXT = "Das kann ich aus Sicherheitsgründen nicht."
_FIRE_FAIL_TEXT = "Das hat leider nicht geklappt."

# Domains, die der rohe Router ZUVERLÄSSIG feuern kann (Picker UI + WS-Validierung teilen diese Liste).
# scene/cover/button haben eigene Services (Dispatch in async_fire); der Rest geht generisch über
# homeassistant.turn_on/off/toggle. Bewusst NICHT dabei — der generische Pfad no-opt dort still (meldet
# aber „Erfolg"): lock/alarm (Safety + eigene lock/arm-Verben = Executor-Sache), vacuum (start/stop statt
# turn_*), automation (turn_on = AKTIVIEREN ≠ auslösen). Die gehören in einen späteren, expliziten Pass.
SUPPORTED_DOMAINS = frozenset({
    "scene", "script", "cover", "button", "input_button",
    "light", "switch", "fan", "input_boolean", "media_player",
    "climate", "humidifier", "siren", "group",
})
_COVER_SVC = {"on": "open_cover", "off": "close_cover", "toggle": "toggle"}
_GENERIC_SVC = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}

# Umlaut-Faltung: beide Seiten gleich normalisiert, darum ist die konkrete Faltung egal (ä→a, ö→o, ü→u, ß→ss).
_UMLAUT = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss"})


def _norm_key(text: str) -> str:
    """Match-Key: lower → Umlaute falten → ALLES außer Wortzeichen raus (inkl. Leerzeichen).

    Space-Strip macht „kino abend" == „kinoabend" (Join/Split-Varianz) per Exact-Match — ohne das
    gefährliche difflib-ratio. Antonyme bleiben getrennt: „lichtanimwohnzimmer" ≠ „lichtausimwohnzimmer"."""
    return re.sub(r"[^\w]+", "", (text or "").lower().translate(_UMLAUT), flags=re.UNICODE)


def _edit_le1(a: str, b: str) -> bool:
    """True wenn Levenshtein(a, b) ≤ 1 (früh-abbrechend, für kurze Sätze billig)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:                       # sicherstellen la ≤ lb
        a, b, la, lb = b, a, lb, la
    i = j = 0
    edited = False
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1; j += 1
        elif edited:
            return False              # zweite Abweichung → Distanz > 1
        else:
            edited = True
            if la == lb:              # Substitution
                i += 1; j += 1
            else:                     # Insertion in b
                j += 1
    return True                       # ≤1 Rest-Zeichen ist genau 1 Edit


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

    async def async_rename_target(self, old_entity_id: str, new_entity_id: str) -> int:
        """Entity-Rename-Migration: `target_entity` aller Sätze old→new umschreiben.

        Ohne das würde ein umbenanntes Ziel beim Feuern still ins Leere gehen (async_fire fällt
        auf `_FIRE_FAIL_TEXT`). Rückgabe = Anzahl migrierter Sätze."""
        assert self._data is not None, "async_load() zuerst aufrufen"
        n = 0
        for rec in self._data:
            if rec.get("target_entity") == old_entity_id:
                rec["target_entity"] = new_entity_id
                n += 1
        if n:
            await self._async_save()
        return n

    def match(self, text: str) -> tuple[dict, int] | None:
        """Bester Treffer über alle Sätze/Phrasen, oder None. Rückgabe (record, edits).

        Exact (0 Edits) schlägt 1-Edit; innerhalb gleicher Distanz gewinnt der zuerst angelegte
        Satz (Anlege-Reihenfolge). Antonym-sicher, s. Modul-Docstring."""
        assert self._data is not None, "async_load() zuerst aufrufen"
        key = _norm_key(text)
        if not key:
            return None
        near: dict | None = None      # bester 1-Edit-Kandidat (erster in Anlege-Reihenfolge)
        for rec in self._data:
            for ph in rec.get("phrases", []):
                pk = _norm_key(ph)
                if not pk:
                    continue
                if pk == key:
                    return (rec, 0)   # exakt — kann nicht besser werden
                if near is None and MAX_EDITS >= 1 and _edit_le1(pk, key):
                    near = rec
        return (near, 1) if near is not None else None

    async def _async_save(self) -> None:
        await self._store.async_save({"sentences": self._data})


async def async_fire(hass: HomeAssistant, rec: dict, context: Context, deny: list) -> str:
    """Ziel-Aktion per-Domain feuern, Bestätigungstext zurückgeben.

    Per-Domain-Dispatch, weil HAs generisches `homeassistant.turn_on/off/toggle` bei Domains OHNE
    turn_*-Service (cover/button/…) STILL no-opt (kein Fehler → sonst falscher „Erfolg"):
      - scene            → scene.turn_on (Szenen kennen nur turn_on)
      - cover            → open_cover / close_cover / toggle
      - button/input_button → press (Modus ohne Wirkung — momentane Aktion)
      - Rest             → homeassistant.turn_on/off/toggle (light/switch/fan/…)
    Safemode-konsistent: liegt die Ziel-Domain im effektiven Deny (lock/alarm ohne unsafe_mode),
    NICHT feuern → Sicherheits-Absage (spiegelt Executor `err_unsafe`)."""
    target = rec.get("target_entity", "")
    domain = target.split(".")[0]
    if domain in (deny or ()):
        return _UNSAFE_TEXT
    mode = rec.get("mode", "on")
    if domain == "scene":
        call_domain, service = "scene", "turn_on"
    elif domain == "cover":
        call_domain, service = "cover", _COVER_SVC.get(mode, "open_cover")
    elif domain in ("button", "input_button"):
        call_domain, service = domain, "press"
    else:
        call_domain, service = "homeassistant", _GENERIC_SVC.get(mode, "turn_on")
    try:
        await hass.services.async_call(call_domain, service, {"entity_id": target},
                                       blocking=True, context=context)
    except Exception as e:  # noqa: BLE001 — Ziel weg / Service-Fehler → ehrlicher Fallback
        _LOGGER.warning("Hestia custom-sentence fire failed (%s → %s.%s): %s",
                        target, call_domain, service, e)
        return _FIRE_FAIL_TEXT
    return (rec.get("response") or "").strip() or DEFAULT_RESPONSE


def get_sentence_store(hass: HomeAssistant) -> SentenceStore | None:
    """Den (einen) SentenceStore aus hass.data holen (single-instance je HA-Config), oder None,
    falls (noch) nicht geladen — der Aufrufer degradiert dann (Router überspringen)."""
    return hass.data.get(DOMAIN, {}).get("_sentences")
