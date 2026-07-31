"""Thin HTTP client for a Pool Guardian controller on the local network.

Every endpoint used here is an unauthenticated GET. That is deliberate on the
firmware side: since 1.0.320 all *mutating* /api routes require the LAN control
secret, while the read-only ones stayed open so the app's local mode and the
device's own browser UI keep working without holding a credential.

This integration is feedback only. It never calls a mutating route, so it never
needs that secret — which is what makes setup a single "enter the IP" step.
Do not add a write path here without revisiting that decision.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import USER_AGENT


class PoolGuardianError(Exception):
    """Any failure talking to the controller."""


class PoolGuardianNotFound(PoolGuardianError):
    """Host answered, but it is not a Pool Guardian controller."""


class PoolGuardianClient:
    """Fetches the read-only JSON endpoints from one controller."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._session = session
        self._timeout = timeout

    @property
    def host(self) -> str:
        return self._host

    async def _get(self, path: str) -> dict[str, Any]:
        url = f"http://{self._host}{path}"
        try:
            # asyncio.timeout rather than the async_timeout package: it is
            # stdlib from 3.11, and Home Assistant is actively removing the
            # third-party dependency. Avoids declaring a requirement at all.
            async with asyncio.timeout(self._timeout):
                resp = await self._session.get(url, headers={"User-Agent": USER_AGENT})
                resp.raise_for_status()
                # The ESP32 sets Content-Type: application/json, but be lenient —
                # a proxy or a captive portal in the path may not.
                return await resp.json(content_type=None)
        except TimeoutError as err:
            raise PoolGuardianError(f"Timeout fetching {url}") from err
        except aiohttp.ClientError as err:
            raise PoolGuardianError(f"Error fetching {url}: {err}") from err
        except ValueError as err:
            raise PoolGuardianError(f"Malformed JSON from {url}: {err}") from err

    async def async_get_info(self) -> dict[str, Any]:
        """Identity and firmware version.

        Cheap (a 256-byte document) and the only endpoint that carries the
        CONTROLLER firmware version — /api/status reports the two RS232 sensor
        firmwares but not its own.
        """
        data = await self._get("/json")
        if data.get("device_type") != "pool_monitor":
            raise PoolGuardianNotFound(
                f"{self._host} responded to /json but is not a pool_monitor"
            )
        if not data.get("device_id"):
            raise PoolGuardianNotFound(f"{self._host} returned no device_id")
        return data

    async def async_get_status(self) -> dict[str, Any]:
        """Controller status: mode, uptime, rssi, ip, pairing/cloud state."""
        return await self._get("/api/status")

    async def async_get_live(self) -> dict[str, Any]:
        """Rich sensor snapshot: per-sensor blocks, freeze block, alert count."""
        return await self._get("/api/sensors/live")

    async def async_get_pump_history(self) -> dict[str, Any]:
        """Last 10 pump runs, newest first.

        Deliberately NOT on the fast poll loop: it serialises the whole ring
        buffer (~2 KB) on an ESP32 that is also running an RS232 sensor loop and
        a cloud WebSocket, and the contents only change when a run ENDS.
        See the coordinator for when it is actually fetched.

        `end_reason` requires controller firmware 1.0.332 or newer.
        """
        return await self._get("/api/pump-history")
