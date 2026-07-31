"""The Pool Guardian integration.

Local polling, read only. See api.py for why no credential is required.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PoolGuardianClient, PoolGuardianError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import PoolGuardianCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pool Guardian from a config entry."""
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
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
