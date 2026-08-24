"""Sensors for Comelit: last doorbell ring."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ComelitDataUpdateCoordinator
from .events import SOURCE_NONE, signal_source
from .fcm_push import signal_doorbell


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit sensors."""
    coordinator: ComelitDataUpdateCoordinator = entry.runtime_data
    if coordinator.events_manager is None:
        return
    async_add_entities(
        [
            ComelitLastRingSensor(coordinator),
            ComelitRingCountSensor(coordinator),
            ComelitEventsSourceSensor(coordinator),
        ]
    )


class ComelitLastRingSensor(SensorEntity):
    """Timestamp of the most recent doorbell ring."""

    _attr_has_entity_name = True
    _attr_name = "Last ring"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.unique_id}_last_ring"
        self._attr_device_info = coordinator.device_info
        self._value: datetime | None = None
        self._attr_extra_state_attributes: dict[str, Any] = {}

    @property
    def native_value(self) -> datetime | None:
        """Return the timestamp of the last ring."""
        return self._value

    async def async_added_to_hass(self) -> None:
        """Subscribe to ring dispatches."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_doorbell(self._coordinator.entry.entry_id),
                self._handle_ring,
            )
        )

    @callback
    def _handle_ring(self, payload: dict[str, Any]) -> None:
        """Record the ring time and call metadata."""
        self._value = dt_util.utcnow()
        self._attr_extra_state_attributes = {
            k: v
            for k, v in payload.items()
            if k in ("call_id", "notification") and v is not None
        }
        self.async_write_ha_state()


class ComelitRingCountSensor(RestoreSensor):
    """Running count of doorbell rings (persisted across restarts)."""

    _attr_has_entity_name = True
    _attr_name = "Ring count"
    _attr_icon = "mdi:bell-ring-outline"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.unique_id}_ring_count"
        self._attr_device_info = coordinator.device_info
        self._count = 0

    @property
    def native_value(self) -> int:
        """Return the ring count."""
        return self._count

    async def async_added_to_hass(self) -> None:
        """Restore the previous count and subscribe to rings."""
        last = await self.async_get_last_sensor_data()
        if last is not None and last.native_value is not None:
            try:
                self._count = int(last.native_value)
            except (ValueError, TypeError):
                self._count = 0
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_doorbell(self._coordinator.entry.entry_id),
                self._handle_ring,
            )
        )

    @callback
    def _handle_ring(self, _payload: dict[str, Any]) -> None:
        """Increment on each ring."""
        self._count += 1
        self.async_write_ha_state()


class ComelitEventsSourceSensor(SensorEntity):
    """Active doorbell-events source: local, cloud, or none."""

    _attr_has_entity_name = True
    _attr_name = "Events source"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["local", "cloud", "none"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:transit-connection-variant"

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.unique_id}_events_source"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        mgr = self._coordinator.events_manager
        return mgr.source if mgr else SOURCE_NONE

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_source(self._coordinator.entry.entry_id),
                self._handle_source,
            )
        )

    @callback
    def _handle_source(self, _source: str) -> None:
        self.async_write_ha_state()
