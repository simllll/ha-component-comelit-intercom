"""Config flow for Comelit integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .comelit_client import IconaBridgeClient
from .const import (
    CONF_ENABLE_NOTIFICATIONS,
    CONF_PUSH_TOKEN,
    CONF_USER_MATCH,
    DEFAULT_PORT,
    DOMAIN,
)
from .token_extractor import extract_token

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_USER_MATCH): str,
        vol.Optional(CONF_TOKEN): str,
    }
)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    _LOGGER.info("Starting validation for Comelit device at %s", data[CONF_HOST])

    data = dict(data)
    user_match = data.get(CONF_USER_MATCH)
    token = data.get(CONF_TOKEN)

    # No explicit token: extract one from a device backup (default password).
    # If a dedicated user name/email is given, extract *that* user's token
    # (pair it once via the Comelit app first) — this gives HA its own identity,
    # required for cloud-free local doorbell events. Otherwise fall back to the
    # first (monitor) token.
    if not token:
        _LOGGER.info("No token provided, extracting from backup (match=%s)", user_match)
        try:
            token = await asyncio.wait_for(
                extract_token(data[CONF_HOST], match=user_match), timeout=30.0
            )
        except TimeoutError:
            _LOGGER.error("Token extraction timed out after 30 seconds")
            token = None
        except Exception as e:  # noqa: BLE001
            _LOGGER.error(f"Token extraction failed with error: {e}")
            token = None
        if not token:
            if user_match:
                raise InvalidAuth(
                    f"No user matching '{user_match}' found. Create that user in the "
                    "device web UI (port 8080) and pair it in the Comelit app first."
                )
            raise InvalidAuth(
                "Failed to extract token automatically. Check the device is reachable "
                "and uses the default 'comelit' password, or enter a token manually."
            )
        data[CONF_TOKEN] = token
        data.pop(CONF_USER_MATCH, None)

    client = IconaBridgeClient(data[CONF_HOST], data.get(CONF_PORT, DEFAULT_PORT))

    try:
        # Add timeout to prevent hanging
        _LOGGER.info("Attempting to connect to Comelit device at %s", data[CONF_HOST])
        await asyncio.wait_for(client.connect(), timeout=10.0)
        _LOGGER.info("Successfully connected to device")
    except TimeoutError as e:
        _LOGGER.error("Connection timeout to device at %s", data[CONF_HOST])
        raise CannotConnect("Connection timeout - device not responding") from e
    except OSError as err:
        # Special handling for macOS "No route to host" error
        if err.errno == 65:  # EHOSTUNREACH on macOS
            _LOGGER.error(
                "Cannot reach device at %s:%s - possible firewall or wrong port",
                data[CONF_HOST],
                64100,
            )
            raise CannotConnect(
                "Cannot reach device - check firewall settings"
            ) from err
        _LOGGER.error("Network error connecting to device: %s", err)
        raise CannotConnect(f"Network error: {err}") from err
    except Exception as err:
        _LOGGER.error("Cannot connect to device: %s", err)
        raise CannotConnect from err

    try:
        _LOGGER.info("Authenticating with device")
        auth_code = await asyncio.wait_for(
            client.authenticate(token), timeout=15.0
        )

        if auth_code != 200:
            _LOGGER.error("Authentication failed with code %s", auth_code)
            raise InvalidAuth(f"Authentication failed with code {auth_code}")

        _LOGGER.info("Authentication successful, getting configuration")

        # Get configuration to verify everything works
        config = await asyncio.wait_for(client.get_config("all"), timeout=15.0)

        if not config:
            raise CannotConnect("Failed to get configuration")

        _LOGGER.info("Configuration retrieved successfully")
        await client.shutdown()

        # Return info that you want to store in the config entry
        return {
            "title": f"Comelit Intercom ({data[CONF_HOST]})",
            "token": data.get(CONF_TOKEN),  # Include token in case it was extracted
        }

    except TimeoutError as err:
        _LOGGER.error("Operation timeout while communicating with device: %s", err)
        _LOGGER.error("This could be during connect, auth, or config retrieval")
        await client.shutdown()
        raise CannotConnect("Device communication timeout") from err
    except InvalidAuth:
        await client.shutdown()
        raise
    except CannotConnect:
        await client.shutdown()
        raise
    except Exception as err:
        _LOGGER.exception("Unexpected error during validation: %s", err)
        await client.shutdown()
        raise CannotConnect(f"Unexpected error: {err}") from err


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Comelit."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovered_host: str | None = None

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Return the options flow."""
        return OptionsFlowHandler()

    def _user_schema(self) -> vol.Schema:
        """User form schema, pre-filling a DHCP-discovered host if any."""
        if not self._discovered_host:
            return STEP_USER_DATA_SCHEMA
        return vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._discovered_host): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
                vol.Optional(CONF_USER_MATCH): str,
                vol.Optional(CONF_TOKEN): str,
            }
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> FlowResult:
        """Handle a Comelit device discovered via DHCP (OUI 00:25:29)."""
        host = discovery_info.ip
        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._discovered_host = host
        # Show the normal form, pre-filled with the discovered IP, so the user
        # can supply a dedicated-user name/email or a token.
        self.context["title_placeholders"] = {"name": f"Comelit ({host})"}
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(),
                description_placeholders={
                    "token_help": "Leave token empty to try automatic extraction"
                },
            )

        errors = {}
        validated_data = None

        try:
            info = await validate_input(self.hass, user_input)
            # Get the potentially updated data (with extracted/minted token)
            validated_data = user_input.copy()
            if info.get("token"):
                validated_data[CONF_TOKEN] = info["token"]
            # Don't persist the transient user-match hint.
            validated_data.pop(CONF_USER_MATCH, None)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth as e:
            errors["base"] = "invalid_auth"
            # If auto-extraction failed, show more helpful error
            if "extract token automatically" in str(e):
                errors["base"] = "auto_token_failed"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            # Check if already configured
            await self.async_set_unique_id(validated_data[CONF_HOST])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(title=info["title"], data=validated_data)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "token_help": "Leave token empty to try automatic extraction"
            },
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options: doorbell push notifications."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Drop an empty push-token override so it falls back to the main token.
            if not user_input.get(CONF_PUSH_TOKEN):
                user_input.pop(CONF_PUSH_TOKEN, None)
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ENABLE_NOTIFICATIONS,
                    default=options.get(CONF_ENABLE_NOTIFICATIONS, True),
                ): bool,
                vol.Optional(
                    CONF_PUSH_TOKEN,
                    description={"suggested_value": options.get(CONF_PUSH_TOKEN, "")},
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
