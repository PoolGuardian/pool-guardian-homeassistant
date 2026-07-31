"""Binary sensor platform for Pool Guardian.

Note what is NOT here: there is no switch platform and no service that can
start the pump. This integration is feedback only, matching the MQTT decision
in the firmware — control stays on the authenticated paths (the mobile app and
the LAN API, both of which require a credential this integration never holds).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_LIVE, DATA_STATUS, DOMAIN
from .coordinator import PoolGuardianCoordinator
from .entity import PoolGuardianEntity


@dataclass(frozen=True, kw_only=True)
class PoolGuardianBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description with an extractor over the merged payload."""

    value_fn: Callable[[dict[str, Any]], bool | None]


def _live(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(DATA_LIVE) or {}


def _status(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(DATA_STATUS) or {}


def _freeze(data: dict[str, Any]) -> dict[str, Any]:
    return _live(data).get("freeze") or {}


def _cloud_connected(data: dict[str, Any]) -> bool | None:
    """Whether the controller currently has a working cloud session.

    Unpaired is not the same as disconnected, and neither is
    cloud_access_denied (a lapsed subscription — the device still works
    locally). Report a plain false for both rather than inventing a third
    state; the distinction belongs in the app, not on a HA connectivity dot.
    """
    status = _status(data)
    if "paired" not in status:
        return None
    if not status.get("paired"):
        return False
    return not status.get("cloud_access_denied", False)


BINARY_SENSORS: tuple[PoolGuardianBinarySensorDescription, ...] = (
    PoolGuardianBinarySensorDescription(
        key="pump",
        translation_key="pump",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d: _live(d).get("pump_active"),
    ),
    # ── Water detection, grouped under the sensor that produced it ──────────
    # Taken from the controller's debounced view (top-level high_sensor /
    # low_sensor), not the sensor block's raw `water`, because the debounced
    # value is what actually drives the pump.
    PoolGuardianBinarySensorDescription(
        key="sensor_low_water",
        translation_key="sensor_low_water",
        device_class=BinarySensorDeviceClass.MOISTURE,
        value_fn=lambda d: _live(d).get("low_sensor"),
    ),
    PoolGuardianBinarySensorDescription(
        key="sensor_high_water",
        translation_key="sensor_high_water",
        device_class=BinarySensorDeviceClass.MOISTURE,
        value_fn=lambda d: _live(d).get("high_sensor"),
    ),
    PoolGuardianBinarySensorDescription(
        key="sensor_low_online",
        translation_key="sensor_low_online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (_live(d).get("sensor_low") or {}).get("online"),
    ),
    PoolGuardianBinarySensorDescription(
        key="sensor_high_online",
        translation_key="sensor_high_online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (_live(d).get("sensor_high") or {}).get("online"),
    ),
    # ── Freeze protection ───────────────────────────────────────────────────
    PoolGuardianBinarySensorDescription(
        key="freeze_enabled",
        translation_key="freeze_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _freeze(d).get("enabled"),
    ),
    PoolGuardianBinarySensorDescription(
        key="freeze_protect_active",
        translation_key="freeze_protect_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d: _freeze(d).get("protect_active"),
    ),
    PoolGuardianBinarySensorDescription(
        key="freeze_conditions_met",
        translation_key="freeze_conditions_met",
        device_class=BinarySensorDeviceClass.COLD,
        value_fn=lambda d: _freeze(d).get("conditions_met"),
    ),
    PoolGuardianBinarySensorDescription(
        key="freeze_lockout_active",
        translation_key="freeze_lockout_active",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d: _freeze(d).get("lockout_active"),
    ),
    # ── Controller diagnostics ──────────────────────────────────────────────
    PoolGuardianBinarySensorDescription(
        key="cloud_connected",
        translation_key="cloud_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_cloud_connected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pool Guardian binary sensors."""
    coordinator: PoolGuardianCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PoolGuardianBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class PoolGuardianBinarySensor(PoolGuardianEntity, BinarySensorEntity):
    """A single boolean read from the controller."""

    entity_description: PoolGuardianBinarySensorDescription

    def __init__(
        self,
        coordinator: PoolGuardianCoordinator,
        description: PoolGuardianBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
