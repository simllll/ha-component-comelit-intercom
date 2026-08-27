"""Camera platform: live video + snapshots for entrance panels.

Both the live stream and stills come from a single held ViP video call fed
into a local RTSP server (see :mod:`video_stream`). On a ring the camera
proactively refreshes its still so automations can attach a fresh image to a
push notification.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ComelitDataUpdateCoordinator
from .entity import ComelitEntity
from .events import address_matches
from .fcm_push import signal_doorbell, signal_snapshot

_LOGGER = logging.getLogger(__name__)

# Serve the cached still for this long before pulling a fresh one.
_SNAPSHOT_TTL = 8.0
# How long a ring notification's image fetch waits for the fresh inbound
# snapshot before giving up and serving whatever's cached. The inbound preview
# sequence takes a few seconds to yield the first frame.
_RING_SNAPSHOT_WAIT = 9.0


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
    """Live camera + snapshots for an entrance panel."""

    _attr_icon = "mdi:doorbell-video"
    _attr_supported_features = CameraEntityFeature.STREAM

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
        # On-ring coordination: when this entrance rings, the coordinator runs
        # the inbound preview and pushes a fresh still. `async_camera_image`
        # (what a ring notification fetches via camera_proxy) waits on this
        # event until that still lands, so it serves the current frame instead
        # of the last cached one. `_ring_deadline` bounds the wait window.
        self._ring_event: asyncio.Event | None = None
        self._ring_deadline = 0.0

    async def async_added_to_hass(self) -> None:
        """Wire ring + fresh-snapshot signals."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_doorbell(self.coordinator.entry.entry_id),
                self._handle_ring,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_snapshot(self.coordinator.entry.entry_id),
                self._apply_snapshot,
            )
        )

    @callback
    def _handle_ring(self, payload: dict[str, Any]) -> None:
        caller = payload.get("caller") or ""
        if payload.get("source") == "cloud":
            # Cloud fallback: the local connection is down, so there's no
            # inbound call to snapshot from — use the on-demand outbound grab.
            self.hass.async_create_task(self._refresh(force=True))
        elif address_matches(caller, self._entrance):
            # Local ring: the coordinator runs the inbound preview and pushes a
            # fresh still. Arm the wait window so a notification's camera_proxy
            # fetch blocks for that still instead of returning a stale one.
            self._ring_event = asyncio.Event()
            self._ring_deadline = time.monotonic() + _RING_SNAPSHOT_WAIT

    @callback
    def _apply_snapshot(self, entrance: str, jpeg: bytes) -> None:
        """Store a fresh still pushed by the coordinator's on-ring capture."""
        if not jpeg or not address_matches(entrance, self._entrance):
            return
        self._image = jpeg
        self._image_ts = time.monotonic()
        if self._ring_event is not None:
            self._ring_event.set()
        self.async_write_ha_state()

    async def stream_source(self) -> str | None:
        """Return the local RTSP URL for live view (starts the call if needed).

        Note: Home Assistant's Camera base class calls ``stream_source`` — this
        method name must match exactly for live streaming to work.
        """
        return await self.coordinator.stream.async_stream_source(self._entrance)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still, pulling a fresh one from the stream if stale."""
        # If this entrance just rang, wait for the coordinator's inbound
        # snapshot so a ring notification attaches the current frame.
        ev = self._ring_event
        if ev is not None and not ev.is_set():
            remaining = self._ring_deadline - time.monotonic()
            if remaining > 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(ev.wait(), timeout=remaining)
        if self._image and (time.monotonic() - self._image_ts) < _SNAPSHOT_TTL:
            return self._image
        await self._refresh()
        return self._image

    async def _refresh(self, force: bool = False) -> None:
        if self._lock.locked():
            # A capture is already in progress; the caller gets the cached one.
            return
        async with self._lock:
            if (
                not force
                and self._image
                and (time.monotonic() - self._image_ts) < _SNAPSHOT_TTL
            ):
                return
            image = await self.coordinator.stream.async_get_image(self._entrance)
            if image:
                self._image = image
                self._image_ts = time.monotonic()
                self.async_write_ha_state()
