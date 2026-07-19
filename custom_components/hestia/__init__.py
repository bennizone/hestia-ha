"""Hestia — Blackbox-Conversation-Agent für HA (cap-v2 Loop) + Config-Panel.

Setup-Gerüst. Die Logik lebt in conversation.py (ConversationEntity + Loop) und
executor.py (Wire→Entität→hass.services). Contract-Anker: vendored hestia_cap.

Dazu (v23.1 UI-Block): Config-Store (store.py, in HAs `.storage`), WS-API (websocket.py)
und das Sidebar-Panel (panel.py). Store/WS/Panel sind HA-weit (single instance), nicht
per Config-Entry — darum idempotent hinter hass.data-Flags.
"""
from __future__ import annotations

import logging
from functools import partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, Event
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .panel import async_register_panel, async_remove_panel
from .reqlog import RequestLog
from .sentences import SentenceStore
from .store import ExposureStore
from .websocket import async_register as async_register_ws

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CONVERSATION]


async def _async_handle_entity_registry_updated(hass: HomeAssistant, event: Event) -> None:
    """Bei entity_id-Rename die per-entity_id gekeyten Hestia-Daten mitziehen.

    HA-Contract (2026.7): `action=="update"` mit `old_entity_id` im Event-Data feuert GENAU dann,
    wenn sich die entity_id geändert hat (`entity_id` = neuer Wert). Ohne diese Migration verwaisen
    der Exposure-Record (Key = entity_id) und die `target_entity` der Custom-Sätze still — die
    Entität fällt aus Modell+Panel und alle kuratierten Metadaten gehen verloren. Owned-Helper +
    Config-Settings sind bereits rename-fest (über config_entry_id gejoint)."""
    data = event.data
    if data.get("action") != "update" or "old_entity_id" not in data:
        return
    old = data["old_entity_id"]
    new = data["entity_id"]
    if not old or not new or old == new:
        return
    bucket = hass.data.get(DOMAIN, {})
    store: ExposureStore | None = bucket.get("_store")
    sent: SentenceStore | None = bucket.get("_sentences")
    moved = await store.async_rename(old, new) if store is not None else False
    n = await sent.async_rename_target(old, new) if sent is not None else 0
    if moved or n:
        _LOGGER.info("Hestia: Entity-Rename %s → %s migriert (exposure=%s, sentences=%d)",
                     old, new, moved, n)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    bucket = hass.data.setdefault(DOMAIN, {})
    bucket[entry.entry_id] = dict(entry.data)

    # Config-Store (single instance) — vor WS/Panel laden, damit ws_* sofort lesen können.
    if "_store" not in bucket:
        store = ExposureStore(hass)
        await store.async_load()
        bucket["_store"] = store

    # Custom-Sätze-Store (single instance) — roher Router vor dem LLM (sentences.py).
    if "_sentences" not in bucket:
        sent = SentenceStore(hass)
        await sent.async_load()
        bucket["_sentences"] = sent

    # Request-Log (single instance) — rotierender Ring der letzten Conversation-Turns (Observability).
    if "_reqlog" not in bucket:
        reqlog = RequestLog(hass)
        await reqlog.async_load()
        bucket["_reqlog"] = reqlog

    # Entity-Rename-Listener (single instance) — hält Exposure-Store + Custom-Satz-Ziele
    # rename-fest, indem er die per-entity_id gekeyten Daten bei Umbenennung mitzieht.
    if "_er_unsub" not in bucket:
        bucket["_er_unsub"] = hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            partial(_async_handle_entity_registry_updated, hass),
        )

    # v23.7 Zeitsteuerung: Schedule-Cleanup (single instance) — deaktivierte/verwaiste eigene one-shot-
    # Automationen weg. Startup ERST nach HA-Start (sonst sind Automation-States noch nicht da → eigene
    # Schedules sähen fälschlich verwaist aus) + täglich.
    if "_sched_cleanup" not in bucket:
        from . import schedule
        from homeassistant.core import CoreState
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
        from homeassistant.helpers.event import async_track_time_change

        async def _sched_cleanup(now=None):
            try:
                n = await schedule.cleanup(hass)
                if n:
                    _LOGGER.info("Hestia: %d abgelaufene Schedule(s) aufgeräumt", n)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Hestia schedule-cleanup: %s", e)

        bucket["_sched_cleanup"] = async_track_time_change(hass, _sched_cleanup, hour=3, minute=17, second=0)

        async def _sched_cleanup_started(_event=None):
            # Coroutine-Callback → HA awaited sie IM Event-Loop. Ein sync-Lambda hier würde als
            # nicht-@callback-Job im Executor-Thread laufen → hass.async_create_task aus Fremd-Thread
            # = RuntimeError (Thread-Safety-Checker, HA ≥2024.5). Direktes await vermeidet das ganz.
            await _sched_cleanup()

        if hass.state == CoreState.running:
            hass.async_create_task(_sched_cleanup())          # in async_setup_entry → im Loop, thread-safe
        else:
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _sched_cleanup_started)

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
            unsub = bucket.pop("_er_unsub", None)
            if unsub is not None:
                unsub()
            bucket.pop("_store", None)
            bucket.pop("_sentences", None)
            bucket.pop("_reqlog", None)
    return ok
