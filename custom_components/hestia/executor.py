"""Executor (STUB) — Wire→Entität→hass.services + rev2-Result.

Der native Kern des Loops: geparste cap-v2-Calls (hestia_cap.Call) gegen HAs Registry auflösen,
den echten HA-Service rufen, und ein rev2-Result-JSON bauen (RESULT_SCHEMA.md).

TODO (Coding-Runde):
  resolve(call, exposure) -> entity_ids       # name/aliases → entity_id; area/domain → Filter; rapidfuzz (F1)
  turn_on/off/stop → light.turn_on etc.        # hass.services.async_call(domain, service, {entity_id})
  get_state         → hass.states → readings   # schlank {name,attribute,value,unit}
  set_state/adjust  → Service + Wert echoen
  Safety-Deny (lock/alarm) → {"ok":false,"error":"unsafe"}
  entity_not_found/ambiguous → {"ok":false,"error":..., "did_you_mean"/"candidates"/"areas": [...]}
Rückgabe: rev2-JSON-String (kompakt, separators (",",":")) für den tool-Turn.
"""
from __future__ import annotations


async def execute_calls(hass, calls, exposure) -> str:
    raise NotImplementedError("Executor: Coding-Runde (RESULT_SCHEMA.md rev2)")
