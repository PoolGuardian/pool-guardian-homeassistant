"""Constants for the Pool Guardian integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "pool_guardian"

MANUFACTURER = "Pool Guardian"
MODEL = "Pool Monitor"

# Sent as User-Agent on every request so the controller can tell which
# integrations are talking to it. This is the whole telemetry story: the
# signal rides a request the integration was making anyway, nothing is sent
# anywhere new, and a controller that was never paired to the cloud still
# reports nothing — which is the point of choosing local-only.
#
# Keep in lockstep with "version" in manifest.json. Nothing enforces it.
INTEGRATION_VERSION = "1.1.1"
USER_AGENT = f"PoolGuardian-HomeAssistant/{INTEGRATION_VERSION}"

CONF_SCAN_INTERVAL = "scan_interval"

# 10 s is a deliberate compromise. The device's own browser UI polls every 2 s,
# but that is one page on a LAN; Home Assistant polls forever. Pool state is
# slow — a drain takes minutes — so 10 s costs nothing in usefulness and keeps
# the load off an ESP32 that is also holding a cloud WebSocket and an RS232
# sensor loop.
DEFAULT_SCAN_INTERVAL = 10
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300

# /json only changes across an OTA, so it does not belong on the fast loop.
# Refreshed every Nth coordinator cycle to pick up a firmware version bump
# without making the user reload the integration.
INFO_REFRESH_EVERY_N_CYCLES = 60

# Pump history is fetched on the pump's falling edge (a run just ended), which
# is the only moment its contents change. This periodic refresh is the safety
# net for the case that edge is missed — a run shorter than one poll interval,
# such as a bench pump-test, can start and finish between two polls.
HISTORY_REFRESH_EVERY_N_CYCLES = 30

DEFAULT_TIMEOUT = 10.0

UPDATE_LISTENER_UNSUB = "update_listener_unsub"

# Keys into the coordinator's merged payload.
DATA_INFO = "info"
DATA_STATUS = "status"
DATA_LIVE = "live"
DATA_LAST_RUN = "last_run"

SCAN_INTERVAL_FALLBACK = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
