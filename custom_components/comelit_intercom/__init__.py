"""The Comelit Intercom integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ENABLE_NOTIFICATIONS, DOMAIN
from .coordinator import ComelitDataUpdateCoordinator
from .fcm_push import ComelitPushManager
from .test_service import SERVICE_TEST_CONNECTION, async_setup_test_service

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
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

    # Optional: real-time doorbell/ring events via Comelit cloud push (FCM).
    # Enabled by default; disable via the options flow.
    if entry.options.get(CONF_ENABLE_NOTIFICATIONS, True):
        push_manager = ComelitPushManager(
            hass, entry, lambda: coordinator.vip_config
        )
        coordinator.push_manager = push_manager
        # Start in the background so a slow/offline FCM checkin never blocks setup.
        entry.async_create_background_task(
            hass, push_manager.async_start(), "comelit_fcm_start"
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the diagnostic services once per HA instance
    if not hass.services.has_service(DOMAIN, SERVICE_TEST_CONNECTION):
        await async_setup_test_service(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ComelitConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = entry.runtime_data
    if coordinator.push_manager is not None:
        await coordinator.push_manager.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
