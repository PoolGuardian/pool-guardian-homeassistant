"""Config and options flow for Pool Guardian."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from .api import PoolGuardianClient, PoolGuardianError, PoolGuardianNotFound
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class PoolGuardianConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pool Guardian."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._info: dict[str, Any] | None = None

    async def _async_probe(self, host: str) -> dict[str, Any]:
        """Confirm the host is a Pool Guardian and return its identity."""
        session = async_get_clientsession(self.hass)
        client = PoolGuardianClient(host, session)
        return await client.async_get_info()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manual setup: the user types an IP or hostname.

        Always available. Still the required path for a controller on firmware
        older than 1.0.332 that has been renamed: those advertise no TXT record,
        so only the mDNS-name matcher can find them and a rename defeats it.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                info = await self._async_probe(host)
            except PoolGuardianNotFound:
                errors["base"] = "not_pool_guardian"
            except PoolGuardianError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info["device_id"])
                # Re-point an existing entry if the device moved to a new IP
                # rather than refusing the flow with "already configured".
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=info.get("device_name") or "Pool Guardian",
                    data={CONF_HOST: host},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> FlowResult:
        """Handle a controller found via mDNS.

        Two matchers in manifest.json feed this: a device_type=pool_monitor TXT
        property (firmware 1.0.332+, name-independent) and a poolguardian* name
        prefix for older firmware. Both sit on _http._tcp, which anything can
        answer on, so probe /json and check device_type before showing the user
        anything.
        """
        host = discovery_info.host

        try:
            info = await self._async_probe(host)
        except PoolGuardianNotFound:
            return self.async_abort(reason="not_pool_guardian")
        except PoolGuardianError:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(info["device_id"])
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._host = host
        self._info = info

        # Shows the device name rather than a bare IP on the discovery card.
        self.context["title_placeholders"] = {
            "name": info.get("device_name") or "Pool Guardian"
        }
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask the user to confirm adding a discovered controller."""
        assert self._host is not None and self._info is not None

        if user_input is not None:
            return self.async_create_entry(
                title=self._info.get("device_name") or "Pool Guardian",
                data={CONF_HOST: self._host},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                "name": self._info.get("device_name") or "Pool Guardian",
                "host": self._host,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PoolGuardianOptionsFlow()


class PoolGuardianOptionsFlow(OptionsFlow):
    """Lets the user trade polling load against latency."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    )
                }
            ),
        )
