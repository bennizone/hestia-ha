"""Custom-Panel-Registrierung — „Hestia" in HAs Seitenleiste.

Das Frontend-Bundle (`panel/hestia-panel.js`) wird als Static-Path DIREKT aus der
Integration serviert (sauberer HACS-Weg — kein `www/`-Kopieren). Registriert ein
`custom`-Panel (kein iframe): das Custom-Element `<hestia-panel>` bekommt `hass` gesetzt
und redet über die WS-API (websocket.py) mit dem Config-Store.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "hestia"                       # /hestia in der URL + Sidebar-Slug
PANEL_ELEMENT = "hestia-panel"                  # Custom-Element-Tag im Bundle
_STATIC_PATH = "/hestia_static"                 # Static-Mount für das Bundle
# Cache-Bust: die manifest-Version (dynamisch, s. async_register_panel) — HA/Browser cachen Panel-Module
# aggressiv. Früher statische Konstante → Bundle-Änderungen erreichten den Browser NICHT (Bug 2026-07-13).
PANEL_JS_VERSION = "8"   # Fallback, falls die Integration-Version mal nicht lesbar ist


async def async_register_panel(hass: HomeAssistant) -> None:
    """Static-Path + Sidebar-Panel registrieren (idempotent über hass.data-Flag)."""
    bucket = hass.data.setdefault(DOMAIN, {})
    if bucket.get("_panel"):
        return

    js_file = Path(__file__).parent / "panel" / "hestia-panel.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_STATIC_PATH, str(js_file.parent), cache_headers=False)]
    )

    try:                                        # manifest-Version als Cache-Buster → bustet je Release
        hv = str((await async_get_integration(hass, DOMAIN)).version or PANEL_JS_VERSION)
    except Exception:  # noqa: BLE001
        hv = PANEL_JS_VERSION
    module_url = f"{_STATIC_PATH}/hestia-panel.js?hv={hv}"
    # Falls ein Alt-Panel hängt (Reload ohne sauberes Unload): erst weg, dann neu.
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="Hestia",
        sidebar_icon="mdi:home-assistant",
        frontend_url_path=PANEL_URL_PATH,
        require_admin=True,
        config={
            "_panel_custom": {
                "name": PANEL_ELEMENT,
                "embed_iframe": False,
                "trust_external": False,
                "module_url": module_url,
            }
        },
    )
    bucket["_panel"] = True
    _LOGGER.debug("Hestia-Panel registriert (%s)", module_url)


def async_remove_panel(hass: HomeAssistant) -> None:
    """Sidebar-Panel wieder entfernen (Static-Path bleibt — HA kann ihn nicht abmelden)."""
    bucket = hass.data.setdefault(DOMAIN, {})
    if not bucket.get("_panel"):
        return
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    bucket["_panel"] = False
