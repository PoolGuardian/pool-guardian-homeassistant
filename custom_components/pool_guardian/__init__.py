"""The Pool Guardian integration.

Local polling, read only. See api.py for why no credential is required.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PoolGuardianClient, PoolGuardianError
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    INTEGRATION_VERSION,
)
from .coordinator import PoolGuardianCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

# The bundled Lovelace card. Served from the integration rather than asked of
# the user, because the alternative is a README step that says "copy this file
# into /config/www and then add a resource" -- which is where most people stop.
CARD_URL = f"/{DOMAIN}/pool-guardian-card.js"
CARD_FILE = "pool-guardian-card.js"
CARD_REGISTERED = "card_registered"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the card and add it to the frontend, once per HA run.

    Guarded on a flag rather than on the number of config entries: someone with
    a pool and a spa has two entries, and registering the same static path
    twice raises.

    The URL carries the integration version as a cache-buster. Without it a
    browser holds the previous card indefinitely after an update and the user
    reports a bug that was fixed a release ago.
    """
    store = hass.data.setdefault(DOMAIN, {})
    if store.get(CARD_REGISTERED):
        return

    path = Path(__file__).parent / "www" / CARD_FILE
    if not path.is_file():
        # Not fatal. The integration's entities are the product; the card is a
        # convenience, and a missing file should not take the whole thing down.
        _LOGGER.warning("Pool Guardian card not found at %s; skipping", path)
        return

    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={INTEGRATION_VERSION}")
    store[CARD_REGISTERED] = True
    _LOGGER.debug("Registered Pool Guardian card at %s", CARD_URL)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pool Guardian from a config entry."""
    await _async_register_card(hass)

    host = entry.data[CONF_HOST]
    session = async_get_clientsession(hass)
    client = PoolGuardianClient(host, session)

    try:
        info = await client.async_get_info()
    except PoolGuardianError as err:
        # Retryable: the controller reboots on OTA and on a config save, so a
        # failure at startup is far more often "not up yet" than "gone".
        raise ConfigEntryNotReady(
            f"Cannot reach Pool Guardian at {host}: {err}"
        ) from err

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = PoolGuardianCoordinator(hass, entry, client, scan_interval, info)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when the poll interval changes — the interval is fixed at
    coordinator construction, so there is nothing to mutate in place."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Only the entry's own key. CARD_REGISTERED shares this dict and must
        # outlive the entry: the static path stays registered for the life of
        # the HA process, so re-registering it on reload raises.
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
