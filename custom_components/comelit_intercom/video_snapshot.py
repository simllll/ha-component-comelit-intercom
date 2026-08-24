"""On-demand door-camera snapshots via the ICONA ViP video call.

Negotiates a short video call to an entrance panel, collects the H.264 stream,
and decodes a JPEG (PyAV). Proven live against a 6742W.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import time

from homeassistant.core import HomeAssistant

from .icona.channels import ChannelType
from .icona.client import IconaBridgeClient
from .icona.models import DeviceConfig
from .icona.video_call import VideoCallSession

_LOGGER = logging.getLogger(__name__)

_FIRST_NAL_TIMEOUT = 12.0


def _decode_jpeg(h264: bytes) -> bytes | None:
    """Decode an Annex-B H.264 buffer to a JPEG (freshest decodable frame)."""
    import av  # noqa: PLC0415 — PyAV is bundled with HA

    codec = av.CodecContext.create("h264", "r")
    last: bytes | None = None
    for packet in codec.parse(h264):
        for frame in codec.decode(packet):
            img = frame.to_image()
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            last = buf.getvalue()
    return last


async def capture_snapshot(
    hass: HomeAssistant,
    host: str,
    port: int,
    token: str,
    apt_address: str,
    apt_subaddress: int,
    entrance_address: str,
    collect_seconds: float = 2.5,
) -> bytes | None:
    """Place a snapshot-only video call and return a JPEG (or None)."""
    client = IconaBridgeClient(host, port)
    try:
        await client.connect()
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Snapshot connect failed: %s", err)
        return None

    nals = bytearray()
    session: VideoCallSession | None = None
    try:
        ua = await client.open_channel("UAUT", ChannelType.UAUT)
        resp = await client.send_json(
            ua,
            {
                "message": "access",
                "user-token": token,
                "message-type": "request",
                "message-id": 2,
            },
        )
        if resp.get("response-code") != 200:
            _LOGGER.warning("Snapshot auth failed (code %s)", resp.get("response-code"))
            return None

        config = DeviceConfig(
            apt_address=apt_address,
            apt_subaddress=apt_subaddress,
            caller_address=entrance_address,
        )
        session = VideoCallSession(
            client, config, auto_timeout=False, snapshot_only=True
        )
        receiver = await session.start()
        # Attach our own fan-out queue so we get NALs independently of the
        # receiver's internal decode pipeline.
        nal_q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        receiver.attach_rtsp_queues(nal_q, asyncio.Queue(), None)

        deadline = time.monotonic() + collect_seconds + _FIRST_NAL_TIMEOUT
        end = None
        while time.monotonic() < deadline:
            try:
                _ts, nal = await asyncio.wait_for(nal_q.get(), 1.0)
            except TimeoutError:
                continue
            nals += b"\x00\x00\x00\x01" + nal
            if end is None:  # first NAL arrived — collect a bit more then stop
                end = time.monotonic() + collect_seconds
            elif time.monotonic() >= end:
                break
        if not nals:
            _LOGGER.warning("No video received for snapshot")
            return None
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Snapshot capture failed: %s", err)
        return None
    finally:
        if session is not None:
            with contextlib.suppress(Exception):
                await session.stop()
        with contextlib.suppress(Exception):
            await client.disconnect()

    if not nals:
        return None
    try:
        return await hass.async_add_executor_job(_decode_jpeg, bytes(nals))
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Snapshot decode failed: %s", err)
        return None
