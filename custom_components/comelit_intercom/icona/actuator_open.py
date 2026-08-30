"""Actuator (gate/barrier) open frames, for sending over the shared held CTPP.

Standalone actuator opens historically ran on a *second, short-lived*
connection that registers its own CTPP on the same ViP identity as the
coordinator's persistent shared CTPP. The panel allows only ONE CTPP
registration per identity, so that extra registration makes it reset the
shared connection on every press — connection churn, unreliable opens, and
disrupted rings (observed on the 6742W: each Schranke press → "Shared
connection lost — scheduling reconnect" → reconnect).

Sending the actuator frames on the already-registered shared CTPP avoids the
second registration entirely. The byte layout mirrors
``comelit_client.open_actuator`` (the 0x45 0xbe family) exactly; only the
transport differs (shared channel vs. a fresh connection). The bodies are
returned without a channel header — ``IconaBridgeClient.send_binary()`` adds it.
"""

from __future__ import annotations

_NULL = b"\x00"


def _nt(s: str) -> bytes:
    """ASCII, null-terminated (matches comelit_client._string_to_buffer(..., True))."""
    return s.encode("ascii") + _NULL


def build_actuator_open_frames(vip: dict, actuator_item: dict) -> tuple[bytes, bytes, bytes]:
    """Return ``(init, open_cmd, confirm)`` CTPP frame bodies for an actuator open."""
    apt = str(vip["apt-address"])
    out = actuator_item["output-index"]
    act_apt = str(actuator_item["apt-address"])

    # Trailer shared by all three frames: "<apt><out>\0" + "<act_apt>\0" + "\0".
    tail = _nt(f"{apt}{out}") + _nt(act_apt) + _NULL

    init = (
        bytes([0xC0, 0x18, 0x45, 0xBE])  # actuator init (vs 0x5c/0x70 for doors)
        + bytes([0x8F, 0x5C, 0x00, 0x04])
        + bytes([0x00, 0x20, 0xFF, 0x01])
        + bytes([0xFF, 0xFF, 0xFF, 0xFF])  # broadcast/wildcard
        + tail
    )

    def _cmd(confirm: bool) -> bytes:
        # 0x00 = OPEN, 0x20 = CONFIRM (both required).
        return (
            bytes([0x20 if confirm else 0x00, 0x18, 0x45, 0xBE])
            + bytes([0x8F, 0x5C, 0x00, 0x04])
            + bytes([0xFF, 0xFF, 0xFF, 0xFF])
            + tail
        )

    return init, _cmd(False), _cmd(True)
