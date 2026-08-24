"""The Comelit Intercom integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ENABLE_NOTIFICATIONS, DOMAIN
from .coordinator import ComelitDataUpdateCoordinator
from .events import ComelitEventsManager
from .test_service import SERVICE_TEST_CONNECTION, async_setup_test_service

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.LOCK,
    Platform.SENSOR,
]

# Config entry with the coordinator attached as runtime_data.
type ComelitConfigEntry = ConfigEntry[ComelitDataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ComelitConfigEntry) -> bool:
    """Set up Comelit from a config entry."""
    coordinator = ComelitDataUpdateCoordinator(hass, entry)

    # Fetch initial data (raises ConfigEntryNotReady on failure)
    await coordinator.async_config_entry_first_refresh()

    # Store the coordinator on the config entry (modern runtime_data pattern)
    entry.runtime_data = coordinator

    # Optional: real-time doorbell/ring events. Local (held CTPP registration)
    # is primary; Comelit cloud push (FCM) is the automatic fallback.
    # Enabled by default; disable via the options flow.
    if entry.options.get(CONF_ENABLE_NOTIFICATIONS, True):
        events_manager = ComelitEventsManager(hass, entry, coordinator)
        coordinator.events_manager = events_manager
        # Start in the background so nothing blocks setup.
        entry.async_create_background_task(
            hass, events_manager.async_start(), "comelit_events_start"
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the diagnostic services once per HA instance
    if not hass.services.has_service(DOMAIN, SERVICE_TEST_CONNECTION):
        await async_setup_test_service(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ComelitConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = entry.runtime_data
    if coordinator.events_manager is not None:
        await coordinator.events_manager.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
