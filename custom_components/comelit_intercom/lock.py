"""Lock platform for Comelit doors and gates.

Exposes each door/actuator as a LockEntity supporting OPEN, so it works nicely
with dashboards and voice ("open/unlock the front door"). The openers are
momentary relay pulses with no state feedback, so the lock always reports
locked and simply triggers the pulse on unlock/open.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ComelitDataUpdateCoordinator
from .entity import ComelitEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit lock entities."""
    coordinator: ComelitDataUpdateCoordinator = entry.runtime_data

    entities: list[LockEntity] = []
    for door in coordinator.data.get("doors", []):
        entities.append(ComelitDoorLock(coordinator, door))
    for actuator in coordinator.data.get("actuators", []):
        entities.append(ComelitActuatorLock(coordinator, actuator))
    async_add_entities(entities)


class _ComelitOpenerLock(ComelitEntity, LockEntity):
    """Base momentary-opener lock (always locked; unlock/open triggers a pulse)."""

    _attr_supported_features = LockEntityFeature.OPEN

    @property
    def is_locked(self) -> bool:
        """Momentary opener has no state; always report locked."""
        return True

    async def async_lock(self, **kwargs: Any) -> None:
        """No-op: the opener cannot be actively locked."""

    async def async_unlock(self, **kwargs: Any) -> None:
        """Trigger the opener (same as open)."""
        await self.async_open(**kwargs)


class ComelitDoorLock(_ComelitOpenerLock):
    """A Comelit door as a lock."""

    def __init__(
        self, coordinator: ComelitDataUpdateCoordinator, door: dict[str, Any]
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._door = door
        self._attr_name = door.get("name", "Unknown Door")
        door_id = f"{door.get('apt-address', '')}_{door.get('output-index', '')}"
        self._attr_unique_id = f"{coordinator.entry.unique_id}_lock_{door_id}"

    async def async_open(self, **kwargs: Any) -> None:
        """Open the door."""
        await self.coordinator.async_open_door(self._door.get("name", ""))

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self._door.get("name") in [
            d.get("name") for d in self.coordinator.data.get("doors", [])
        ]


class ComelitActuatorLock(_ComelitOpenerLock):
    """A Comelit ViP actuator (gate/barrier) as a lock."""

    def __init__(
        self, coordinator: ComelitDataUpdateCoordinator, actuator: dict[str, Any]
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._actuator = actuator
        self._attr_name = actuator.get("name", "Unknown Actuator")
        actuator_id = (
            f"actuator_{actuator.get('apt-address', '')}"
            f"_{actuator.get('output-index', '')}"
        )
        self._attr_unique_id = f"{coordinator.entry.unique_id}_lock_{actuator_id}"

    async def async_open(self, **kwargs: Any) -> None:
        """Open the gate/barrier."""
        await self.coordinator.async_open_actuator(self._actuator.get("name", ""))

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self._actuator.get(
            "name"
        ) in [a.get("name") for a in self.coordinator.data.get("actuators", [])]
