"""Peer/TAP door-open frames (Comelit 1456S / 6741W ``opendoor-action: peer``).

These are built as raw CTPP frame *bodies* so they can be sent over the
coordinator's SHARED, already-registered CTPP channel via
``IconaBridgeClient.send_binary()`` — instead of the legacy path, which opens a
second, short-lived CTPP registration on the same ViP identity.

On some firmware (notably the 6741W / MSVF, see issue #64) that ephemeral peer
registration leaves stale device-side state: the first door open works, but
every subsequent open is reset by the device (``[Errno 32] Broken pipe``) until
the integration is reloaded. Reusing the one persistent CTPP registration
avoids creating that transient state at all — the same one-CTPP-per-identity
principle the shared-connection design is built on.

The frame layout mirrors ``comelit_client._open_door_peer_tap`` /
``_create_tap_packet`` exactly (verified against the 1456S in PR #52); only the
transport differs (shared channel vs. a fresh connection).
"""

from __future__ import annotations

import struct

# CTPP message opcodes (same values as comelit_client.MessageType).
_OPEN_DOOR_INIT = 0x18C0
_OPEN_DOOR = 0x1800
_OPEN_DOOR_CONFIRM = 0x1820


def _addr10(addr: str) -> bytes:
    """Encode a VIP address as the 10-byte null-padded form TAP frames use."""
    raw = str(addr).encode("ascii", errors="strict")
    if len(raw) > 10:
        raise ValueError(f"VIP address too long: {addr!r}")
    return raw.ljust(10, b"\x00")[:10]


def _tap_body(opcode: int, token: bytes, payload: bytes, dst: str, src: str) -> bytes:
    """Build a single TAP-framed CTPP body (no channel header — send_binary adds it)."""
    if len(token) != 4:
        raise ValueError("TAP token must be 4 bytes")
    payload_len = len(payload)
    pad = (4 - (payload_len % 4)) % 4

    body = bytearray()
    body += struct.pack("<H", int(opcode) & 0xFFFF)
    body += token
    body += (payload_len & 0x7FF).to_bytes(2, "big")
    body += payload
    if pad:
        body += b"\x00" * pad
    body += b"\xff\xff\xff\xff"
    body += _addr10(dst)
    body += _addr10(src)
    return bytes(body)


def build_peer_open_frames(
    vip: dict, door_item: dict, start_token: int, reg_cid: int
) -> tuple[bytes, list[bytes]]:
    """Return ``(reg_frame, door_frames)`` TAP bodies for a peer/TAP door open.

    Mirrors ``comelit_client._open_door_peer_tap`` step-for-step, minus the
    channel open/close and connection setup — the caller sends these on an
    existing CTPP channel. ``start_token`` seeds the monotonic TAP token and
    ``reg_cid`` is the 16-bit registration correlation id (both supplied by the
    caller so this module stays free of global/random state).
    """
    vip_base = str(vip["apt-address"])
    apt_full = f"{vip_base}{vip.get('apt-subaddress', '')}"
    door_addr = str(door_item["apt-address"])
    output_index = int(door_item["output-index"])
    dst_addr = f"{vip_base}{output_index}"

    tok = start_token & 0xFFFFFFFF

    def next_tok() -> bytes:
        nonlocal tok
        tok = (tok + 1) & 0xFFFFFFFF
        return struct.pack("<I", tok)

    reg_payload = (
        b"\x00\x40"
        + struct.pack("<H", reg_cid & 0xFFFF)
        + _addr10(apt_full)
        + struct.pack("<H", 0x0E10)
        + b"\x00"
    )
    reg_frame = _tap_body(_OPEN_DOOR_INIT, next_tok(), reg_payload, apt_full, vip_base)

    op_payload = b"\x00\x2d" + _addr10(door_addr) + bytes([output_index])
    token_door = next_tok()
    token_init = next_tok()
    door_frames = [
        _tap_body(_OPEN_DOOR, token_door, b"", dst_addr, door_addr),
        _tap_body(_OPEN_DOOR_CONFIRM, token_door, b"", dst_addr, door_addr),
        _tap_body(_OPEN_DOOR_INIT, token_init, op_payload, dst_addr, door_addr),
        _tap_body(_OPEN_DOOR, token_door, b"", dst_addr, door_addr),
        _tap_body(_OPEN_DOOR_CONFIRM, token_door, b"", dst_addr, door_addr),
    ]
    return reg_frame, door_frames
