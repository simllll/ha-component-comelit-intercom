"""VIP event listener — attaches to a persistent CTPP channel for ring events.

This is the cloud-free doorbell path. The Comelit device delivers incoming
calls (doorbell rings) as binary VIP messages on a persistently registered
CTPP channel. Unlike the old raw-socket ``local_events`` implementation, this
listener ATTACHES to the CTPP channel already opened and initialised on the
shared :class:`IconaBridgeClient` by the coordinator — it never opens a second
CTPP registration (two registrations on one ViP identity make the device drop
video after ~3s).

Adapted from antoiba86/hass-comelit-intercom-local's ``vip_listener.py`` with
two deliberate changes so it drops into this integration unchanged elsewhere:

  * Model-agnostic caller extraction. antoiba only parses ``SB``-prefixed
    addresses (6741W ``MSVF``). The 6742W (``MnWi``) reports purely numeric
    VIP addresses (e.g. ``00000100``), so we fall back to a generic hex
    matcher — matching the behaviour of the old ``local_events`` listener.
  * The ring callback receives a plain dict ``{caller, source, event_type}``
    (what :class:`ComelitEventsManager._handle_ring` expects) instead of a
    ``PushEvent`` dataclass.

Wire facts (verified live, unchanged from the raw-socket implementation):
  * CTPP is opened with ``apt-address + apt-subaddress`` (the subaddress must
    match the authenticated identity). The coordinator does that open + init.
  * ``0x1860/0x0010`` is the device's periodic registration renewal — we must
    answer with an ACK pair (``0x1800`` + ``0x1820``) whose timestamp is the
    coordinator's CTPP ``init_ts + 0x01010000`` (see ``ctpp._VIP_ACK_TS_INCR``).
  * A ring arrives as ``0x18C0`` (call init, action ``0x0028``) or
    ``0x1860/0x0001`` (IN_ALERTING). ``0x1840/0x0000`` is a missed call.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import struct
import time
from collections.abc import Callable

from .client import IconaBridgeClient
from .const import is_verbose_logging
from .ctpp import _VIP_ACK_TS_INCR
from .protocol import encode_call_response_ack

_LOGGER = logging.getLogger(__name__)

# CTPP prefixes sent by the device.
PREFIX_ACK = 0x1800
PREFIX_CONFIRM = 0x1820
PREFIX_VIDEO_EVENT = 0x1840
PREFIX_VIP_EVENT = 0x1860
PREFIX_CALL_INIT = 0x18C0

# VIP FSM action codes (carried in 0x1860 messages).
ACTION_IDLE = 0x0000
ACTION_IN_ALERTING = 0x0001  # incoming call / doorbell ring
ACTION_CALL_INIT = 0x0028  # action carried in 0x18C0 call-init frames
ACTION_REGISTRATION_RENEWAL = 0x0010  # device keepalive — must ACK 0x1800+0x1820

MIN_MSG_SIZE = 8

# Generic VIP address matcher — works for both numeric 6742W addresses
# (00000100) and SB-prefixed 6741W addresses (SB100001).
_ADDR_RE = re.compile(rb"(?:SB)?[0-9A-Fa-f]{6,9}")


def parse_ctpp_message(data: bytes) -> dict | None:
    """Parse a binary CTPP message into its components (model-agnostic)."""
    if len(data) < MIN_MSG_SIZE:
        return None

    prefix = struct.unpack_from("<H", data, 0)[0]
    timestamp = struct.unpack_from("<I", data, 2)[0]
    action = struct.unpack_from(">H", data, 6)[0]

    result: dict = {
        "prefix": prefix,
        "timestamp": timestamp,
        "action": action,
        "raw": data,
    }
    if len(data) >= 10:
        result["flags"] = struct.unpack_from(">H", data, 8)[0]

    addresses: list[str] = []
    for m in _ADDR_RE.finditer(data):
        addresses.append(m.group(0).decode("ascii", errors="replace"))
    result["addresses"] = addresses

    # Call-origin tag: the two ASCII bytes immediately before the 0xFFFFFFFF
    # marker. On the 6741W the floor-call ring carries the entrance panel's
    # address as the caller — byte-identical to a building-door ring — so the
    # address can't distinguish them. This tag is the only stable
    # discriminator: "PP" = entrance panel, "FF" = floor door ("fuoriporta").
    # See issue #45.
    marker = data.find(b"\xff\xff\xff\xff")
    result["call_tag"] = data[marker - 2 : marker] if marker >= 2 else None
    return result


def _extract_caller(addresses: list[str], our_apt: str) -> str:
    """Pick the caller (doorbell) address from a message's addresses.

    Prefer the first address that isn't our own apartment; fall back to the
    first address found. Mirrors the old local_events heuristic so the caller
    passed to ``address_matches`` identifies the entrance/panel that rang.
    """
    our_prefix = our_apt[:6] if our_apt else ""
    for a in addresses:
        if a and (not our_prefix or not a.upper().startswith(our_prefix.upper())):
            return a
    return addresses[0] if addresses else ""


class VipEventListener:
    """Listens for VIP ring events on the shared client's CTPP channel."""

    def __init__(
        self,
        client: IconaBridgeClient,
        apt_address: str,
        apt_subaddress: int,
        on_ring: Callable[[dict], None],
        init_ts: int,
    ) -> None:
        self._client = client
        self._apt = apt_address
        self._sub = apt_subaddress
        self._our_addr = f"{apt_address}{apt_subaddress}"
        self._on_ring = on_ring
        # All outgoing ACKs on this channel use init_ts + _VIP_ACK_TS_INCR
        # (PCAP/live-verified: never derive the ACK ts from the device's ts).
        self._init_ts = init_ts
        self._ack_ts = (init_ts + _VIP_ACK_TS_INCR) & 0xFFFFFFFF
        self._channel = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_fired: dict[str, float] = {}
        self._dedup_window = 8.0
        # A real "missed call" only follows an actual ring. 0x1840/0x0000 also
        # arrives as a video-call teardown tail and at CTPP init after a reboot;
        # those are NOT missed calls. Only emit missed_call if a ring preceded
        # it within this window.
        self._last_ring_mono = 0.0
        self._missed_window = 45.0
        self.restart_count = 0

    @property
    def running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Attach to the already-open CTPP channel and begin listening.

        The coordinator opens and initialises CTPP before calling start(); we
        only look it up and read from its response queue — no channel open, no
        init, no ACK pair here.
        """
        ctpp = self._client.get_channel("CTPP")
        if ctpp is None:
            raise RuntimeError(
                "CTPP channel not open — coordinator must open/init CTPP "
                "before starting the VIP listener"
            )
        self._channel = ctpp
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        _LOGGER.info("VIP event listener attached to CTPP (%s)", self._our_addr)

    async def stop_task(self) -> None:
        """Cancel the read loop only — LEAVE CTPP/CSPB open for video reuse."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def stop(self) -> None:
        """Stop the listener task. Channels are owned by the coordinator."""
        await self.stop_task()

    async def _listen_loop(self) -> None:
        """Read binary CTPP messages and dispatch ring events.

        Auto-restarts after unhandled exceptions, up to 5 times in 60s, then
        re-raises so the coordinator's disconnect/reconnect path takes over.
        """
        _RESTART_LIMIT = 5
        _RESTART_WINDOW = 60.0
        restart_times: list[float] = []

        while self._running:
            try:
                queue = self._channel.response_queue
                while self._running:
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=60.0)
                    except TimeoutError:
                        continue
                    await self._process_message(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                now = time.time()
                restart_times = [t for t in restart_times if now - t < _RESTART_WINDOW]
                restart_times.append(now)
                self.restart_count += 1
                _LOGGER.error(
                    "VIP listener loop crashed (restart #%d)", self.restart_count,
                    exc_info=True,
                )
                if len(restart_times) > _RESTART_LIMIT:
                    _LOGGER.error("VIP listener exceeded restart limit — escalating")
                    raise
                await asyncio.sleep(1)

    async def _process_message(self, data: bytes) -> None:
        msg = parse_ctpp_message(data)
        if msg is None:
            return
        prefix = msg["prefix"]
        action = msg["action"]
        addresses = msg["addresses"]

        if is_verbose_logging():
            _LOGGER.debug(
                "VIP msg prefix=0x%04X action=0x%04X addrs=%s",
                prefix, action, addresses,
            )

        # Device's periodic registration renewal → answer with ACK pair.
        if prefix == PREFIX_VIP_EVENT and action == ACTION_REGISTRATION_RENEWAL:
            await self._send_renewal_ack()
            return

        # Ring: 0x18C0 (call init) or 0x1860/0x0001 (IN_ALERTING).
        if prefix == PREFIX_CALL_INIT or (
            prefix == PREFIX_VIP_EVENT and action == ACTION_IN_ALERTING
        ):
            with contextlib.suppress(Exception):
                await self._send_renewal_ack()
            self._last_ring_mono = time.monotonic()
            self._fire(addresses, "ring", msg.get("call_tag"))
            return

        # Missed call: 0x1840/0x0000 — but ONLY when it follows a real ring.
        # The same frame is also emitted as a video-call teardown tail and at
        # CTPP init after a reboot; those must not fire a missed call.
        if prefix == PREFIX_VIDEO_EVENT and action == ACTION_IDLE:
            if 0 < time.monotonic() - self._last_ring_mono <= self._missed_window:
                self._last_ring_mono = 0.0
                self._fire(addresses, "missed_call")
            elif is_verbose_logging():
                _LOGGER.debug(
                    "Ignoring 0x1840/0x0000 (no preceding ring — video/CTPP tail)"
                )
            return

    async def _send_renewal_ack(self) -> None:
        """Send the ACK pair (0x1800 + 0x1820) using init_ts + 0x01010000."""
        try:
            await self._client.send_binary(
                self._channel,
                encode_call_response_ack(self._our_addr, self._apt, self._ack_ts),
            )
            await self._client.send_binary(
                self._channel,
                encode_call_response_ack(
                    self._our_addr, self._apt, self._ack_ts, prefix=PREFIX_CONFIRM
                ),
            )
            if is_verbose_logging():
                _LOGGER.debug("VIP: sent renewal ACK pair (ack_ts=0x%08X)", self._ack_ts)
        except Exception:
            _LOGGER.warning("VIP: failed to send renewal ACK", exc_info=True)

    def _fire(
        self, addresses: list[str], event_type: str, call_tag: bytes | None = None
    ) -> None:
        now = time.time()
        caller = _extract_caller(addresses, self._apt)
        # 6741W floor call: the ring carries the entrance panel's address, so
        # the only origin signal is the tag ("FF" = floor door). Report our own
        # apartment address as the caller so address_matches() routes it to the
        # "Floor call" entity instead of the entrance doorbell (issue #45).
        if call_tag == b"FF" and self._apt:
            caller = self._apt
        key = f"{event_type}:{caller}"
        if now - self._last_fired.get(key, 0.0) < self._dedup_window:
            return
        self._last_fired[key] = now
        _LOGGER.info("VIP %s from %s", event_type, caller)
        try:
            self._on_ring(
                {"caller": caller, "source": "local", "event_type": event_type}
            )
        except Exception:
            _LOGGER.exception("Error in VIP event callback")
