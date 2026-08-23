"""Binary sensors for Comelit: connectivity and push status."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ComelitDataUpdateCoordinator
from .fcm_push import signal_doorbell

# How long the "ringing" sensor stays on after a ring (no reliable call-end
# is delivered on this firmware, so we auto-clear).
RING_ACTIVE_SECONDS = 30


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit binary sensors."""
    coordinator: ComelitDataUpdateCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [ComelitConnectivitySensor(coordinator)]
    if coordinator.push_manager is not None:
        entities.append(ComelitPushStatusSensor(coordinator))
        entities.append(ComelitRingingSensor(coordinator))
    async_add_entities(entities)


class ComelitConnectivitySensor(
    CoordinatorEntity[ComelitDataUpdateCoordinator], BinarySensorEntity
):
    """Reports whether the ICONA bridge is reachable and authenticating."""

    _attr_has_entity_name = True
    _attr_name = "Connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.unique_id}_connectivity"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        """Return True when the last poll succeeded."""
        return self.coordinator.last_update_success

    @property
    def available(self) -> bool:
        """Connectivity sensor is always available (it reports the state)."""
        return True


class ComelitPushStatusSensor(
    CoordinatorEntity[ComelitDataUpdateCoordinator], BinarySensorEntity
):
    """Diagnostic: whether cloud-push ring notifications are active."""

    _attr_has_entity_name = True
    _attr_name = "Ring notifications"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:bell-ring"

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.unique_id}_push_status"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        """Return True when the FCM listener is registered and running."""
        pm = self.coordinator.push_manager
        return bool(pm and getattr(pm, "_started", False) and pm._fcm_token)

    @property
    def available(self) -> bool:
        return True


class ComelitRingingSensor(BinarySensorEntity):
    """On while the doorbell is ringing (auto-clears after a timeout)."""

    _attr_has_entity_name = True
    _attr_name = "Ringing"
    _attr_device_class = BinarySensorDeviceClass.SOUND
    _attr_icon = "mdi:doorbell-video"

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.unique_id}_ringing"
        self._attr_device_info = coordinator.device_info
        self._attr_is_on = False
        self._cancel_off = None

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
    def _handle_ring(self, _payload: dict) -> None:
        """Turn on and schedule auto-off."""
        self._attr_is_on = True
        self.async_write_ha_state()
        if self._cancel_off is not None:
            self._cancel_off()
        self._cancel_off = async_call_later(
            self.hass, RING_ACTIVE_SECONDS, self._clear
        )

    @callback
    def _clear(self, _now) -> None:
        self._attr_is_on = False
        self._cancel_off = None
        self.async_write_ha_state()
