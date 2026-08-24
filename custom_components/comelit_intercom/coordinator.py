"""DataUpdateCoordinator for Comelit."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .comelit_client import IconaBridgeClient
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    DEFAULT_PORT,
    DOMAIN,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class ComelitDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Comelit data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.host = entry.data[CONF_HOST]
        self.port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self.token = entry.data[CONF_TOKEN]
        self.client = IconaBridgeClient(self.host, self.port)
        self.vip_config: dict[str, Any] = {}
        self.server_info: dict[str, Any] = {}
        # Set by __init__.py when doorbell events are enabled.
        self.events_manager = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Shared device info, enriched with server-info when available."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.unique_id)},
            name=f"Comelit Intercom ({self.host})",
            manufacturer="Comelit",
            model=self.server_info.get("model", "ICONA Bridge"),
            sw_version=self.server_info.get("version"),
            serial_number=self.server_info.get("serial-code"),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Comelit."""
        try:
            await self.client.connect()

            # Authenticate
            auth_code = await self.client.authenticate(self.token)
            if auth_code != 200:
                raise ConfigEntryAuthFailed(
                    f"Authentication failed with code {auth_code}"
                )

            # Fetch device info once (model / firmware / serial).
            if not self.server_info:
                try:
                    info = await self.client.get_server_info()
                    if info:
                        self.server_info = info
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("server-info fetch failed: %s", err)

            # Get configuration
            config = await self.client.get_config("all")
            if not config or "vip" not in config:
                raise UpdateFailed("Failed to get configuration from device")

            self.vip_config = config["vip"]
            user_params = self.vip_config.get("user-parameters", {})
            doors = user_params.get("opendoor-address-book", [])
            actuators = user_params.get("actuator-address-book", [])

            return {
                "doors": doors,
                "actuators": actuators,
                "vip": self.vip_config,
            }

        except ConfigEntryAuthFailed:
            # Re-raise auth errors
            raise
        except Exception as err:
            _LOGGER.error("Error communicating with Comelit device: %s", err)
            raise UpdateFailed(f"Error communicating with device: {err}") from err
        finally:
            # Always close the connection after update
            await self.client.shutdown()

    async def async_open_door(self, door_name: str) -> None:
        """Open a specific door."""
        # Create a separate client instance for door operations
        # to avoid interfering with the coordinator's update cycle
        door_client = IconaBridgeClient(self.host, self.port)
        try:
            await door_client.connect()

            # Authenticate
            auth_code = await door_client.authenticate(self.token)
            if auth_code != 200:
                raise Exception(f"Authentication failed with code {auth_code}")

            # Find the door
            doors = self.data.get("doors", [])
            door = next((d for d in doors if d.get("name") == door_name), None)
            if not door:
                raise Exception(f"Door '{door_name}' not found")

            # Open the door
            await door_client.open_door(self.vip_config, door)

        except Exception as err:
            _LOGGER.error("Error opening door %s: %s", door_name, err)
            raise
        finally:
            # Always clean up the door client connection
            await door_client.shutdown()

    async def async_open_actuator(self, actuator_name: str) -> None:
        """Trigger a specific actuator (gate/barrier)."""
        # Separate client instance, like door operations
        actuator_client = IconaBridgeClient(self.host, self.port)
        try:
            await actuator_client.connect()

            auth_code = await actuator_client.authenticate(self.token)
            if auth_code != 200:
                raise Exception(f"Authentication failed with code {auth_code}")

            actuators = self.data.get("actuators", [])
            actuator = next(
                (a for a in actuators if a.get("name") == actuator_name), None
            )
            if not actuator:
                raise Exception(f"Actuator '{actuator_name}' not found")

            await actuator_client.open_actuator(self.vip_config, actuator)

        except Exception as err:
            _LOGGER.error("Error opening actuator %s: %s", actuator_name, err)
            raise
        finally:
            await actuator_client.shutdown()
