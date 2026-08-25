"""Event platform: one doorbell per entrance panel, plus any other caller
(e.g. the floor/"Etagen" call) created dynamically on its first ring.

Entrance panels are known from the address book, so their doorbell entities are
created up front. The floor call, by contrast, may or may not exist depending on
the installation (apartment block vs single-house/kit) — rather than guess, we
create a doorbell entity the first time a ring arrives from a caller that isn't a
known entrance. That avoids a permanently-"unknown" entity while still supporting
any setup that does have a floor call.
"""

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
from .events import address_matches
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

    # Known entrance panels → one doorbell each, up front.
    created: dict[str, ComelitDoorbellEvent] = {}
    entities: list[ComelitDoorbellEvent] = []
    for ent in books.get("entrance-address-book", []):
        addr = ent.get("apt-address")
        if not addr:
            continue
        key = f"entrance_{addr}"
        entity = ComelitDoorbellEvent(
            coordinator,
            key=key,
            name=ent.get("name") or "Entrance",
            matcher=lambda c, a=addr: address_matches(c, a),
        )
        created[key] = entity
        entities.append(entity)
    if entities:
        async_add_entities(entities)

    @callback
    def _on_ring(payload: dict[str, Any]) -> None:
        """Create a doorbell entity the first time an unknown caller rings."""
        if payload.get("source") == "cloud":
            return  # cloud rings carry no caller — handled by existing entities
        caller = payload.get("caller") or ""
        if not caller or any(e.matches(caller) for e in created.values()):
            return
        # New caller. It's the floor/"Etagen" call if it's our own apartment
        # address; otherwise an unlisted entrance/caller.
        if apt and address_matches(caller, apt):
            key, name = "floor", "Floor call"
        else:
            key, name = f"caller_{caller}", caller
        if key in created:
            return
        entity = ComelitDoorbellEvent(
            coordinator,
            key=key,
            name=name,
            matcher=lambda c, x=caller: address_matches(c, x),
            initial_payload=payload,
        )
        created[key] = entity
        async_add_entities([entity])

    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_doorbell(entry.entry_id), _on_ring)
    )


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
        initial_payload: dict[str, Any] | None = None,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._matcher = matcher
        self._initial_payload = initial_payload
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.unique_id}_doorbell_{key}"

    def matches(self, caller: str) -> bool:
        """Return True if a ring from *caller* belongs to this doorbell."""
        return bool(caller) and self._matcher(caller)

    async def async_added_to_hass(self) -> None:
        """Subscribe to ring dispatches (and fire the ring that created us)."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_doorbell(self.coordinator.entry.entry_id),
                self._handle_ring,
            )
        )
        # If this entity was created dynamically for a ring already in flight,
        # fire that ring now (it happened before we were subscribed).
        if self._initial_payload is not None:
            self._handle_ring(self._initial_payload)
            self._initial_payload = None

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
