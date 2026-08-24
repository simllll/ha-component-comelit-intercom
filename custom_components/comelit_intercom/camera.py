"""Camera platform: on-demand door-camera snapshots (+ snapshot on ring)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HOST, CONF_PORT, CONF_TOKEN, DEFAULT_PORT
from .coordinator import ComelitDataUpdateCoordinator
from .entity import ComelitEntity
from .fcm_push import signal_doorbell
from .video_snapshot import capture_snapshot

_LOGGER = logging.getLogger(__name__)

# Don't re-negotiate a fresh call for every image request within this window.
_SNAPSHOT_TTL = 8.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a camera per entrance panel."""
    coordinator: ComelitDataUpdateCoordinator = entry.runtime_data
    vip = coordinator.vip_config or {}
    books = vip.get("user-parameters", {})

    entities: list[Camera] = []
    for ent in books.get("entrance-address-book", []):
        addr = ent.get("apt-address")
        if not addr:
            continue
        entities.append(
            ComelitEntranceCamera(coordinator, ent.get("name") or "Entrance", addr)
        )
    async_add_entities(entities)


class ComelitEntranceCamera(ComelitEntity, Camera):
    """On-demand snapshot camera for an entrance panel."""

    _attr_icon = "mdi:doorbell-video"

    def __init__(
        self,
        coordinator: ComelitDataUpdateCoordinator,
        name: str,
        entrance_address: str,
    ) -> None:
        """Initialize."""
        ComelitEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._entrance = entrance_address
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.unique_id}_camera_{entrance_address}"
        self._image: bytes | None = None
        self._image_ts = 0.0
        self._lock = asyncio.Lock()

    async def async_added_to_hass(self) -> None:
        """Capture a fresh snapshot when this entrance rings."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_doorbell(self.coordinator.entry.entry_id),
                self._handle_ring,
            )
        )

    @callback
    def _handle_ring(self, payload: dict[str, Any]) -> None:
        caller = payload.get("caller") or ""
        # Refresh on this entrance's ring, or on any cloud ring (no caller).
        if payload.get("source") == "cloud" or caller == self._entrance:
            self.hass.async_create_task(self._refresh(force=True))

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a snapshot, negotiating a fresh one if the cache is stale."""
        if self._image and (time.monotonic() - self._image_ts) < _SNAPSHOT_TTL:
            return self._image
        await self._refresh()
        return self._image

    async def _refresh(self, force: bool = False) -> None:
        if self._lock.locked():
            # A capture is already in progress; the caller will get the cached one.
            return
        async with self._lock:
            if (
                not force
                and self._image
                and (time.monotonic() - self._image_ts) < _SNAPSHOT_TTL
            ):
                return
            vip = self.coordinator.vip_config or {}
            entry = self.coordinator.entry
            image = await capture_snapshot(
                self.hass,
                host=entry.data[CONF_HOST],
                port=entry.data.get(CONF_PORT, DEFAULT_PORT),
                token=entry.data[CONF_TOKEN],
                apt_address=vip.get("apt-address", ""),
                apt_subaddress=vip.get("apt-subaddress", 0),
                entrance_address=self._entrance,
            )
            if image:
                self._image = image
                self._image_ts = time.monotonic()
                self.async_write_ha_state()
