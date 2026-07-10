"""Hestia — Blackbox-Conversation-Agent für HA (cap-v2 Loop) + Config-Panel.

Setup-Gerüst. Die Logik lebt in conversation.py (ConversationEntity + Loop) und
executor.py (Wire→Entität→hass.services). Contract-Anker: vendored hestia_cap.

Dazu (v23.1 UI-Block): Config-Store (store.py, in HAs `.storage`), WS-API (websocket.py)
und das Sidebar-Panel (panel.py). Store/WS/Panel sind HA-weit (single instance), nicht
per Config-Entry — darum idempotent hinter hass.data-Flags.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import DOMAIN
from .panel import async_register_panel, async_remove_panel
from .store import ExposureStore
from .websocket import async_register as async_register_ws

PLATFORMS = [Platform.CONVERSATION]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    bucket = hass.data.setdefault(DOMAIN, {})
    bucket[entry.entry_id] = dict(entry.data)

    # Config-Store (single instance) — vor WS/Panel laden, damit ws_* sofort lesen können.
    if "_store" not in bucket:
        store = ExposureStore(hass)
        await store.async_load()
        bucket["_store"] = store

    async_register_ws(hass)
    await async_register_panel(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        bucket = hass.data[DOMAIN]
        bucket.pop(entry.entry_id, None)
        # Kein Config-Entry mehr → HA-weite Ressourcen abräumen (Panel weg, Store frei).
        if not any(k for k in bucket if not k.startswith("_")):
            async_remove_panel(hass)
            bucket.pop("_store", None)
    return ok
