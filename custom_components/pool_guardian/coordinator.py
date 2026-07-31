"""Polling coordinator for a Pool Guardian controller."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PoolGuardianClient, PoolGuardianError
from .const import (
    DATA_INFO,
    DATA_LAST_RUN,
    DATA_LIVE,
    DATA_STATUS,
    DOMAIN,
    HISTORY_REFRESH_EVERY_N_CYCLES,
    INFO_REFRESH_EVERY_N_CYCLES,
)

_LOGGER = logging.getLogger(__name__)


class PoolGuardianCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches the controller's read-only endpoints on a fixed interval.

    Two endpoints are polled every cycle because neither is a superset of the
    other: /api/sensors/live carries the per-sensor and freeze blocks, while
    /api/status carries mode, uptime, rssi and the pairing/cloud state.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: PoolGuardianClient,
        scan_interval: int,
        info: dict[str, Any],
    ) -> None:
        self.client = client
        self.entry = entry
        self._info = info
        self._cycles = 0
        self._last_run: dict[str, Any] | None = None
        # None, not False: "we have never seen the pump" is distinct from "the
        # pump was off last cycle". Seeding it False would make a controller
        # that is already pumping at HA startup look like a falling edge later.
        self._prev_pump_active: bool | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(seconds=scan_interval),
        )

    @property
    def device_id(self) -> str:
        """MAC address. The controller's primary key everywhere in this system."""
        return str(self._info.get("device_id", ""))

    @property
    def device_name(self) -> str:
        return str(self._info.get("device_name") or "Pool Guardian")

    @property
    def firmware_version(self) -> str | None:
        return self._info.get("firmware_version")

    @property
    def serial_number(self) -> str | None:
        serial = self._info.get("serial_number")
        # Firmware reports 0 for "not assigned at the factory yet"; showing a
        # literal 0 in the HA device page reads like a real serial number.
        if not serial:
            return None
        return str(serial)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            live = await self.client.async_get_live()
            status = await self.client.async_get_status()
        except PoolGuardianError as err:
            raise UpdateFailed(str(err)) from err

        self._cycles += 1

        # Slow lane: pick up a firmware version change after an OTA. A failure
        # here must not fail the whole update — the device is plainly reachable,
        # we just keep the previous identity until the next attempt.
        if self._cycles % INFO_REFRESH_EVERY_N_CYCLES == 0:
            try:
                self._info = await self.client.async_get_info()
            except PoolGuardianError as err:
                _LOGGER.debug("Info refresh failed, keeping previous: %s", err)

        await self._async_maybe_refresh_history(live)

        return {
            DATA_LIVE: live,
            DATA_STATUS: status,
            DATA_INFO: self._info,
            DATA_LAST_RUN: self._last_run,
        }

    async def _async_maybe_refresh_history(self, live: dict[str, Any]) -> None:
        """Fetch pump history only when it can have changed.

        The ring buffer gains an entry when a run ENDS, so the pump's
        true -> false transition is the exact moment worth re-reading it.
        Polling it every cycle would re-serialise ~2 KB on the controller for
        an answer that is usually identical.
        """
        pump_active = live.get("pump_active")
        prev = self._prev_pump_active
        if pump_active is not None:
            self._prev_pump_active = bool(pump_active)

        run_just_ended = prev is True and pump_active is False
        first_fetch = self._last_run is None
        periodic = self._cycles % HISTORY_REFRESH_EVERY_N_CYCLES == 0

        if not (run_just_ended or first_fetch or periodic):
            return

        try:
            history = await self.client.async_get_pump_history()
        except PoolGuardianError as err:
            # Non-fatal by design: the live data is already in hand and the
            # last-run entities can keep their previous values.
            _LOGGER.debug("Pump history refresh failed, keeping previous: %s", err)
            return

        runs = history.get("history") or []
        # Firmware serialises the ring buffer newest-first.
        self._last_run = runs[0] if runs else {}
