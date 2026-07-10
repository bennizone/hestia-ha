"""Hestia ConversationEntity — der cap-v2 Blackbox-Loop.

Architektur (HA_INTEGRATION_DRAFT.md):
  Text rein → System-Prompt aus HA-Registry (hestia_cap.render + „Aktueller Raum:") → /completion →
    Tool-Block? → hestia_cap.parse → Executor (Wire→Entität→hass.services) → rev2-Result → nächste Iter (≤N)
    freier Text? → fertig, an Assist zurück (Mikro offen bei „?")
  Loop erschöpft → Addon-Fehlermeldung (KEIN LLM).

train==serve: Prompt LOKAL rendern (LFM2.5-Template via hestia_cap.render_prompt + INNERE Tools)
+ POST /completion. NIEMALS /v1/chat/completions (llama.cpp #23838 — s. SERVE_PIPELINE.md).
"""
from __future__ import annotations

import json
import logging
import random

import aiohttp
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (DOMAIN, CONF_LLAMA_URL, CONF_LOOP_DEPTH, CONF_DENY,
                    CONF_UNSAFE_MODE, DEFAULT_LOOP_DEPTH, DEFAULT_DENY, DEFAULT_UNSAFE_MODE,
                    LOOP_EXHAUSTED_TEXTS, effective_deny)
from .hestia_cap import (TOOL_CALL_START, STOP, all_tool_defs, parse, render_prompt,
                         render_system_content)
from .hestia_cap import result as R
from .house_builder import build_exposure, build_house
from .executor import execute_calls
from .sentences import async_fire as sentence_fire, get_sentence_store

_LOGGER = logging.getLogger(__name__)

_MAX_NEW_TOKENS = 128
_HTTP_TIMEOUT = 120
_WEEKDAYS_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")

# Truthfulness-Guard (RESULT_SCHEMA §4): bei ok:false darf die Antwort keinen Erfolg behaupten.
_SUCCESS_MARKERS = ("erledigt", "eingeschaltet", "ausgeschaltet", "ist an", "ist aus", "mach ich",
                    "geschaltet", "gestellt", "aktiviert", "geöffnet", "geschlossen", "erhöht", "reduziert")
_ERROR_FALLBACK = {
    "unsafe": "Das kann ich aus Sicherheitsgründen nicht.",
    "entity_not_found": "So ein Gerät kenne ich nicht.",
    "no_targets": "Dazu habe ich kein passendes Gerät gefunden.",
    "no_data": "Das konnte ich nicht auslesen.",
    "not_controllable": "Das lässt sich so nicht steuern.",
    "timeout": "Das hat gerade nicht geklappt, versuch es bitte nochmal.",
    "unparseable": "Das habe ich nicht ganz verstanden.",
}
_ERROR_FALLBACK_DEFAULT = "Das hat leider nicht geklappt."


def _guard_truthful(answer: str, last_result: dict | None) -> str:
    """Ersetzt eine Erfolgs-Behauptung durch ehrlichen Fallback, wenn das letzte Result ok:false war.
    Partial (ok:false MIT targets) ist ausgenommen — da ist Teil-Erfolg legitim."""
    if not last_result or last_result.get("ok", True) or last_result.get("targets"):
        return answer
    if any(m in answer.lower() for m in _SUCCESS_MARKERS):
        err = last_result.get("error", "")
        _LOGGER.warning("Hestia truthfulness-guard: Erfolg behauptet trotz ok:false (%s) → ersetzt. war=%r",
                        err, answer)
        return _ERROR_FALLBACK.get(err, _ERROR_FALLBACK_DEFAULT)
    return answer


def _looks_like_tool(text: str) -> bool:
    """Grobe Tool-Block-Heuristik (loop_bench._has_tool): Wrapper-Token oder „[…]"-Liste."""
    t = text.strip()
    return TOOL_CALL_START in t or t.startswith("[") or t.startswith("<|tool")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([HestiaAgent(hass, entry)])


