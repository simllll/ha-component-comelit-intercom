"""Unified doorbell events manager: local (CTPP) primary, cloud (FCM) fallback.

Prefers the local held-registration path (no internet, identifies which
doorbell). The local path now ATTACHES to the coordinator's single shared CTPP
registration (see :class:`VipEventListener`) instead of opening its own second
raw socket — two CTPP registrations on one ViP identity make the device drop
video. If the local registration can't be established or keeps dropping, falls
back to Comelit cloud push (FCM). Exposes the active source (local / cloud /
none) to HA.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DOMAIN,
    EVENT_DOORBELL,
)
from .fcm_push import ComelitPushManager, signal_doorbell
from .icona.vip_listener import VipEventListener

_LOGGER = logging.getLogger(__name__)

SOURCE_LOCAL = "local"
SOURCE_CLOUD = "cloud"
SOURCE_NONE = "none"

# How long to wait for the local path to attach before considering fallback.
_LOCAL_GRACE_SECONDS = 20


def signal_source(entry_id: str) -> str:
    """Dispatcher signal fired when the active events source changes."""
    return f"{DOMAIN}_events_source_{entry_id}"


def address_matches(caller: str | None, addr: str | None) -> bool:
    """Return True if a ring's caller address refers to ``addr``.

    Devices report the caller in slightly different forms across models:
    - 6742W: exact match (e.g. ``00000100``), and floor calls append a
      subaddress (``00000B060`` for apartment ``00000B06``) → prefix.
    - 6741W: the caller drops a leading character vs the address book
      (``B100001`` for entrance ``SB100001``) → suffix.

    So treat equality, either-direction prefix, or either-direction suffix as a
    match. Addresses are distinct enough that this doesn't cross-match entrance
    vs floor in practice.
    """
    if not caller or not addr:
        return False
    c, a = caller.upper(), addr.upper()
    return (
        c == a
        or c.startswith(a)
        or a.startswith(c)
        or c.endswith(a)
        or a.endswith(c)
    )


class ComelitEventsManager:
    """Owns the local VIP listener + FCM manager and picks the active source.

    The local listener attaches to the coordinator's shared CTPP connection.
    The coordinator drives attach/detach on connect/reconnect/unload; the
    stream manager drives pause/resume around a video session (video reuses the
    same CTPP channel, so the listener must yield it while video is up).
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, coordinator
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self._local: VipEventListener | None = None
        self._fcm: ComelitPushManager | None = None
        self._monitor: asyncio.Task | None = None
        self._source = SOURCE_NONE
        self._fcm_started = False
        # Loop time when local last went down — debounces cloud fallback so a
        # brief reconnect doesn't flap the source local↔cloud.
        self._local_down_since: float | None = None
        # True while a video session has borrowed the CTPP channel — the
        # listener is paused, but that is expected and must NOT trigger the
        # cloud fallback.
        self._paused_for_video = False

    @property
    def source(self) -> str:
        return self._source

    # --- lifecycle -------------------------------------------------------
    async def async_start(self) -> None:
        """Create the FCM fallback and start the source-selection monitor.

        The local listener itself is attached by the coordinator once the
        shared CTPP connection is up (async_attach_local); attach may already
        have happened by the time this runs.
        """
        # Cloud manager is created now but only started as a fallback.
        self._fcm = ComelitPushManager(
            self.hass,
            self.entry,
            lambda: self.coordinator.vip_config,
            on_ring=self._handle_ring,
        )

        self._monitor = self.entry.async_create_background_task(
            self.hass, self._monitor_loop(), "comelit_events_monitor"
        )

    async def async_stop(self) -> None:
        if self._monitor:
            self._monitor.cancel()
        await self.async_detach_local()
        if self._fcm and self._fcm_started:
            await self._fcm.async_stop()

    # --- local (shared CTPP) attach/detach -------------------------------
    async def async_attach_local(self) -> None:
        """Attach the VIP listener to the shared client's CTPP channel.

        Called by the coordinator after the shared connection + CTPP are up.
        """
        if self._paused_for_video:
            return
        client = self.coordinator.shared_client
        if client is None:
            return
        # Replace any stale listener.
        await self._stop_local()
        vip = self.coordinator.vip_config or {}
        apt = vip.get("apt-address", "")
        sub = vip.get("apt-subaddress", 0)
        listener = VipEventListener(
            client,
            apt,
            sub,
            self._handle_ring,
            init_ts=self.coordinator.ctpp_init_ts,
        )
        try:
            await listener.start()
            self._local = listener
            _LOGGER.debug("Local doorbell listener attached")
            await self._evaluate()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Failed to attach local doorbell listener", exc_info=True)
            self._local = None
            await self._evaluate()

    async def async_detach_local(self) -> None:
        """Stop the local listener (on unload / reconnect)."""
        await self._stop_local()

    async def async_pause_local(self) -> None:
        """Pause the listener so a video session can reuse the CTPP channel.

        Leaves CTPP/CSPB open; only cancels the read loop.
        """
        self._paused_for_video = True
        if self._local is not None:
            with contextlib.suppress(Exception):
                await self._local.stop_task()
            self._local = None
            _LOGGER.debug("Local doorbell listener paused for video")

    async def async_resume_local(self) -> None:
        """Resume the listener after a video session released the CTPP channel."""
        self._paused_for_video = False
        await self.async_attach_local()

    async def _stop_local(self) -> None:
        if self._local is not None:
            with contextlib.suppress(Exception):
                await self._local.stop()
            self._local = None

    # --- source selection ------------------------------------------------
    async def _monitor_loop(self) -> None:
        # Give local a grace period to come up before considering fallback.
        await asyncio.sleep(_LOCAL_GRACE_SECONDS)
        while True:
            await self._evaluate()
            await asyncio.sleep(30)

    async def _evaluate(self) -> None:
        # While video has borrowed CTPP, the listener is intentionally paused —
        # keep the current source rather than flapping to cloud/none.
        if self._paused_for_video:
            return

        local_ok = self._local is not None and self._local.running
        if local_ok:
            self._local_down_since = None
            new_source = SOURCE_LOCAL
            if self._fcm_started:
                _LOGGER.info("Local events registered; stopping cloud fallback")
                await self._fcm.async_stop()
                self._fcm_started = False
        else:
            # Debounce transient local outages (e.g. a shared-connection
            # reconnect briefly detaches the listener) so the source doesn't
            # flap local↔cloud. Only fall back to cloud after the grace period.
            now = self.hass.loop.time()
            if self._local_down_since is None:
                self._local_down_since = now
            if now - self._local_down_since < _LOCAL_GRACE_SECONDS:
                return
            if not self._fcm_started and self._fcm is not None:
                _LOGGER.info(
                    "Local events unavailable; starting cloud (FCM) fallback"
                )
                await self._fcm.async_start()
                self._fcm_started = True
            new_source = (
                SOURCE_CLOUD
                if self._fcm_started and self._fcm and self._fcm._fcm_token
                else SOURCE_NONE
            )
        self._set_source(new_source)

    def _set_source(self, source: str) -> None:
        if source != self._source:
            self._source = source
            _LOGGER.info("Doorbell events source is now: %s", source)
            async_dispatcher_send(self.hass, signal_source(self.entry.entry_id), source)

    # --- ring handling ---------------------------------------------------
    @callback
    def _handle_ring(self, payload: dict[str, Any]) -> None:
        """Common entry point for both local and cloud rings."""
        payload.setdefault("source", self._source)
        payload.setdefault("event_type", "ring")
        payload["doorbell"] = self._doorbell_name(payload.get("caller"))
        _LOGGER.info(
            "Doorbell ring (source=%s, doorbell=%s)",
            payload.get("source"),
            payload.get("doorbell"),
        )
        self.hass.bus.async_fire(EVENT_DOORBELL, payload)
        async_dispatcher_send(
            self.hass, signal_doorbell(self.entry.entry_id), payload
        )

    def _doorbell_name(self, caller: str | None) -> str | None:
        """Map a caller VIP address to a friendly doorbell name."""
        if not caller:
            return None
        vip = self.coordinator.vip_config or {}
        books = vip.get("user-parameters", {})
        for entry in books.get("entrance-address-book", []):
            if address_matches(caller, entry.get("apt-address")):
                return entry.get("name")
        apt = vip.get("apt-address", "")
        if address_matches(caller, apt):
            return "Floor call"
        return caller
