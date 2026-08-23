"""Diagnostic services for the Comelit Intercom integration.

These services are for debugging/inspection. Each opens a one-shot
connection to the device and RETURNS the result (Developer Tools ->
Actions shows the response), so you can verify connectivity, auth, and
see exactly which doors/actuators the bridge reports — without guessing.
"""

from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)

from .comelit_client import IconaBridgeClient
from .const import DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_TEST_CONNECTION = "test_connection"
SERVICE_TEST_AUTHENTICATE = "test_authenticate"
SERVICE_TEST_GET_CONFIG = "test_get_config"

_BASE_SCHEMA = {
    vol.Required("ip"): cv.string,
    vol.Optional("port", default=DEFAULT_PORT): cv.port,
}
CONNECTION_SCHEMA = vol.Schema(_BASE_SCHEMA)
AUTH_SCHEMA = vol.Schema({**_BASE_SCHEMA, vol.Required("token"): cv.string})


async def async_setup_test_service(hass: HomeAssistant) -> None:
    """Register the diagnostic services (once per HA instance)."""

    async def handle_test_connection(call: ServiceCall) -> ServiceResponse:
        """Open a raw TCP connection and report success/failure."""
        ip = call.data["ip"]
        port = call.data["port"]
        client = IconaBridgeClient(ip, port)
        try:
            await client.connect()
            return {"connected": True, "host": ip, "port": port}
        except Exception as err:  # noqa: BLE001 - surface any error to the caller
            _LOGGER.warning("test_connection to %s:%s failed: %s", ip, port, err)
            return {"connected": False, "host": ip, "port": port, "error": str(err)}
        finally:
            await client.shutdown()

    async def handle_test_authenticate(call: ServiceCall) -> ServiceResponse:
        """Connect and authenticate; return the auth response code."""
        ip = call.data["ip"]
        port = call.data["port"]
        token = call.data["token"]
        client = IconaBridgeClient(ip, port)
        try:
            await client.connect()
            auth_code = await client.authenticate(token)
            return {
                "connected": True,
                "auth_code": auth_code,
                "authenticated": auth_code == 200,
            }
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("test_authenticate to %s:%s failed: %s", ip, port, err)
            return {"connected": False, "authenticated": False, "error": str(err)}
        finally:
            await client.shutdown()

    async def handle_test_get_config(call: ServiceCall) -> ServiceResponse:
        """Connect, authenticate and return the discovered directory.

        Returns the doors, actuators and entrances the bridge reports,
        plus the raw list of user-parameter keys (handy when a device
        exposes openers under an unexpected address book).
        """
        ip = call.data["ip"]
        port = call.data["port"]
        token = call.data["token"]
        client = IconaBridgeClient(ip, port)
        try:
            await client.connect()
            auth_code = await client.authenticate(token)
            if auth_code != 200:
                return {
                    "authenticated": False,
                    "auth_code": auth_code,
                    "error": "Authentication failed",
                }

            config = await client.get_config("all")
            if not config or "vip" not in config:
                return {"authenticated": True, "error": "No configuration returned"}

            user_params = config["vip"].get("user-parameters", {})
            doors = user_params.get("opendoor-address-book", [])
            actuators = user_params.get("actuator-address-book", [])
            entrances = user_params.get("entrance-address-book", [])
            return {
                "authenticated": True,
                "user_parameter_keys": sorted(user_params.keys()),
                "door_count": len(doors),
                "actuator_count": len(actuators),
                "doors": doors,
                "actuators": actuators,
                "entrances": entrances,
            }
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("test_get_config to %s:%s failed: %s", ip, port, err)
            return {"error": str(err)}
        finally:
            await client.shutdown()

    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_CONNECTION,
        handle_test_connection,
        schema=CONNECTION_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_AUTHENTICATE,
        handle_test_authenticate,
        schema=AUTH_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_GET_CONFIG,
        handle_test_get_config,
        schema=AUTH_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    _LOGGER.debug("Comelit diagnostic services registered")