class HestiaAgent(conversation.ConversationEntity):
    """Blackbox-Conversation-Agent. Nutzt HAs llm-API-Tool-Layer NICHT — eigener Loop."""

    _attr_has_entity_name = True
    _attr_name = "Hestia"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = entry.entry_id

    # Config LIVE aus dem Config-Entry lesen (nicht im __init__ cachen): das Panel schreibt
    # Allgemein-Settings via `async_update_entry`, was `entry.data` in-place ersetzt — dieselbe
    # Entry-Referenz. So greifen URL/Loop-Tiefe/Safemode sofort, ohne Reload/Entity-Neubau.
    @property
    def _url(self) -> str:
        return self.entry.data[CONF_LLAMA_URL]

    @property
    def _depth(self) -> int:
        return self.entry.data.get(CONF_LOOP_DEPTH, DEFAULT_LOOP_DEPTH)

    @property
    def _deny(self) -> list:
        return effective_deny(self.entry.data.get(CONF_DENY, DEFAULT_DENY),
                              self.entry.data.get(CONF_UNSAFE_MODE, DEFAULT_UNSAFE_MODE))

    @property
    def supported_languages(self) -> list[str] | str:
        return ["de"]

    # ── Loop ─────────────────────────────────────────────────────────────────
    async def _async_handle_message(
        self, user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        # 0. Custom-Sätze: roher Router VOR dem LLM (Bahn-1). Matcht ein Satz (exact/1-Edit),
        #    feuern wir die Ziel-Aktion direkt und antworten kurz — LLM/Loop bleiben außen vor.
        store = get_sentence_store(self.hass)
        hit = store.match(user_input.text) if store else None
        if hit is not None:
            rec, edits = hit
            _LOGGER.debug("Hestia custom-sentence hit id=%s edits=%d target=%s mode=%s",
                          rec.get("id"), edits, rec.get("target_entity"), rec.get("mode"))
            answer = await sentence_fire(self.hass, rec, user_input.context, self._deny)
            # Router-Aktion ist terminal → Mikro zu (auch wenn der Admin-Text auf „?" endet).
            return self._result(user_input, chat_log, answer, continue_conversation=False)

        # 1. Haus + Exposure aus der HA-Registry; System-Prompt (train==serve-Naht)
        exposure = build_exposure(self.hass)   # Quelle = Config-Store (Panel-kuratiert)
        house = build_house(self.hass, exposure)
        system_content = render_system_content(house)   # statischer, cachebarer Präfix (ohne Raum/Zeit)
        live_context = self._live_context(user_input, exposure)   # volatiler Schwanz = 2. System-Message

        tools = all_tool_defs()
        msgs = [{"role": "system", "content": system_content}]
        if live_context:
            msgs.append({"role": "system", "content": live_context})   # nach den Tools (train==serve)
        msgs.append({"role": "user", "content": user_input.text})

        _LOGGER.debug("Hestia in=%r exposure=%d live=%r", user_input.text, len(exposure), live_context)

        # 2. Loop ≤ depth
        answer: str | None = None
        last_result: dict | None = None
        for i in range(self._depth):
            text = await self._complete(msgs, tools)
            _LOGGER.debug("Hestia iter %d model=%r", i, text)
            if _looks_like_tool(text):
                parsed = parse(text)
                if not parsed.ok:
                    result = json.dumps(R.err_unparseable(), ensure_ascii=False, separators=(",", ":"))
                else:
                    result = await execute_calls(self.hass, parsed, exposure,
                                                 user_input.context, self._deny,
                                                 user_input.device_id)
                _LOGGER.debug("Hestia iter %d result=%s", i, result)
                try:
                    last_result = json.loads(result)
                except ValueError:
                    last_result = None
                msgs.append({"role": "assistant", "content": text})
                msgs.append({"role": "tool", "content": result})
                continue
            answer = text        # freier Text → fertig
            break

        # 3. Loop erschöpft → variabler Fehlertext (KEIN LLM)
        if answer is None:
            answer = random.choice(LOOP_EXHAUSTED_TEXTS)
        else:
            answer = _guard_truthful(answer, last_result)   # kein falscher Erfolg bei ok:false

        return self._result(user_input, chat_log, answer)

    # ── Live-Kontext-Schwanz (volatil, nach den Tools — prefix-cache-schonend) ──
    def _live_context(self, user_input, exposure: dict[str, dict]) -> str:
        """Datum/Tag/Zeit · Raum (device→area; mobil→kein fester Raum) · laufende Timer/Medien.
        PROTOTYP (v23.1): Format provisorisch; train==serve-Lock folgt im Generator.

        Medien-Eligibility (Benni-Lock 2026-07-10, „Nur exposte + opt-out"): ein spielender
        media_player erscheint NUR, wenn er Exposure-Member ist (added AND active — `exposure`
        enthält genau die) UND sein `media_context`-Flag gesetzt ist (Default True). So leakt kein
        nicht-kuratierter Player, und einzelne lassen sich bewusst ausschließen (bleiben steuerbar)."""
        from homeassistant.util import dt as dt_util
        now = dt_util.now()
        parts = [f"Aktueller Kontext: {_WEEKDAYS_DE[now.weekday()]}, "
                 f"{now.strftime('%d.%m.%Y')}, {now.strftime('%H:%M')} Uhr."]
        room = self._device_area(user_input.device_id)
        parts.append(f"Raum: {room}." if room else "Raum: unterwegs, kein fester Raum.")
        active = []
        for st in self.hass.states.async_all("timer"):
            if st.state == "active":
                nm = st.attributes.get("friendly_name") or "Timer"
                rem = st.attributes.get("remaining")
                active.append(f"Timer {nm}" + (f" (noch {rem})" if rem else ""))
        for st in self.hass.states.async_all("media_player"):
            if st.state != "playing":
                continue
            rec = exposure.get(st.entity_id)
            if not rec or not rec.get("media_context", True):   # nicht exposed ODER bewusst ausgeschlossen
                continue
            active.append(f"Medienwiedergabe {st.attributes.get('friendly_name') or ''}".strip())
        if active:
            parts.append("Läuft gerade: " + "; ".join(active) + ".")
        return " ".join(parts)

    # ── HTTP: /completion (raw, lokaler Render) ────────────────────────────────
    async def _complete(self, msgs: list[dict], tools: list[dict]) -> str:
        prompt = render_prompt(msgs, tools=tools, add_generation_prompt=True)
        body = {"prompt": prompt, "n_predict": _MAX_NEW_TOKENS, "temperature": 0.0,
                "cache_prompt": True, "stop": [STOP]}
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(self._url.rstrip("/") + "/completion", json=body,
                                    timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT)) as resp:
                data = await resp.json()
        except Exception as e:  # noqa: BLE001 — Netz/LLM-Fehler → leerer Text → Loop degradiert
            _LOGGER.error("Hestia /completion request failed: %s", e)
            return ""
        return (data.get("content") or "").strip()

    # ── Helfer ─────────────────────────────────────────────────────────────────
    def _device_area(self, device_id: str | None) -> str | None:
        """Voice-Satelliten-Gerät → Area-Name (Ziel-Defaulting M5)."""
        if not device_id:
            return None
        dev = dr.async_get(self.hass).async_get(device_id)
        if dev and dev.area_id:
            area = ar.async_get(self.hass).async_get_area(dev.area_id)
            return area.name if area else None
        return None

    def _result(self, user_input, chat_log, answer: str,
                continue_conversation: bool | None = None) -> conversation.ConversationResult:
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(answer)
        if continue_conversation is None:
            continue_conversation = answer.rstrip().endswith("?")   # „?" → Mikro offen
        return conversation.ConversationResult(
            response=response,
            conversation_id=chat_log.conversation_id,
            continue_conversation=continue_conversation,
        )
