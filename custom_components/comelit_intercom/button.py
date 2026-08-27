"""Button platform for the Comelit intercom.

Exposes an "Answer doorbell" button that starts two-way audio (TX) for an
active inbound call. The inbound call itself is answered automatically when
the device rings (see coordinator.async_start_inbound_video); pressing this
button opens the microphone path so the visitor can hear us.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ComelitDataUpdateCoordinator
from .entity import ComelitEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit button entities."""
    coordinator: ComelitDataUpdateCoordinator = entry.runtime_data
    async_add_entities([ComelitAnswerDoorbellButton(coordinator)])


class ComelitAnswerDoorbellButton(ComelitEntity, ButtonEntity):
    """Button to answer an active inbound doorbell call with two-way audio."""

    _attr_name = "Answer doorbell"

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize the answer doorbell button entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.unique_id}_answer_doorbell"

    async def async_press(self) -> None:
        """Start two-way audio for the active inbound call."""
        _LOGGER.info("Answering doorbell — starting audio")
        try:
            await self.coordinator.async_answer_inbound()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to answer doorbell")
