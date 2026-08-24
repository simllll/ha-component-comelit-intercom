"""Event platform: one doorbell per entrance panel + the floor ("Etagen") call."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ComelitDataUpdateCoordinator
from .entity import ComelitEntity
from .fcm_push import signal_doorbell

EVENT_TYPES = ["ring", "missed_call"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up doorbell event entities."""
    coordinator: ComelitDataUpdateCoordinator = entry.runtime_data
    if getattr(coordinator, "events_manager", None) is None:
        return

    vip = coordinator.vip_config or {}
    apt = vip.get("apt-address", "")
    books = vip.get("user-parameters", {})

    entities: list[EventEntity] = []

    # One doorbell per entrance panel.
    for ent in books.get("entrance-address-book", []):
        addr = ent.get("apt-address")
        if not addr:
            continue
        entities.append(
            ComelitDoorbellEvent(
                coordinator,
                key=f"entrance_{addr}",
                name=ent.get("name") or "Entrance",
                matcher=lambda c, a=addr: c == a,
            )
        )

    # The floor / "Etagen" call (the apartment's own door station) — always present.
    entities.append(
        ComelitDoorbellEvent(
            coordinator,
            key="floor",
            name="Floor call",
            matcher=lambda c, a=apt: bool(a) and bool(c) and c.startswith(a),
        )
    )

    async_add_entities(entities)


class ComelitDoorbellEvent(ComelitEntity, EventEntity):
    """A doorbell that fires 'ring'/'missed_call' for one caller."""

    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = EVENT_TYPES
    _attr_icon = "mdi:doorbell-video"

    def __init__(
        self,
        coordinator: ComelitDataUpdateCoordinator,
        key: str,
        name: str,
        matcher: Callable[[str], bool],
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._matcher = matcher
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.unique_id}_doorbell_{key}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to ring dispatches."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_doorbell(self.coordinator.entry.entry_id),
                self._handle_ring,
            )
        )

    @callback
    def _handle_ring(self, payload: dict[str, Any]) -> None:
        """Trigger if the ring's caller matches this doorbell."""
        caller = payload.get("caller") or ""
        # FCM (cloud) rings carry no caller — fire every doorbell so the ring
        # isn't lost; local rings are routed to the matching doorbell.
        if payload.get("source") == "cloud" or self._matcher(caller):
            event_type = payload.get("event_type", "ring")
            if event_type not in EVENT_TYPES:
                event_type = "ring"
            attrs = {
                k: v
                for k, v in payload.items()
                if k in ("call_id", "notification", "source", "doorbell", "caller")
                and v is not None
            }
            self._trigger_event(event_type, attrs)
            self.async_write_ha_state()
