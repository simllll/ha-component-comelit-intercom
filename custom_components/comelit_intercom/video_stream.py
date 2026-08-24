"""Live video streaming (and stream-derived snapshots) for Comelit entrances.

Holds a single ViP video call to an entrance panel, feeding a local RTSP server
that Home Assistant's stream component (go2rtc) connects to. Snapshots are pulled
from the same live stream via ffmpeg, which is far more reliable than the old
one-shot capture (the device delivers media over TCP/RTPC2, which needs a
sustained, promptly-consumed connection).

The device serves only one video call at a time, so the call is started lazily
when a consumer appears and stopped after a short idle period once nobody is
watching.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from homeassistant.core import HomeAssistant

from .icona.channels import ChannelType
from .icona.client import IconaBridgeClient
from .icona.models import DeviceConfig
from .icona.rtsp_server import LocalRtspServer
from .icona.video_call import VideoCallSession

_LOGGER = logging.getLogger(__name__)

# Stop the call this long after the last RTSP client disconnects.
_IDLE_TIMEOUT = 30.0
# Grace period after starting a call before idle-checking (lets HA connect).
_CONNECT_GRACE = 12.0
# How long to wait for first media before a snapshot grab.
_MEDIA_WARMUP = 2.5


class ComelitStreamManager:
    """Owns one persistent RTSP server and an on-demand ViP video call."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        token: str,
        vip_provider: Callable[[], dict],
    ) -> None:
        """Initialize the manager (does not connect until first use)."""
        self.hass = hass
        self._host = host
        self._port = port
        self._token = token
        self._vip = vip_provider
        self._server: LocalRtspServer | None = None
        self._client: IconaBridgeClient | None = None
        self._session: VideoCallSession | None = None
        self._entrance: str | None = None
        self._lock = asyncio.Lock()
        self._idle_task: asyncio.Task | None = None

    async def async_stream_source(self, entrance: str) -> str | None:
        """Ensure a call is running to *entrance* and return the RTSP URL."""
        async with self._lock:
            try:
                await self._ensure(entrance)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Failed to start video stream: %s", err)
                await self._stop_session()
                return None
            return self._server.rtsp_url if self._server else None

    async def async_get_image(
        self, entrance: str, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a fresh JPEG still.

        If a live-view stream is already running we grab a frame from it
        (the device serves only one call at a time). Otherwise we place a
        clean, self-contained one-shot call — the reliable pattern for
        on-ring snapshots, unaffected by the device's ~30s call lease that
        eventually freezes a long-held stream.
        """
        if self._session is not None and self._session.active:
            rx = self._session.rtp_receiver
            if rx is not None:
                try:
                    return await rx.get_jpeg_frame(timeout=_MEDIA_WARMUP + 5)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Snapshot from live stream failed: %s", err)
                    return None
        return await self._oneshot_image(entrance)

    async def _oneshot_image(self, entrance: str) -> bytes | None:
        """Place a short fresh video call, decode one frame, tear down."""
        async with self._lock:
            client = IconaBridgeClient(self._host, self._port)
            server = LocalRtspServer()
            session: VideoCallSession | None = None
            try:
                await server.start()
                await client.connect()
                ua = await client.open_channel("UAUT", ChannelType.UAUT)
                resp = await client.send_json(
                    ua,
                    {
                        "message": "access",
                        "user-token": self._token,
                        "message-type": "request",
                        "message-id": 2,
                    },
                )
                if resp.get("response-code") != 200:
                    _LOGGER.warning(
                        "Snapshot auth failed (code %s)", resp.get("response-code")
                    )
                    return None
                vip = self._vip() or {}
                config = DeviceConfig(
                    apt_address=vip.get("apt-address", ""),
                    apt_subaddress=vip.get("apt-subaddress", 0),
                    caller_address=entrance,
                )
                session = VideoCallSession(
                    client, config, auto_timeout=False, rtsp_server=server
                )
                await session.start()
                return await session.rtp_receiver.get_jpeg_frame(
                    timeout=_MEDIA_WARMUP + 6
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("One-shot snapshot failed: %s", err)
                return None
            finally:
                if session is not None:
                    with contextlib.suppress(Exception):
                        await session.stop()
                with contextlib.suppress(Exception):
                    await client.disconnect()
                with contextlib.suppress(Exception):
                    await server.stop()

    # --- lifecycle -------------------------------------------------------

    async def _ensure(self, entrance: str) -> None:
        """Start the RTSP server and a call to *entrance* if not already up."""
        if self._server is None:
            self._server = LocalRtspServer()
            await self._server.start()
            _LOGGER.debug("RTSP server started at %s", self._server.rtsp_url)

        if (
            self._session is None
            or not self._session.active
            or self._entrance != entrance
        ):
            await self._stop_session()
            await self._start_session(entrance)
            self._arm_idle_monitor()

    async def _start_session(self, entrance: str) -> None:
        client = IconaBridgeClient(self._host, self._port)
        await client.connect()
        ua = await client.open_channel("UAUT", ChannelType.UAUT)
        resp = await client.send_json(
            ua,
            {
                "message": "access",
                "user-token": self._token,
                "message-type": "request",
                "message-id": 2,
            },
        )
        if resp.get("response-code") != 200:
            with contextlib.suppress(Exception):
                await client.disconnect()
            raise RuntimeError(f"authentication failed (code {resp.get('response-code')})")

        self._client = client
        vip = self._vip() or {}
        config = DeviceConfig(
            apt_address=vip.get("apt-address", ""),
            apt_subaddress=vip.get("apt-subaddress", 0),
            caller_address=entrance,
        )
        self._server.reset()
        self._session = VideoCallSession(
            client, config, auto_timeout=False, rtsp_server=self._server
        )
        await self._session.start()
        self._server.mark_ready()
        self._entrance = entrance
        _LOGGER.info("Live video call started to entrance %s", entrance)

    async def _stop_session(self) -> None:
        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._session.stop()
            self._session = None
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.disconnect()
            self._client = None
        self._entrance = None
        if self._server is not None:
            self._server.mark_not_ready()

    def _arm_idle_monitor(self) -> None:
        if self._idle_task and not self._idle_task.done():
            return
        self._idle_task = self.hass.async_create_background_task(
            self._idle_monitor(), "comelit_stream_idle"
        )

    async def _idle_monitor(self) -> None:
        """Stop the call once no RTSP client has been connected for a while."""
        await asyncio.sleep(_CONNECT_GRACE)
        empty_since: float | None = None
        loop = self.hass.loop
        while True:
            await asyncio.sleep(2.0)
            session = self._session
            server = self._server
            if session is None or not session.active or server is None:
                return
            if server.client_count > 0:
                empty_since = None
                continue
            now = loop.time()
            if empty_since is None:
                empty_since = now
            elif now - empty_since >= _IDLE_TIMEOUT:
                async with self._lock:
                    if self._server and self._server.client_count == 0:
                        _LOGGER.info("No stream viewers — stopping live video call")
                        await self._stop_session()
                return

    async def async_shutdown(self) -> None:
        """Tear down the call and RTSP server (on entry unload)."""
        async with self._lock:
            await self._stop_session()
            if self._idle_task and not self._idle_task.done():
                self._idle_task.cancel()
            if self._server is not None:
                with contextlib.suppress(Exception):
                    await self._server.stop()
                self._server = None
