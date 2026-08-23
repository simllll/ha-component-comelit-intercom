"""Shared base entity for the Comelit integration."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ComelitDataUpdateCoordinator


class ComelitEntity(CoordinatorEntity[ComelitDataUpdateCoordinator]):
    """Base for coordinator-backed Comelit entities (shared device info)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize with the shared device info."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
