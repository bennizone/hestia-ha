"""Config-Flow (STUB) — minimal: llama.cpp-URL + Loop-Tiefe.

TODO (Coding-Runde): Exposure-Set-Editor (llm_name/aliases/description je Entität),
Deny-Liste, Optionen-Flow. Fürs Grundgerüst reicht die URL, damit die Entität lädt.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_LLAMA_URL, CONF_LOOP_DEPTH, DEFAULT_LOOP_DEPTH


class HestiaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Hestia", data=user_input)
        schema = vol.Schema({
            vol.Required(CONF_LLAMA_URL, default="http://10.83.1.111:8099"): str,
            vol.Optional(CONF_LOOP_DEPTH, default=DEFAULT_LOOP_DEPTH): int,
        })
        return self.async_show_form(step_id="user", data_schema=schema)
