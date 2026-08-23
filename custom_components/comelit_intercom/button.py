"""Button platform for Comelit integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ComelitDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit button entities."""
    coordinator: ComelitDataUpdateCoordinator = entry.runtime_data

    # Create button entities for each door
    entities = []
    doors = coordinator.data.get("doors", [])

    for door in doors:
        entities.append(ComelitDoorButton(coordinator, door))

    # Create button entities for each actuator (gates/barriers)
    actuators = coordinator.data.get("actuators", [])

    for actuator in actuators:
        entities.append(ComelitActuatorButton(coordinator, actuator))

    async_add_entities(entities)


class ComelitDoorButton(CoordinatorEntity[ComelitDataUpdateCoordinator], ButtonEntity):
    """Representation of a Comelit door button."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-open"

    def __init__(
        self,
        coordinator: ComelitDataUpdateCoordinator,
        door: dict[str, Any],
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._door = door
        self._attr_name = door.get("name", "Unknown Door")

        # Create unique ID based on host and door details
        door_id = f"{door.get('apt-address', '')}_{door.get('output-index', '')}"
        self._attr_unique_id = f"{coordinator.entry.unique_id}_{door_id}"

        # Set device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.unique_id)},
            name=f"Comelit Intercom ({coordinator.host})",
            manufacturer="Comelit",
            model="ICONA Bridge",
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_open_door(self._door.get("name", ""))

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self._door.get("name") in [
            d.get("name") for d in self.coordinator.data.get("doors", [])
        ]


class ComelitActuatorButton(
    CoordinatorEntity[ComelitDataUpdateCoordinator], ButtonEntity
):
    """Representation of a Comelit ViP actuator (gate/barrier) button."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:gate"

    def __init__(
        self,
        coordinator: ComelitDataUpdateCoordinator,
        actuator: dict[str, Any],
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._actuator = actuator
        self._attr_name = actuator.get("name", "Unknown Actuator")

        # Unique ID based on host + actuator address/output (namespaced to avoid
        # clashing with door buttons that share apt-address/output-index)
        actuator_id = (
            f"actuator_{actuator.get('apt-address', '')}"
            f"_{actuator.get('output-index', '')}"
        )
        self._attr_unique_id = f"{coordinator.entry.unique_id}_{actuator_id}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.unique_id)},
            name=f"Comelit Intercom ({coordinator.host})",
            manufacturer="Comelit",
            model="ICONA Bridge",
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_open_actuator(self._actuator.get("name", ""))

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self._actuator.get(
            "name"
        ) in [a.get("name") for a in self.coordinator.data.get("actuators", [])]
