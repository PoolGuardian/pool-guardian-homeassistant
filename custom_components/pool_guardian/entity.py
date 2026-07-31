"""Shared base entity for Pool Guardian."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import PoolGuardianCoordinator


class PoolGuardianEntity(CoordinatorEntity[PoolGuardianCoordinator]):
    """Base class binding every entity to the one controller device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PoolGuardianCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        # device_id is the MAC, which is this system's primary key everywhere
        # (see MAC_ADDRESS_MIGRATION.md), so it doubles as the HA identifier and
        # as the network connection — letting HA merge this device with anything
        # else that discovers the same MAC.
        mac = self.coordinator.device_id
        return DeviceInfo(
            identifiers={(DOMAIN, mac)},
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
            name=self.coordinator.device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=self.coordinator.firmware_version,
            serial_number=self.coordinator.serial_number,
            configuration_url=f"http://{self.coordinator.client.host}",
        )
