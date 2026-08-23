"""The Comelit Intercom integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ComelitDataUpdateCoordinator
from .test_service import SERVICE_TEST_CONNECTION, async_setup_test_service

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON]

# Config entry with the coordinator attached as runtime_data.
type ComelitConfigEntry = ConfigEntry[ComelitDataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ComelitConfigEntry) -> bool:
    """Set up Comelit from a config entry."""
    coordinator = ComelitDataUpdateCoordinator(hass, entry)

    # Fetch initial data (raises ConfigEntryNotReady on failure)
    await coordinator.async_config_entry_first_refresh()

    # Store the coordinator on the config entry (modern runtime_data pattern)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the diagnostic services once per HA instance
    if not hass.services.has_service(DOMAIN, SERVICE_TEST_CONNECTION):
        await async_setup_test_service(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ComelitConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
