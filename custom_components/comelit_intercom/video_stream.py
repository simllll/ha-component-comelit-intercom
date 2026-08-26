"""Live video streaming (and stills) for Comelit entrances.

Holds a SINGLE ViP video call to an entrance panel, feeding a local RTSP server
that Home Assistant's stream component (go2rtc) connects to. Both live view and
still images come from that one call — the intercom serves only one video call
at a time, so anything that opens a second, competing call causes the device to
drop the connection. Keeping a single shared call avoids that churn.

The video session REUSES the coordinator's single shared, authenticated ICONA
connection and its already-open CTPP registration (never a second CTPP — two
CTPP registrations on one ViP identity make the device drop video after ~3s).
Before starting a session the manager pauses the doorbell VIP listener (which
reads from the same CTPP channel), and resumes it once video stops/idles.

The call starts lazily on first use, is kept alive while anything is watching
(an RTSP client) or recently asked for a still, is recycled if its media stalls
(the device dropped it), and is stopped after a short idle period.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from .icona.client import IconaBridgeClient as SharedIconaClient
from .icona.models import DeviceConfig
from .icona.rtsp_server import LocalRtspServer
from .icona.video_call import VideoCallSession

if TYPE_CHECKING:
    from .coordinator import ComelitDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Stop the call this long after the last viewer/still request.
_IDLE_TIMEOUT = 30.0
# Grace period after starting a call before health/idle checking (lets media ramp
# and HA/go2rtc connect).
_CONNECT_GRACE = 12.0
# Recycle the call if no new media packets arrive for this long (device dropped
# it — e.g. BrokenPipe — so the next request starts a clean one).
_STALL_TIMEOUT = 10.0
# How long to wait for a freshly-decoded frame for a still.
_SNAPSHOT_TIMEOUT = 8.0


class ComelitStreamManager:
    """Owns one persistent RTSP server and a single on-demand ViP video call."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        token: str,
        vip_provider: Callable[[], dict],
        get_shared_client: Callable[[], SharedIconaClient | None],
        coordinator: ComelitDataUpdateCoordinator,
    ) -> None:
        """Initialize the manager (does not connect until first use)."""
        self.hass = hass
        self._host = host
        self._port = port
        self._token = token
        self._vip = vip_provider
        # Returns the coordinator's single shared authenticated ICONA client
        # (the CTPP owner) — video sessions reuse it and its CTPP channel.
        self._get_shared_client = get_shared_client
        self._coordinator = coordinator
        self._server: LocalRtspServer | None = None
        self._session: VideoCallSession | None = None
        self._entrance: str | None = None
        # Whether the current session was started in answer mode (two-way,
        # joining a live ring) vs a plain outbound view.
        self._session_answer_mode = False
        self._lock = asyncio.Lock()
        self._idle_task: asyncio.Task | None = None
        self._last_use = 0.0

    def _touch(self) -> None:
        self._last_use = self.hass.loop.time()

    def _entrances(self) -> list[str]:
        """All configured entrance panel addresses."""
        books = (self._vip() or {}).get("user-parameters", {})
        return [
            e["apt-address"]
            for e in books.get("entrance-address-book", [])
            if e.get("apt-address")
        ]

    def _ring_active_for(self, entrance: str) -> bool:
        """True if a ring from *this* entrance is live (→ answer, not view).

        Per-entrance so that, with several video doorbells, only the camera
        that actually rang answers; the others open as plain views.
        """
        events = self._coordinator.events_manager
        return events is not None and events.ring_active_for(entrance)

    def _ringing_entrance(self) -> str | None:
        """The configured entrance whose ring is currently active, if any."""
        events = self._coordinator.events_manager
        if events is None:
            return None
        for ent in self._entrances():
            if events.ring_active_for(ent):
                return ent
        return None

    def default_entrance(self) -> str | None:
        """First entrance panel address from the config (for the answer service)."""
        entrances = self._entrances()
        return entrances[0] if entrances else None

    async def async_answer(self, entrance: str | None = None) -> bool:
        """Explicitly answer the active ring (two-way audio).

        Used by the answer service. If *entrance* is omitted, targets the
        entrance that actually rang (so the right camera shows it), falling
        back to the first configured entrance. Works best while a ring is
        active; if none is, the device has no call to join.
        """
        target = entrance or self._ringing_entrance() or self.default_entrance()
        if not target:
            _LOGGER.warning("answer: no entrance configured")
            return False
        async with self._lock:
            try:
                await self._ensure(target, answer_mode=True)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Failed to answer call: %s", err)
                await self._stop_session("answer failure")
                return False
            self._touch()
            return True

    async def async_stream_source(self, entrance: str) -> str | None:
        """Ensure the shared call is running and return the RTSP URL."""
        async with self._lock:
            try:
                # Opening the view while THIS entrance's ring is live answers
                # it (two-way); otherwise it's a plain outbound view. Per
                # entrance, so with multiple doorbells only the one that rang
                # answers.
                await self._ensure(entrance, answer_mode=self._ring_active_for(entrance))
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Failed to start live video call: %s", err)
                await self._stop_session("start failure")
                return None
            self._touch()
            url = self._server.rtsp_url if self._server else None
            _LOGGER.debug("stream_source(%s) -> %s", entrance, url)
            return url

    async def async_get_image(
        self, entrance: str, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a fresh JPEG still from the shared call."""
        async with self._lock:
            try:
                await self._ensure(entrance)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Snapshot: failed to start video call: %s", err)
                await self._stop_session("snapshot start failure")
                return None
            self._touch()
            rx = self._session.rtp_receiver if self._session else None
            if rx is None:
                return None
            try:
                jpeg = await rx.get_jpeg_frame(timeout=_SNAPSHOT_TIMEOUT)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Snapshot decode failed: %s", err)
                jpeg = None
            if jpeg is None:
                # No fresh frame → the call likely died; drop it so the next
                # request starts a clean one instead of returning a frozen frame.
                _LOGGER.debug("Snapshot: no fresh frame, recycling call")
                await self._stop_session("no fresh frame")
            else:
                _LOGGER.debug("Snapshot: %d byte JPEG", len(jpeg))
            return jpeg

    # --- lifecycle -------------------------------------------------------

    async def _ensure(self, entrance: str, answer_mode: bool = False) -> None:
        """Start the RTSP server + shared call to *entrance* if not already up.

        `answer_mode` upgrades a plain view into a two-way answer of the live
        ring — only ever an upgrade, never a downgrade, so a passive snapshot
        (answer_mode=False) never tears down an active answer call.
        """
        if self._server is None:
            self._server = LocalRtspServer()
            await self._server.start()
            _LOGGER.debug("RTSP server started at %s", self._server.rtsp_url)

        need_new = (
            self._session is None
            or not self._session.active
            or self._entrance != entrance
        )
        upgrade = answer_mode and not self._session_answer_mode
        if need_new or upgrade:
            if self._session is not None:
                _LOGGER.debug(
                    "Recreating call (active=%s, entrance %s->%s, answer=%s->%s)",
                    self._session.active,
                    self._entrance,
                    entrance,
                    self._session_answer_mode,
                    answer_mode,
                )
            # Don't resume the listener between stop and immediate restart —
            # _start_session pauses it again right away.
            await self._stop_session("restart", resume_listener=False)
            await self._start_session(entrance, answer_mode=answer_mode)
            self._arm_idle_monitor()
        else:
            _LOGGER.debug("Reusing existing call to %s", entrance)

    async def _start_session(self, entrance: str, answer_mode: bool = False) -> None:
        # Reuse the coordinator's single shared, authenticated ICONA client and
        # its already-open CTPP registration — never open a second connection
        # or a second CTPP (two CTPP registrations make the device drop video).
        client = self._get_shared_client()
        if client is None or not client.connected:
            raise RuntimeError("shared ICONA connection not available")

        events = self._coordinator.events_manager
        if answer_mode:
            # Two-way answer needs a FRESH CTPP registration (the 6741W won't
            # give audio on our reused held one). Release the shared CTPP so
            # the session opens/inits its own — this also pauses the listener.
            await self._coordinator.async_release_ctpp()
        elif events is not None:
            # Plain view: pause the listener but reuse the shared CTPP (stable).
            with contextlib.suppress(Exception):
                await events.async_pause_local()

        # Serialise CTPP negotiation with any other CTPP user (device only
        # handles one negotiation at a time).
        async with self._coordinator.ctpp_lock:
            vip = self._vip() or {}
            config = DeviceConfig(
                apt_address=vip.get("apt-address", ""),
                apt_subaddress=vip.get("apt-subaddress", 0),
                caller_address=entrance,
            )
            self._server.reset()
            # Forward any ring seen on CTPP during the call to the events
            # manager — the doorbell listener is paused while video holds the
            # channel, so this keeps mid-call rings from being lost.
            on_ring = None
            if events is not None:
                on_ring = events.handle_ring
            self._session = VideoCallSession(
                client,
                config,
                auto_timeout=False,
                rtsp_server=self._server,
                on_ring=on_ring,
                answer_mode=answer_mode,
            )
            await self._session.start()
        self._server.mark_ready()
        self._entrance = entrance
        self._session_answer_mode = answer_mode
        _LOGGER.info(
            "Live video call started to entrance %s (%s)",
            entrance,
            "answer/two-way" if answer_mode else "view",
        )

    async def _stop_session(self, reason: str = "", resume_listener: bool = True) -> None:
        if self._session is not None:
            _LOGGER.debug("Stopping video call (%s)", reason)
            with contextlib.suppress(Exception):
                await self._session.stop()
            self._session = None
        was_answer = self._session_answer_mode
        self._entrance = None
        self._session_answer_mode = False
        if self._server is not None:
            self._server.mark_not_ready()
        # Hand the CTPP channel back to the doorbell listener. Skipped on
        # reconnect teardown (the shared client is dead; the coordinator
        # re-attaches the listener after it re-opens CTPP).
        if resume_listener:
            if was_answer:
                # The answer used its own fresh CTPP (now closed) — reopen the
                # shared registration and restart the listener.
                with contextlib.suppress(Exception):
                    await self._coordinator.async_restore_ctpp()
            else:
                events = self._coordinator.events_manager
                if events is not None:
                    with contextlib.suppress(Exception):
                        await events.async_resume_local()

    async def async_stop_for_reconnect(self) -> None:
        """Stop any active session without resuming the listener.

        Called by the coordinator when the shared connection dropped — the old
        session holds a reference to the dead client; the coordinator will
        re-attach the listener itself once CTPP is re-opened.
        """
        async with self._lock:
            if self._idle_task and not self._idle_task.done():
                self._idle_task.cancel()
            await self._stop_session("reconnect", resume_listener=False)

    def _arm_idle_monitor(self) -> None:
        if self._idle_task and not self._idle_task.done():
            return
        self._idle_task = self.hass.async_create_background_task(
            self._idle_monitor(), "comelit_stream_idle"
        )

    async def _idle_monitor(self) -> None:
        """Recycle a stalled (dropped) call and stop the call when idle."""
        await asyncio.sleep(_CONNECT_GRACE)
        loop = self.hass.loop
        last_pkts = -1
        stalled_since: float | None = None
        while True:
            await asyncio.sleep(2.0)
            session = self._session
            server = self._server
            if session is None or server is None:
                return
            if not session.active:
                async with self._lock:
                    await self._stop_session("inactive")
                return

            rx = session.rtp_receiver
            pkts = (
                rx.tcp_media_packet_count + rx.udp_media_packet_count if rx else 0
            )
            now = loop.time()

            # Liveness: media must keep flowing while a call is up.
            if pkts != last_pkts:
                last_pkts = pkts
                stalled_since = None
            elif stalled_since is None:
                stalled_since = now
            elif now - stalled_since >= _STALL_TIMEOUT:
                _LOGGER.warning(
                    "Video media stalled %.0fs (device dropped the call?) — recycling",
                    now - stalled_since,
                )
                async with self._lock:
                    await self._stop_session("media stalled")
                return

            # Idle: no live viewers and no recent still requests.
            if (
                server.client_count == 0
                and now - self._last_use >= _IDLE_TIMEOUT
            ):
                async with self._lock:
                    if (
                        self._server
                        and self._server.client_count == 0
                        and loop.time() - self._last_use >= _IDLE_TIMEOUT
                    ):
                        _LOGGER.info("No viewers/stills — stopping live video call")
                        await self._stop_session("idle")
                return

    async def async_shutdown(self) -> None:
        """Tear down the call and RTSP server (on entry unload)."""
        async with self._lock:
            if self._idle_task and not self._idle_task.done():
                self._idle_task.cancel()
            await self._stop_session("shutdown", resume_listener=False)
            if self._server is not None:
                with contextlib.suppress(Exception):
                    await self._server.stop()
                self._server = None
