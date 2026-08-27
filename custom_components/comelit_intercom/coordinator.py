"""DataUpdateCoordinator for Comelit.

Owns the SINGLE shared, persistent, authenticated ICONA Bridge connection that
is the one owner of the ViP CTPP registration. Both the doorbell event listener
and the live-video session ATTACH to / REUSE this one connection's CTPP channel
— never a second one. Two CTPP registrations on one ViP identity make the
device drop video after ~3s, so this shared-connection design is load-bearing.

Config, door and actuator operations still use short-lived connections via the
legacy ``comelit_client`` (they don't hold CTPP, so they don't contend).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .comelit_client import IconaBridgeClient
from .const import (
    CONF_AUTO_ANSWER,
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    DEFAULT_PORT,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .events import address_matches
from .fcm_push import signal_snapshot
from .icona.channels import ChannelType
from .icona.client import IconaBridgeClient as SharedIconaClient
from .icona.ctpp import _VIP_ACK_TS_INCR, ctpp_init_sequence
from .video_stream import ComelitStreamManager

_LOGGER = logging.getLogger(__name__)

# Keepalive cadence — well under the client's 300s idle timeout and the panel's
# ~120s renewal cycle, so the connection never goes idle-dead when nothing rings.
_KEEPALIVE_INTERVAL = 90


class ComelitDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Comelit data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.host = entry.data[CONF_HOST]
        self.port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self.token = entry.data[CONF_TOKEN]
        self.client = IconaBridgeClient(self.host, self.port)
        self.vip_config: dict[str, Any] = {}
        self.server_info: dict[str, Any] = {}
        # Set by __init__.py when doorbell events are enabled.
        self.events_manager = None

        # --- shared persistent ICONA connection (single CTPP owner) ---------
        self._shared_client: SharedIconaClient | None = None
        # Serialises CTPP negotiation: only one of {open, video-start} at a time.
        self._ctpp_lock = asyncio.Lock()
        # init_ts used in the last CTPP init on the shared connection — the VIP
        # listener derives its outgoing ACK timestamps from this.
        self._ctpp_init_ts: int = 0
        self._reconnecting = False
        # Proactive keepalive: the panel sleeps when idle and stops sending, so
        # the receive-loop's 300s idle timeout fires and churns a reconnect
        # every ~5 min. A periodic benign server-info query keeps the panel
        # replying (resets the idle timer) — the same benign query the app
        # sends, with no push-enrollment side effect.
        self._keepalive_task: asyncio.Task[None] | None = None

        # Live-video/snapshot manager reuses the shared connection's CTPP.
        self.stream = ComelitStreamManager(
            hass,
            self.host,
            self.port,
            self.token,
            lambda: self.vip_config,
            get_shared_client=lambda: self._shared_client,
            coordinator=self,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Shared device info, enriched with server-info when available."""
        model_code = self.server_info.get("model")
        # Map known internal server-info model codes to friendlier product names.
        model = {
            "MnWi": "6742W Mini ViP",
            "MSVF": "6741W Mini ViP",
        }.get(model_code, model_code or "ICONA Bridge")
        name = f"Comelit {model}" if model_code else "Comelit Intercom"
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.unique_id)},
            name=name,
            manufacturer="Comelit",
            model=model,
            sw_version=self.server_info.get("version"),
            serial_number=self.server_info.get("serial-code"),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Comelit."""
        try:
            await self.client.connect()

            # Authenticate
            auth_code = await self.client.authenticate(self.token)
            if auth_code != 200:
                raise ConfigEntryAuthFailed(
                    f"Authentication failed with code {auth_code}"
                )

            # Fetch device info once (model / firmware / serial).
            if not self.server_info:
                try:
                    info = await self.client.get_server_info()
                    if info:
                        self.server_info = info
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("server-info fetch failed: %s", err)

            # Get configuration
            config = await self.client.get_config("all")
            if not config or "vip" not in config:
                raise UpdateFailed("Failed to get configuration from device")

            self.vip_config = config["vip"]
            user_params = self.vip_config.get("user-parameters", {})
            doors = user_params.get("opendoor-address-book", [])
            actuators = user_params.get("actuator-address-book", [])

            return {
                "doors": doors,
                "actuators": actuators,
                "vip": self.vip_config,
            }

        except ConfigEntryAuthFailed:
            # Re-raise auth errors
            raise
        except Exception as err:
            _LOGGER.error("Error communicating with Comelit device: %s", err)
            raise UpdateFailed(f"Error communicating with device: {err}") from err
        finally:
            # Always close the (config-only) connection after update
            await self.client.shutdown()

    # --- shared connection lifecycle ----------------------------------------

    @property
    def shared_client(self) -> SharedIconaClient | None:
        """The single persistent authenticated ICONA client (CTPP owner)."""
        return self._shared_client

    @property
    def ctpp_lock(self) -> asyncio.Lock:
        """Serialises CTPP negotiation (open vs. video start)."""
        return self._ctpp_lock

    @property
    def ctpp_init_ts(self) -> int:
        """init_ts of the last CTPP init on the shared connection."""
        return self._ctpp_init_ts

    # --- inbound call answer (device-initiated ring) --------------------

    def _has_entrance_camera(self, addr: str) -> bool:
        """True if *addr* is an entrance panel with a camera (in the address book).

        Floor/Etagen calls come from the apartment's own address, which has no
        camera — answering them for a snapshot just runs a doomed video
        handshake (device never opens RTPC) and pauses the doorbell listener for
        the whole timeout. Skip those.
        """
        books = (self.vip_config or {}).get("user-parameters", {})
        return any(
            (ent.get("apt-address") and address_matches(addr, ent["apt-address"]))
            for ent in books.get("entrance-address-book", [])
        )

    def _on_inbound_ring(self, entrance_addr: str, ring_ts: int) -> bool:
        """Called by the VIP listener on a 0x18C0 call-init (doorbell ring).

        Returns True if we will run the inbound answer sequence (and therefore
        own the ring ACK); False if the listener should ACK the ring itself.

        Schedules the full 20-step inbound answer sequence as a background task
        so it never blocks the VIP listener read loop. The ring's LE32 timestamp
        (ring_ts) is required — the answer sequence derives fresh_ts from it via
        the device's proprietary transform.

        Skipped (returns False) for callers without a camera (floor/Etagen
        calls): there is no video to snapshot, so the sequence would only waste
        time and hold the listener. The normal doorbell event still fires.
        """
        if not self._has_entrance_camera(entrance_addr):
            _LOGGER.debug(
                "Inbound ring from %s has no camera (floor call) — skipping snapshot",
                entrance_addr,
            )
            return False
        _LOGGER.debug(
            "Inbound ring: entrance=%s ring_ts=0x%08X", entrance_addr, ring_ts
        )
        self.entry.async_create_background_task(
            self.hass,
            self.async_start_inbound_video(entrance_addr, ring_ts),
            "comelit-inbound-video",
        )
        return True

    async def async_start_inbound_video(
        self, entrance_addr: str, ring_ts: int
    ) -> None:
        """Answer a device-initiated ring: run inbound signaling and start media.

        Delegates to the stream manager, which reuses the shared client + held
        CTPP and pauses the doorbell listener for the duration (same model as
        the outbound video path). The normal ring event is fired separately by
        the VIP listener, so we do not re-fire it here.
        """
        # Renewal ACK ts the device expects during the call — same increment the
        # VIP listener uses for its keepalive ACKs (init_ts + 0x01010000).
        renewal_ack_ts = (self._ctpp_init_ts + _VIP_ACK_TS_INCR) & 0xFFFFFFFF
        auto_answer = self.entry.options.get(CONF_AUTO_ANSWER, False)
        ring_at = self.hass.loop.time()
        try:
            ok = await self.stream.async_start_inbound(
                entrance_addr, ring_ts, renewal_ack_ts=renewal_ack_ts
            )
            if not ok:
                return
            # Grab a fresh still from the preview and hand it to the camera so
            # a ring notification can attach a current image (the outbound
            # snapshot path conflicts with the busy, ringing panel).
            jpeg = await self.stream.async_grab_snapshot()
            if jpeg:
                async_dispatcher_send(
                    self.hass, signal_snapshot(self.entry.entry_id), entrance_addr, jpeg
                )
            # Snapshot-only preview: unless the user opted into auto-answer
            # (staying connected for two-way audio), release the call — but not
            # if someone opened a live view in the meantime (shared session).
            if not auto_answer:
                await self.stream.async_release_after_snapshot(ring_at)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Inbound video answer failed", exc_info=True)

    async def async_answer_inbound(self) -> None:
        """Start two-way audio for the active inbound call (answer button)."""
        await self.stream.async_answer_inbound()

    async def async_start_shared(self) -> None:
        """Connect + authenticate the shared client and open/init CTPP once.

        Idempotent-ish: safe to call at setup. Also (re)starts the doorbell
        VIP listener via the events manager once CTPP is up.
        """
        await self._connect_shared()

    async def _connect_shared(self) -> None:
        """(Re)establish the shared client, open CTPP+CSPB, run init."""
        client = SharedIconaClient(self.host, self.port)
        await client.connect()
        try:
            await self._authenticate(client)
        except Exception:
            with contextlib.suppress(Exception):
                await client.disconnect()
            raise

        self._shared_client = client
        client.set_disconnect_callback(self._on_shared_disconnect)

        # Open + initialise the single CTPP registration. Guarded by the CTPP
        # lock so it can't race a video start.
        async with self._ctpp_lock:
            await self._open_ctpp_channels(client)

        # Bring the doorbell listener up on the freshly opened CTPP.
        if self.events_manager is not None:
            with contextlib.suppress(Exception):
                await self.events_manager.async_attach_local()

        # Keep the connection alive so it doesn't churn every idle cycle.
        self._start_keepalive()

    async def _authenticate(self, client: SharedIconaClient) -> None:
        """Authenticate the shared client via an inline UAUT access request."""
        ua = await client.open_channel("UAUT", ChannelType.UAUT)
        resp = await client.send_json(
            ua,
            {
                "message": "access",
                "user-token": self.token,
                "message-type": "request",
                "message-id": 2,
            },
        )
        if resp.get("response-code") != 200:
            raise ConfigEntryAuthFailed(
                f"Shared client auth failed (code {resp.get('response-code')})"
            )

    async def _open_ctpp_channels(self, client: SharedIconaClient) -> int:
        """Open CTPP + CSPB and run the full CTPP init handshake.

        Stores the init_ts so the VIP listener derives matching ACK timestamps.
        Returns the init_ts used.
        """
        vip = self.vip_config or {}
        apt = vip.get("apt-address", "")
        sub = vip.get("apt-subaddress", 0)
        our_addr = f"{apt}{sub}"
        ctpp = await client.open_channel("CTPP", ChannelType.CTPP, extra_data=our_addr)
        await client.open_channel("CSPB", ChannelType.CSPB)
        ts = int(time.time()) & 0xFFFFFFFF
        await ctpp_init_sequence(client, ctpp, apt, sub, our_addr, ts)
        self._ctpp_init_ts = ts
        _LOGGER.info("Shared CTPP opened for VIP events (%s, ts=0x%08X)", our_addr, ts)
        return ts

    def _start_keepalive(self) -> None:
        """(Re)start the periodic keepalive loop.

        A *background* task so HA's startup bootstrap doesn't wait on this
        never-ending loop (a tracked task makes bootstrap time out with a
        "blocking startup" warning before moving on).
        """
        self._cancel_keepalive()
        self._keepalive_task = self.entry.async_create_background_task(
            self.hass, self._keepalive_loop(), "comelit-keepalive"
        )

    def _cancel_keepalive(self) -> None:
        if self._keepalive_task is not None and not self._keepalive_task.done():
            self._keepalive_task.cancel()
        self._keepalive_task = None

    async def _keepalive_loop(self) -> None:
        """Ping the panel with a benign server-info query every _KEEPALIVE_INTERVAL.

        The panel replies, resetting the receive-loop idle timer, so the shared
        connection stays up instead of churning a reconnect every idle cycle.
        Skipped while a video/inbound session is active (media already keeps the
        socket busy, and we avoid opening a channel mid-call). Failures are left
        to the receive-loop / disconnect callback to turn into a reconnect.
        """
        while True:
            await asyncio.sleep(_KEEPALIVE_INTERVAL)
            client = self._shared_client
            if client is None or not client.connected:
                return
            if self.stream.session_active:
                continue
            try:
                async with self._ctpp_lock:
                    await asyncio.wait_for(client.get_server_info(), timeout=10.0)
                _LOGGER.debug("Keepalive OK")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Keepalive failed — connection may be dead", exc_info=True)

    def _on_shared_disconnect(self) -> None:
        """Called by the shared client when its TCP connection drops.

        Schedules a reconnect: re-auth → re-open CTPP → restart listener.
        """
        if self._shared_client is None:
            return
        _LOGGER.debug("Shared connection lost — scheduling reconnect")
        self.hass.async_create_task(self._reconnect_shared())

    async def _reconnect_shared(self) -> None:
        """Tear down and re-establish the shared connection + CTPP + listener."""
        if self._reconnecting:
            return
        self._reconnecting = True
        self._cancel_keepalive()
        try:
            # Stop the video session first — it holds a reference to the dead
            # client and would otherwise hang waiting on the dead socket.
            with contextlib.suppress(Exception):
                await self.stream.async_stop_for_reconnect()
            # Detach the listener (leaves nothing on the dead client).
            if self.events_manager is not None:
                with contextlib.suppress(Exception):
                    await self.events_manager.async_detach_local()

            old = self._shared_client
            self._shared_client = None
            if old is not None:
                with contextlib.suppress(Exception):
                    await old.disconnect()

            # Retry connect a few times — the device may still be waking up.
            for attempt in range(4):
                try:
                    await self._connect_shared()
                    _LOGGER.info("Shared connection re-established")
                    return
                except Exception as err:  # noqa: BLE001
                    if attempt >= 3:
                        _LOGGER.warning("Shared reconnect failed: %s", err)
                        return
                    await asyncio.sleep(2)
        finally:
            self._reconnecting = False

    async def async_stop_shared(self) -> None:
        """Disconnect the shared client (on unload)."""
        self._cancel_keepalive()
        if self.events_manager is not None:
            with contextlib.suppress(Exception):
                await self.events_manager.async_detach_local()
        client = self._shared_client
        self._shared_client = None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.disconnect()

    async def async_open_door(self, door_name: str) -> None:
        """Open a specific door."""
        # Create a separate client instance for door operations
        # to avoid interfering with the coordinator's update cycle
        door_client = IconaBridgeClient(self.host, self.port)
        try:
            await door_client.connect()

            # Authenticate
            auth_code = await door_client.authenticate(self.token)
            if auth_code != 200:
                raise Exception(f"Authentication failed with code {auth_code}")

            # Find the door
            doors = self.data.get("doors", [])
            door = next((d for d in doors if d.get("name") == door_name), None)
            if not door:
                raise Exception(f"Door '{door_name}' not found")

            # Open the door
            await door_client.open_door(self.vip_config, door)

        except Exception as err:
            _LOGGER.error("Error opening door %s: %s", door_name, err)
            raise
        finally:
            # Always clean up the door client connection
            await door_client.shutdown()

    async def async_open_actuator(self, actuator_name: str) -> None:
        """Trigger a specific actuator (gate/barrier)."""
        # Separate client instance, like door operations
        actuator_client = IconaBridgeClient(self.host, self.port)
        try:
            await actuator_client.connect()

            auth_code = await actuator_client.authenticate(self.token)
            if auth_code != 200:
                raise Exception(f"Authentication failed with code {auth_code}")

            actuators = self.data.get("actuators", [])
            actuator = next(
                (a for a in actuators if a.get("name") == actuator_name), None
            )
            if not actuator:
                raise Exception(f"Actuator '{actuator_name}' not found")

            await actuator_client.open_actuator(self.vip_config, actuator)

        except Exception as err:
            _LOGGER.error("Error opening actuator %s: %s", actuator_name, err)
            raise
        finally:
            await actuator_client.shutdown()
