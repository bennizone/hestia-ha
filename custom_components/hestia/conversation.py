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

import logging
import random

import aiohttp
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (DOMAIN, CONF_LLAMA_URL, CONF_LOOP_DEPTH, CONF_EXPOSURE, CONF_DENY,
                    DEFAULT_LOOP_DEPTH, DEFAULT_DENY, LOOP_EXHAUSTED_TEXTS)
from .hestia_cap import (TOOL_CALL_START, STOP, all_tool_defs, parse, render_prompt,
                         render_system_content)
from .house_builder import build_exposure, build_house
from .executor import execute_calls

_LOGGER = logging.getLogger(__name__)

_MAX_NEW_TOKENS = 128
_HTTP_TIMEOUT = 120


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
        self._url = entry.data[CONF_LLAMA_URL]
        self._depth = entry.data.get(CONF_LOOP_DEPTH, DEFAULT_LOOP_DEPTH)
        self._deny = entry.data.get(CONF_DENY, DEFAULT_DENY)

    @property
    def supported_languages(self) -> list[str] | str:
        return ["de"]

    # ── Loop ─────────────────────────────────────────────────────────────────
    async def _async_handle_message(
        self, user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        # 1. Haus + Exposure aus der HA-Registry; System-Prompt (train==serve-Naht)
        exposure = build_exposure(self.hass, self.entry.data.get(CONF_EXPOSURE))
        house = build_house(self.hass, exposure)
        system_content = render_system_content(house)
        room = self._device_area(user_input.device_id)
        if room:
            system_content += f"\n\nAktueller Raum: {room}."   # M5, byte-gleich zum Generator

        tools = all_tool_defs()
        msgs = [{"role": "system", "content": system_content},
                {"role": "user", "content": user_input.text}]

        _LOGGER.debug("Hestia in=%r exposure=%d entities", user_input.text, len(exposure))

        # 2. Loop ≤ depth
        answer: str | None = None
        for i in range(self._depth):
            text = await self._complete(msgs, tools)
            _LOGGER.debug("Hestia iter %d model=%r", i, text)
            if _looks_like_tool(text):
                parsed = parse(text)
                if not parsed.ok:
                    result = '{"ok":false,"error":"unparseable"}'
                else:
                    result = await execute_calls(self.hass, parsed, exposure,
                                                 user_input.context, self._deny)
                _LOGGER.debug("Hestia iter %d result=%s", i, result)
                msgs.append({"role": "assistant", "content": text})
                msgs.append({"role": "tool", "content": result})
                continue
            answer = text        # freier Text → fertig
            break

        # 3. Loop erschöpft → variabler Fehlertext (KEIN LLM)
        if answer is None:
            answer = random.choice(LOOP_EXHAUSTED_TEXTS)

        return self._result(user_input, chat_log, answer)

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

    def _result(self, user_input, chat_log, answer: str) -> conversation.ConversationResult:
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(answer)
        return conversation.ConversationResult(
            response=response,
            conversation_id=chat_log.conversation_id,
            continue_conversation=answer.rstrip().endswith("?"),   # „?" → Mikro offen
        )
