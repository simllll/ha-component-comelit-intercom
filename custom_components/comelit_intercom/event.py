"""Event platform for Comelit doorbell rings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EVENT_TYPE_RING
from .coordinator import ComelitDataUpdateCoordinator
from .fcm_push import signal_doorbell


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the doorbell event entity."""
    coordinator: ComelitDataUpdateCoordinator = entry.runtime_data
    # Only expose the entity if push notifications are enabled for this entry.
    if getattr(coordinator, "push_manager", None) is None:
        return
    async_add_entities([ComelitDoorbellEvent(coordinator)])


class ComelitDoorbellEvent(EventEntity):
    """A doorbell that fires a 'ring' event on an incoming call."""

    _attr_has_entity_name = True
    _attr_name = "Doorbell"
    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = [EVENT_TYPE_RING]
    _attr_icon = "mdi:doorbell-video"

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.unique_id}_doorbell"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.unique_id)},
            name=f"Comelit Intercom ({coordinator.host})",
            manufacturer="Comelit",
            model="ICONA Bridge",
        )

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
        """Trigger the doorbell event."""
        attrs = {
            k: v
            for k, v in payload.items()
            if k in ("call_id", "notification") and v is not None
        }
        self._trigger_event(EVENT_TYPE_RING, attrs)
        self.async_write_ha_state()
