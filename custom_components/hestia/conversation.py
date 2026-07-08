"""Hestia ConversationEntity — der cap-v2 Blackbox-Loop (GRUNDGERÜST/STUB).

Architektur (HA_INTEGRATION_DRAFT.md):
  Text rein → System-Prompt aus HA-Registry (hestia_cap.render) → /completion →
    Tool-Block? → hestia_cap.parse → Executor (Wire→Entität→hass.services) → rev2-Result → nächste Iter (≤N)
    freier Text? → fertig, an Assist zurück (Mikro offen bei „?")
  Loop erschöpft → Addon-Fehlermeldung (KEIN LLM).

train==serve: Prompt LOKAL rendern (offizielles LFM2.5-Template + INNERE Tools) + POST /completion.
NIEMALS /v1/chat/completions (llama.cpp #23838 — s. SERVE_PIPELINE.md).

STATUS: Skelett. Die mit TODO markierten Stellen sind die Coding-Runde.
"""
from __future__ import annotations

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_LLAMA_URL, CONF_LOOP_DEPTH, DEFAULT_LOOP_DEPTH
# from .hestia_cap import House, parse, render_system_content, all_tool_defs
# from .executor import execute_calls   # TODO: Wire→Entität→hass.services + rev2-Result


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

    @property
    def supported_languages(self) -> list[str] | str:
        return ["de"]

    async def _async_handle_message(
        self, user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        # ── GRUNDGERÜST — TODO Coding-Runde ──────────────────────────────────
        # 1. House aus HA-Registry bauen (area_registry + entity_registry + Exposure-Set)
        #    → hestia_cap.House; System-Prompt = render_system_content(house) + "Aktueller Raum:" (device→area)
        # 2. Loop (≤ self._depth):
        #    prompt = apply_chat_template(msgs, tools=all_tool_defs()) lokal   (train==serve)
        #    text = POST self._url + "/completion" {prompt, stop:["<|im_end|>"], temperature:0}
        #    calls = hestia_cap.parse(text)
        #      calls.ok → result = await execute_calls(hass, calls, exposure)  # rev2-JSON
        #                 msgs += [asst(text), tool(result)] ; weiter
        #      sonst (freier Text) → return das als Antwort (Mikro offen bei "?")
        # 3. erschöpft → LOOP_EXHAUSTED_TEXTS
        raise NotImplementedError("Hestia-Loop: Coding-Runde (siehe hestia/v23/HA_INTEGRATION_DRAFT.md)")
