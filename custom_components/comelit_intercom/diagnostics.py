"""Diagnostics support for Comelit Intercom."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PUSH_TOKEN, CONF_TOKEN
from .coordinator import ComelitDataUpdateCoordinator

TO_REDACT = {CONF_TOKEN, CONF_PUSH_TOKEN, "user-token", "device-token", "serial-code"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: ComelitDataUpdateCoordinator = entry.runtime_data
    pm = coordinator.push_manager

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "server_info": async_redact_data(coordinator.server_info, TO_REDACT),
        "vip_config": async_redact_data(coordinator.vip_config, TO_REDACT),
        "counts": {
            "doors": len((coordinator.data or {}).get("doors", [])),
            "actuators": len((coordinator.data or {}).get("actuators", [])),
        },
        "last_update_success": coordinator.last_update_success,
        "push": {
            "enabled": pm is not None,
            "running": bool(pm and getattr(pm, "_started", False)),
            "token_registered": bool(pm and getattr(pm, "_fcm_token", None)),
        },
    }
