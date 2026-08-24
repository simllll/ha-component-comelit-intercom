"""Local doorbell events via a held ICONA CTPP registration.

The intercom delivers incoming calls (doorbell rings) over a persistently
registered CTPP channel — no cloud needed. This holds that registration,
answers the device's renewals, and turns incoming call-init frames into ring
callbacks. Reverse-engineered/verified live against a 6742W (fw 2.3.1).

Key facts (verified):
  * CTPP is opened with the apartment's full address = apt-address + apt-subaddress
    (the subaddress must match the authenticated identity, e.g. "00000B061").
  * The device replies 0x1800 (ACK) + 0x1860/0x0010 (registration renewal).
  * We must answer every renewal with a 0x1800 + 0x1820 ACK pair whose timestamp
    is our init timestamp + 0x01010000.
  * A ring arrives as a 0x18C0 (call-init, action 0x0028) or 0x1860/0x0001
    (IN_ALERTING) frame; the caller VIP address is embedded and identifies which
    entrance/panel rang.
"""

from __future__ import annotations

import asyncio
import logging
import re
import struct
import time
from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

# Channel wire type IDs (device-specific, not the JSON message-ids).
_CH_UAUT = 7
_CH_CTPP = 16
_MSG_COMMAND = 0xABCD
_MSG_END = 0x01EF

# CTPP VIP frame prefixes.
_PFX_ACK = 0x1800
_PFX_CONFIRM = 0x1820
_PFX_CALL = 0x1840
_PFX_VIP = 0x1860
_PFX_CALL_INIT = 0x18C0

# Actions.
_ACT_IN_ALERTING = 0x0001
_ACT_RENEWAL = 0x0010
_ACT_CALL_INIT = 0x0028

# ACK timestamp offset (both sub-counters increment) — PCAP/live verified.
_ACK_TS_INCR = 0x01010000

_CTPP_FLAGS1 = b"\x00\x11"
_CTPP_FLAGS2 = b"\x00\x40"
_CTPP_SEP = b"\x10\x0e"

# Connection/hold tuning.
_READ_IDLE_TIMEOUT = 300  # device is quiet between renewals; don't self-kill
_RECONNECT_BACKOFF = 5
# A registration must hold this long to count as "good"; shorter = a flapping
# registration (e.g. identity conflict with the physical monitor) → treated as
# a failure so the manager can fall back to cloud.
_STABLE_SECONDS = 15

# States surfaced to HA.
STATE_CONNECTING = "connecting"
STATE_REGISTERED = "registered"
STATE_FAILED = "failed"
STATE_STOPPED = "stopped"


def _hdr(body_len: int, request_id: int) -> bytes:
    return b"\x00\x06" + struct.pack("<H", body_len) + struct.pack("<H", request_id) + b"\x00\x00"


def _null(s: str) -> bytes:
    return s.encode("ascii") + b"\x00"


def _channel_open(name: str, type_id: int, request_id: int, extra: str | None) -> bytes:
    body = struct.pack("<HH", _MSG_COMMAND, 1)
    body += struct.pack("<I", type_id)
    body += name.encode("ascii")
    body += struct.pack("<H", request_id)
    body += b"\x00"
    if extra:
        body += b"\x00"
        eb = extra.encode("ascii")
        body += struct.pack("<I", len(eb) + 1)
        body += eb + b"\x00"
    return _hdr(len(body), 0) + body


def _json(request_id: int, obj) -> bytes:
    import json

    b = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    return _hdr(len(b), request_id) + b


def _ctpp_init(apt: str, sub: int, ts: int) -> bytes:
    addr = f"{apt}{sub}"
    buf = bytearray()
    buf += struct.pack("<H", _PFX_CALL_INIT)
    buf += struct.pack("<I", ts)
    buf += _CTPP_FLAGS1 + _CTPP_FLAGS2
    buf += struct.pack("<H", ts & 0xFFFF)
    buf += _null(addr)
    buf += _CTPP_SEP
    buf += b"\x00\x00\x00\x00"
    buf += b"\xff\xff\xff\xff"
    buf += _null(addr)
    buf += _null(apt)
    buf += b"\x00"
    return bytes(buf)


