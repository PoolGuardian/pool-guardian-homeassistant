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
    INFO_REFRESH_EVERY_N_CYCLES,
)

_LOGGER = logging.getLogger(__name__)


def _last_run_from_live(live: dict[str, Any]) -> dict[str, Any]:
    """Build the last-run dict from the live payload.

    Deliberately emits the SAME key names the /api/pump-history entries used
    (duration_sec, end_reason, ...) so nothing downstream has to change — the
    sensor platform keeps reading exactly what it always read.

    Returns {} when the controller predates 1.0.394 or has no completed run
    yet, which the sensor platform already treats as "unknown".
    """
    if "last_run_duration_sec" not in live:
        return {}
    return {
        "duration_sec": live.get("last_run_duration_sec"),
        "end_reason": live.get("last_run_end_reason"),
        "completed": live.get("last_run_completed"),
        "end_time": live.get("last_run_end_time"),
        "is_auto": live.get("last_run_is_auto"),
        "freeze_protect": live.get("last_run_freeze"),
        # The last-run current entity reads this. peak/min/anomaly_flags are
        # not carried in the live payload -- nothing consumes them per-run and
        # they remain in /api/pump-history if ever needed.
        "avg_current": live.get("last_run_avg_current"),
    }


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

        # Last-run values now ride the /api/sensors/live payload the controller
        # already returns on every poll (firmware 1.0.394+), so there is no
        # second request and no edge to catch.
        self._last_run = _last_run_from_live(live)

        return {
            DATA_LIVE: live,
            DATA_STATUS: status,
            DATA_INFO: self._info,
            DATA_LAST_RUN: self._last_run,
        }

    @staticmethod
    def _unused_placeholder() -> None:  # pragma: no cover
        """Removed: _async_maybe_refresh_history().

        It fetched /api/pump-history to read runs[0] and discard the other
        nine — roughly 2 KB serialised on the controller for ~80 bytes of
        usable data — and it did so on the pump's true->false EDGE, putting
        the heaviest request of the cycle at the moment the ESP32 was
        busiest. Controller 1.0.394 puts those scalars in /api/sensors/live,
        so the extra request, the edge detection and the periodic safety-net
        refetch all became unnecessary.

        /api/pump-history still exists on the device and still returns all 10
        runs — this integration simply never needed the list.
        """
