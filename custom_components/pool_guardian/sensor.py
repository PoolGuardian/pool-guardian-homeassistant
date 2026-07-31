"""Sensor platform for Pool Guardian."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_INFO, DATA_LAST_RUN, DATA_LIVE, DATA_STATUS, DOMAIN
from .coordinator import PoolGuardianCoordinator
from .entity import PoolGuardianEntity


@dataclass(frozen=True, kw_only=True)
class PoolGuardianSensorDescription(SensorEntityDescription):
    """Sensor description with an extractor over the merged payload."""

    value_fn: Callable[[dict[str, Any]], Any]


def _live(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(DATA_LIVE) or {}


def _status(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(DATA_STATUS) or {}


def _sensor_block(data: dict[str, Any], which: str) -> dict[str, Any]:
    return _live(data).get(which) or {}


def _sensor_temp(data: dict[str, Any], which: str) -> float | None:
    """Water temperature, but only while the sensor is actually reporting.

    An offline sensor keeps the last packet's values, so publishing temp_c
    unconditionally would show a stale number indefinitely with no hint that it
    had stopped updating. The firmware itself omits temp_c when offline; this
    guards the case where it is present but stale.
    """
    block = _sensor_block(data, which)
    if not block.get("online"):
        return None
    return block.get("temp_c")


def _current(data: dict[str, Any], key: str) -> float | None:
    """Pump current, suppressed when the current sensor is not healthy.

    Returning 0.0 for a failed sensor would be indistinguishable from a real
    reading of "pump drawing nothing", which is itself a fault condition.
    """
    live = _live(data)
    if not live.get("current_sensor_ok"):
        return None
    return live.get(key)


def _last_run(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(DATA_LAST_RUN) or {}


def _last_run_value(data: dict[str, Any], key: str) -> Any:
    """A field of the most recent completed run.

    An empty dict means the ring buffer is empty — no pump run has completed
    since the controller booted — which is genuinely unknown, not zero.
    """
    run = _last_run(data)
    if not run:
        return None
    return run.get(key)


def _last_run_finished(data: dict[str, Any]) -> datetime | None:
    """When the last run ended, as an aware datetime.

    end_time is a Unix timestamp from the controller's clock, which is 0 until
    NTP has synced. A run recorded before sync would otherwise be reported as
    1970 and sit at the far end of every history graph.
    """
    end_time = _last_run_value(data, "end_time")
    if not end_time or end_time <= 0:
        return None
    return datetime.fromtimestamp(end_time, tz=UTC)


SENSORS: tuple[PoolGuardianSensorDescription, ...] = (
    PoolGuardianSensorDescription(
        key="state",
        translation_key="state",
        value_fn=lambda d: _live(d).get("state"),
    ),
    PoolGuardianSensorDescription(
        key="mode",
        translation_key="mode",
        value_fn=lambda d: (
            None
            if _status(d).get("is_manual") is None
            else ("manual" if _status(d)["is_manual"] else "auto")
        ),
    ),
    PoolGuardianSensorDescription(
        key="active_alerts",
        translation_key="active_alerts",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _live(d).get("active_alerts"),
    ),
    # ── Pump current ────────────────────────────────────────────────────────
    PoolGuardianSensorDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: _current(d, "current_amps"),
    ),
    PoolGuardianSensorDescription(
        key="current_avg",
        translation_key="current_avg",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: _current(d, "current_avg"),
    ),
    PoolGuardianSensorDescription(
        key="current_min",
        translation_key="current_min",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda d: _current(d, "current_min"),
    ),
    PoolGuardianSensorDescription(
        key="current_max",
        translation_key="current_max",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda d: _current(d, "current_max"),
    ),
    # ── Water sensors ───────────────────────────────────────────────────────
    PoolGuardianSensorDescription(
        key="sensor_low_temp",
        translation_key="sensor_low_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: _sensor_temp(d, "sensor_low"),
    ),
    PoolGuardianSensorDescription(
        key="sensor_high_temp",
        translation_key="sensor_high_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: _sensor_temp(d, "sensor_high"),
    ),
    PoolGuardianSensorDescription(
        key="sensor_low_firmware",
        translation_key="sensor_low_firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _sensor_block(d, "sensor_low").get("firmware"),
    ),
    PoolGuardianSensorDescription(
        key="sensor_high_firmware",
        translation_key="sensor_high_firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _sensor_block(d, "sensor_high").get("firmware"),
    ),
    # ── Freeze protection thresholds ────────────────────────────────────────
    # User-settable, so they ride along: a cold-weather history is hard to read
    # without knowing which thresholds were in force at the time.
    PoolGuardianSensorDescription(
        key="freeze_threshold_c",
        translation_key="freeze_threshold_c",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda d: (_live(d).get("freeze") or {}).get("threshold_c"),
    ),
    PoolGuardianSensorDescription(
        key="freeze_clear_c",
        translation_key="freeze_clear_c",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda d: (_live(d).get("freeze") or {}).get("clear_c"),
    ),
    PoolGuardianSensorDescription(
        key="freeze_cutoff_c",
        translation_key="freeze_cutoff_c",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda d: (_live(d).get("freeze") or {}).get("cutoff_c"),
    ),
    PoolGuardianSensorDescription(
        key="freeze_resume_c",
        translation_key="freeze_resume_c",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda d: (_live(d).get("freeze") or {}).get("resume_c"),
    ),
    # ── Last completed pump run ─────────────────────────────────────────────
    PoolGuardianSensorDescription(
        key="last_run_duration",
        translation_key="last_run_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda d: _last_run_value(d, "duration_sec"),
    ),
    PoolGuardianSensorDescription(
        key="last_run_end_reason",
        translation_key="last_run_end_reason",
        # Requires controller firmware 1.0.332+. Older firmware omits the field
        # from /api/pump-history and this reads unknown rather than erroring.
        value_fn=lambda d: _last_run_value(d, "end_reason"),
    ),
    PoolGuardianSensorDescription(
        key="last_run_avg_current",
        translation_key="last_run_avg_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=2,
        value_fn=lambda d: _last_run_value(d, "avg_current"),
    ),
    PoolGuardianSensorDescription(
        key="last_run_mode",
        translation_key="last_run_mode",
        value_fn=lambda d: (
            None
            if _last_run_value(d, "is_auto") is None
            else ("auto" if _last_run_value(d, "is_auto") else "manual")
        ),
    ),
    PoolGuardianSensorDescription(
        key="last_run_finished",
        translation_key="last_run_finished",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_run_finished,
    ),
    # ── Controller diagnostics ──────────────────────────────────────────────
    PoolGuardianSensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _status(d).get("rssi"),
    ),
    PoolGuardianSensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _status(d).get("uptime"),
    ),
    PoolGuardianSensorDescription(
        key="diagnostic_flags",
        translation_key="diagnostic_flags",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _live(d).get("diagnostic_flags"),
    ),
    PoolGuardianSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _status(d).get("ip"),
    ),
    PoolGuardianSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: (d.get(DATA_INFO) or {}).get("firmware_version"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pool Guardian sensors."""
    coordinator: PoolGuardianCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PoolGuardianSensor(coordinator, description) for description in SENSORS
    )


class PoolGuardianSensor(PoolGuardianEntity, SensorEntity):
    """A single value read from the controller."""

    entity_description: PoolGuardianSensorDescription

    def __init__(
        self,
        coordinator: PoolGuardianCoordinator,
        description: PoolGuardianSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