def _ack(caller: str, callee: str, ts: int, prefix: int) -> bytes:
    buf = bytearray()
    buf += struct.pack("<H", prefix)
    buf += struct.pack("<I", ts)
    buf += struct.pack(">H", 0x0000)
    buf += b"\xff\xff\xff\xff"
    buf += _null(caller)
    buf += callee.encode("ascii") + b"\x00\x00"
    return bytes(buf)


_ADDR_RE = re.compile(rb"[0-9A-Fa-f]{6,9}")


def _extract_caller(body: bytes, our_apt: str) -> str | None:
    """Best-effort: first embedded VIP address that isn't our own apartment."""
    for m in _ADDR_RE.finditer(body):
        a = m.group(0).decode("ascii", "ignore")
        if a and not a.startswith(our_apt[:6]):
            return a
        # a floor call's caller may be our apt + subaddress; keep it if nothing else
    # fall back to the first address found
    m = _ADDR_RE.search(body)
    return m.group(0).decode("ascii", "ignore") if m else None


class ComelitLocalEventListener:
    """Holds a CTPP registration and emits ring callbacks."""

    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        apt_address: str,
        apt_subaddress: int,
        on_ring: Callable[[dict], None],
        on_state: Callable[[str], None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._token = token
        self._apt = apt_address
        self._sub = apt_subaddress
        self._our_addr = f"{apt_address}{apt_subaddress}"
        self._on_ring = on_ring
        self._on_state = on_state
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._req = 100
        self._init_ts = 0
        self._ack_ts = 0
        self._state = STATE_STOPPED
        self._last_fire: dict[str, float] = {}
        self._registered_at = 0.0
        # consecutive registration failures — used by the manager to fall back
        self.consecutive_failures = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def stable(self) -> bool:
        """True only if registered and it has held long enough to be trusted."""
        return (
            self._state == STATE_REGISTERED
            and self._registered_at > 0
            and (time.monotonic() - self._registered_at) >= _STABLE_SECONDS
        )

    def _set_state(self, s: str) -> None:
        if s != self._state:
            self._state = s
            if self._on_state:
                self._on_state(s)

    async def async_start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def async_stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        if self._writer:
            try:
                self._writer.close()
            except Exception:  # noqa: BLE001
                pass
        self._set_state(STATE_STOPPED)

    async def _run(self) -> None:
        while self._running:
            self._registered_at = 0.0
            try:
                self._set_state(STATE_CONNECTING)
                await self._connect_and_register()
                self._registered_at = time.monotonic()
                self._set_state(STATE_REGISTERED)
                await self._read_loop()
                # read loop returned = the socket dropped
                raise RuntimeError("connection closed")
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                held = (
                    time.monotonic() - self._registered_at if self._registered_at else 0.0
                )
                self._registered_at = 0.0
                if held >= _STABLE_SECONDS:
                    # Was a good, stable registration that later dropped — a
                    # transient blip, not a failure. Reset the failure counter.
                    self.consecutive_failures = 0
                    _LOGGER.debug("Local registration dropped after %.0fs; reconnecting", held)
                else:
                    # Never registered, or was kicked almost immediately
                    # (identity conflict) — count as a failure.
                    self.consecutive_failures += 1
                    _LOGGER.debug(
                        "Local registration failed/flapped (%d): %s",
                        self.consecutive_failures,
                        err,
                    )
                self._set_state(STATE_FAILED)
            finally:
                if self._writer:
                    try:
                        self._writer.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self._writer = None
            if self._running:
                await asyncio.sleep(_RECONNECT_BACKOFF)

    async def _send(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()

    async def _read_frame(self, timeout: float):
        header = await asyncio.wait_for(self._reader.readexactly(8), timeout=timeout)
        blen = struct.unpack("<H", header[2:4])[0]
        req = struct.unpack("<H", header[4:6])[0]
        body = await self._reader.readexactly(blen) if blen else b""
        return req, body

    async def _connect_and_register(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port), timeout=10
        )
        # UAUT auth
        self._req += 1
        await self._send(_channel_open("UAUT", _CH_UAUT, self._req, None))
        await self._read_frame(10)  # channel-open response
        await self._send(
            _json(
                self._req,
                {
                    "message": "access",
                    "user-token": self._token,
                    "message-type": "request",
                    "message-id": 2,
                },
            )
        )
        _, body = await self._read_frame(10)
        if b'"response-code":200' not in body:
            raise RuntimeError("auth failed")

        # Open CTPP with our full address; capture the server channel id.
        self._req += 1
        await self._send(_channel_open("CTPP", _CH_CTPP, self._req, self._our_addr))
        _creq, cbody = await self._read_frame(10)
        # server channel id sits in the COMMAND response body (bytes 8-10)
        self._ctpp_id = struct.unpack("<H", cbody[8:10])[0] if len(cbody) >= 10 else self._req

        # Send CTPP init and the initial ACK pair.
        self._init_ts = int(time.monotonic() * 1000) & 0xFFFFFFFF
        self._ack_ts = (self._init_ts + _ACK_TS_INCR) & 0xFFFFFFFF
        await self._send(self._frame(_ctpp_init(self._apt, self._sub, self._init_ts)))
        _LOGGER.info("Local CTPP registration sent (%s, ts=0x%08X)", self._our_addr, self._init_ts)

    def _frame(self, payload: bytes) -> bytes:
        return _hdr(len(payload), self._ctpp_id) + payload

    async def _send_ack_pair(self) -> None:
        await self._send(self._frame(_ack(self._our_addr, self._apt, self._ack_ts, _PFX_ACK)))
        await self._send(self._frame(_ack(self._our_addr, self._apt, self._ack_ts, _PFX_CONFIRM)))

    async def _read_loop(self) -> None:
        while self._running:
            try:
                req, body = await self._read_frame(_READ_IDLE_TIMEOUT)
            except (TimeoutError, asyncio.IncompleteReadError) as err:
                raise RuntimeError("connection idle/closed") from err
            if len(body) < 2:
                continue
            # Device-initiated channel END → ACK so the device can re-open.
            if req == 0 and body[:2] == struct.pack("<H", _MSG_END):
                continue
            if req == 0:
                continue
            prefix = struct.unpack("<H", body[0:2])[0]
            action = struct.unpack(">H", body[6:8])[0] if len(body) >= 8 else 0
            if prefix == _PFX_VIP and action == _ACT_RENEWAL:
                await self._send_ack_pair()
                continue
            if prefix == _PFX_CALL_INIT or (prefix == _PFX_VIP and action == _ACT_IN_ALERTING):
                # A ring. ACK it and fire.
                try:
                    await self._send_ack_pair()
                except Exception:  # noqa: BLE001
                    pass
                self._fire_event(body, "ring")
            elif prefix == _PFX_CALL and action == 0x0000:
                # 0x1840/0x0000 tail = call ended without answer → missed call.
                self._fire_event(body, "missed_call")

    def _fire_event(self, body: bytes, event_type: str) -> None:
        now = time.monotonic()
        caller = _extract_caller(body, self._apt) or ""
        # de-dup rapid retransmits of the same event
        key = f"{event_type}:{caller}"
        if now - self._last_fire.get(key, 0) < 8:
            return
        self._last_fire[key] = now
        _LOGGER.info("Local %s from %s", event_type, caller)
        try:
            self._on_ring(
                {"caller": caller, "source": "local", "event_type": event_type}
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error in local event callback")
