"""Unified doorbell events manager: local (CTPP) primary, cloud (FCM) fallback.

Prefers the local held-registration path (no internet, identifies which
doorbell). If the local registration can't be established or keeps dropping,
falls back to Comelit cloud push (FCM). Exposes the active source
(local / cloud / none) to HA.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_PUSH_TOKEN,
    CONF_TOKEN,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
    EVENT_DOORBELL,
)
from .fcm_push import ComelitPushManager, signal_doorbell
from .local_events import ComelitLocalEventListener

_LOGGER = logging.getLogger(__name__)

SOURCE_LOCAL = "local"
SOURCE_CLOUD = "cloud"
SOURCE_NONE = "none"

# Local failures before falling back to cloud.
_LOCAL_FAILURE_THRESHOLD = 3
# How long to wait for the local path to register before starting cloud.
_LOCAL_GRACE_SECONDS = 20


def signal_source(entry_id: str) -> str:
    """Dispatcher signal fired when the active events source changes."""
    return f"{DOMAIN}_events_source_{entry_id}"


class ComelitEventsManager:
    """Owns the local listener + FCM manager and picks the active source."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, coordinator
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self._local: ComelitLocalEventListener | None = None
        self._fcm: ComelitPushManager | None = None
        self._monitor: asyncio.Task | None = None
        self._source = SOURCE_NONE
        self._fcm_started = False

    @property
    def source(self) -> str:
        return self._source

    # --- lifecycle -------------------------------------------------------
    async def async_start(self) -> None:
        vip = self.coordinator.vip_config or {}
        apt = vip.get("apt-address")
        sub = vip.get("apt-subaddress", 0)
        token = (
            self.entry.options.get(CONF_PUSH_TOKEN)
            or self.entry.data.get(CONF_PUSH_TOKEN)
            or self.entry.data[CONF_TOKEN]
        )
        host = self.entry.data[CONF_HOST]
        port = self.entry.data.get(CONF_PORT, DEFAULT_PORT)

        # Cloud manager is created now but only started as a fallback.
        self._fcm = ComelitPushManager(
            self.hass, self.entry, lambda: self.coordinator.vip_config, on_ring=self._handle_ring
        )

        if apt:
            self._local = ComelitLocalEventListener(
                host, port, token, apt, sub, self._handle_ring, self._on_local_state
            )
            await self._local.async_start()

        self._monitor = self.entry.async_create_background_task(
            self.hass, self._monitor_loop(), "comelit_events_monitor"
        )

    async def async_stop(self) -> None:
        if self._monitor:
            self._monitor.cancel()
        if self._local:
            await self._local.async_stop()
        if self._fcm and self._fcm_started:
            await self._fcm.async_stop()

    # --- source selection ------------------------------------------------
    @callback
    def _on_local_state(self, _state: str) -> None:
        # Re-evaluate promptly on any local state change.
        self.hass.async_create_task(self._evaluate())

    async def _monitor_loop(self) -> None:
        # Give local a grace period to come up before considering fallback.
        await asyncio.sleep(_LOCAL_GRACE_SECONDS)
        while True:
            await self._evaluate()
            await asyncio.sleep(30)

    async def _evaluate(self) -> None:
        local_ok = self._local is not None and self._local.stable
        if local_ok:
            new_source = SOURCE_LOCAL
            if self._fcm_started:
                _LOGGER.info("Local events registered; stopping cloud fallback")
                await self._fcm.async_stop()
                self._fcm_started = False
        else:
            local_failing = (
                self._local is None
                or self._local.consecutive_failures >= _LOCAL_FAILURE_THRESHOLD
            )
            if not local_failing:
                # Local is mid-reconnect (transient) — keep the current source
                # rather than flapping to "none".
                return
            if not self._fcm_started:
                _LOGGER.info("Local events unavailable; starting cloud (FCM) fallback")
                await self._fcm.async_start()
                self._fcm_started = True
            new_source = (
                SOURCE_CLOUD
                if self._fcm_started and self._fcm._fcm_token
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
            if entry.get("apt-address") == caller:
                return entry.get("name")
        apt = vip.get("apt-address", "")
        if apt and caller.startswith(apt):
            return "Floor call"
        return caller
