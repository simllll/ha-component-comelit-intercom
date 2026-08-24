"""
Dedicated-user provisioning for Comelit ICONA intercoms.

Creates a dedicated Home Assistant user on the device and mints its
authentication token **entirely on the local network** — no Comelit cloud and
no Comelit app required.

The flow mirrors what the app does over the LAN, reverse-engineered from a
packet capture:

1. Log into the device web UI (port 8080) with the admin password.
2. Create a user (type "Apps") in the first free slot and generate its
   single-use activation code.
3. Read that 6-character code from the user's ``.mug`` pairing file.
4. Open the ``UAUT`` channel on the ICONA bridge (port 64100) and send a
   ``user-activation`` request with the code. The device validates the code
   locally and returns a freshly minted ``user-token``.

The minted token is a full user identity (its own ViP sub-address), so Home
Assistant can hold local doorbell registrations without clashing with the wall
monitor or a paired phone.
"""

from __future__ import annotations

import asyncio
import gzip
import io
import json
import logging
import re
import struct
import tarfile

import aiohttp

from .const import DEFAULT_WEB_PASSWORD, DEFAULT_WEB_PORT, HA_USER_NAME

_LOGGER = logging.getLogger(__name__)

# users.cfg field indices used by the web UI's update.html endpoint.
_FIELD_TYPE = 5  # 1=Internal Unit, 2=Apps, 3=Phone
_FIELD_NAME = 6
_USER_TYPE_APP = 2
_NULL_TOKEN = "0" * 32

# Highest user slot to consider.
_MAX_SLOTS = 20

# ICONA bridge framing. The 2-byte magic is the literal sequence 00 06;
# the length and request-id that follow are little-endian uint16.
_ICONA_MAGIC = b"\x00\x06"
_COMMAND = 0xABCD
_UAUT_TID = 7


async def provision_dedicated_user(
    host: str,
    password: str = DEFAULT_WEB_PASSWORD,
    web_port: int = DEFAULT_WEB_PORT,
    icona_port: int = 64100,
    name: str = HA_USER_NAME,
) -> str | None:
    """Create a dedicated user on the device and mint its token locally.

    Returns the 32-character user token, or ``None`` on failure.
    """
    base_url = f"http://{host}:{web_port}"
    timeout = aiohttp.ClientTimeout(total=60, connect=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        if not await _login(session, base_url, password):
            return None

        # Read the real user table from a device backup — this is the only
        # reliable way to tell which slots are occupied (an already-activated
        # user has no pending .mug file, so probing .mug would wrongly treat it
        # as empty and OVERWRITE it).
        users = await _fetch_user_map(session, base_url)
        if users is None:
            _LOGGER.error("Could not read the device user table from a backup")
            return None

        # Reuse a previously provisioned identity if it still has a valid token.
        for slot, info in sorted(users.items()):
            if info["name"] == name and info["token"]:
                _LOGGER.info("Reusing existing %r user in slot %s", name, slot)
                return info["token"]

        slot = _find_free_slot(users)
        if slot is None:
            _LOGGER.error("No free user slot available on the device")
            return None
        _LOGGER.info("Provisioning dedicated user in free slot %s", slot)

        code = await _create_user_and_code(session, base_url, slot, name)
        if not code:
            _LOGGER.error("Failed to create user / activation code in slot %s", slot)
            return None
        _LOGGER.info("Generated activation code for %r", name)

    # Redeem the code on the ICONA bridge to mint the token (no cloud).
    try:
        token = await _local_activate(host, icona_port, code, name)
    except (OSError, asyncio.IncompleteReadError, TimeoutError) as err:
        _LOGGER.error("Local activation failed: %s", err)
        return None

    if token:
        _LOGGER.info("Minted dedicated token %s… locally", token[:8])
    return token


async def _login(
    session: aiohttp.ClientSession, base_url: str, password: str
) -> bool:
    """Establish an IP-based session with the device web UI."""
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": f"{base_url}/",
    }
    try:
        async with session.post(
            f"{base_url}/do-login.html", data={"l-pwd": password}, headers=headers
        ) as resp:
            body = await resp.text()
    except aiohttp.ClientError as err:
        _LOGGER.error("Web UI login request failed: %s", err)
        return False

    if resp.status != 200 or "Access granted" not in body:
        _LOGGER.error("Web UI login failed - check the device password")
        return False
    return True


async def _fetch_user_map(
    session: aiohttp.ClientSession, base_url: str
) -> dict[str, dict] | None:
    """Create+download a backup and parse the user table from users.cfg.

    Returns ``{"0.N": {"type": int, "name": str, "email": str, "token": str}}``
    where ``token`` is "" when the slot has no (or a null) token.
    """
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{base_url}/config-backup.html",
    }
    try:
        async with session.post(
            f"{base_url}/create-backup.html", headers=headers
        ) as resp:
            if "Backup successfully created" not in await resp.text():
                _LOGGER.error("Backup creation failed")
                return None
        await asyncio.sleep(2)  # give the device a moment to write the file

        async with session.get(f"{base_url}/config-backup.html") as resp:
            page = await resp.text()
        backups = sorted(re.findall(r"([0-9]+\.tar\.gz)", page))
        if not backups:
            _LOGGER.error("No backup file found on the device")
            return None

        async with session.get(f"{base_url}/{backups[-1]}") as resp:
            data = await resp.read()
    except aiohttp.ClientError as err:
        _LOGGER.error("Backup download failed: %s", err)
        return None

    return await asyncio.get_running_loop().run_in_executor(
        None, _parse_user_map, data
    )


def _parse_user_map(backup_data: bytes) -> dict[str, dict] | None:
    """Parse the user table out of a .tar.gz backup (runs off the event loop)."""
    try:
        with tarfile.open(fileobj=io.BytesIO(backup_data), mode="r:gz") as tar:
            member = next(
                (m for m in tar.getmembers() if m.name.endswith("users.cfg")), None
            )
            if member is None:
                return None
            raw = tar.extractfile(member).read()
    except (tarfile.TarError, OSError) as err:
        _LOGGER.error("Failed to read backup archive: %s", err)
        return None

    if raw[:2] == b"\x1f\x8b":  # some firmware gzips users.cfg
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8", errors="ignore")

    users: dict[str, dict] = {}
    for line in text.splitlines():
        m = re.search(r"mspUsersMap\.(\d+\.\d+)", line)
        if not m:
            continue
        typ = re.search(r"\b5:\d+:(\d+)", line)
        name = re.search(r'\b6:4:"([^"]*)"', line)
        email = re.search(r'\b11:4:"([^"]*)"', line)
        token = re.search(r'\b9:4:"([a-f0-9]{32})"', line, re.IGNORECASE)
        tok = token.group(1) if token else ""
        users[m.group(1)] = {
            "type": int(typ.group(1)) if typ else 0,
            "name": name.group(1) if name else "",
            "email": email.group(1) if email else "",
            "token": "" if tok == _NULL_TOKEN else tok,
        }
    return users


def _find_free_slot(users: dict[str, dict]) -> str | None:
    """Return the first genuinely-empty slot (type 0, no name, no token).

    Slot 0 (the wall monitor) is never returned.
    """
    for n in range(1, _MAX_SLOTS):
        slot = f"0.{n}"
        info = users.get(slot)
        if info is None:
            # Slot absent from the table entirely — treat as free.
            return slot
        if info["type"] == 0 and not info["name"] and not info["token"]:
            return slot
    return None


async def _create_user_and_code(
    session: aiohttp.ClientSession, base_url: str, slot: str, name: str
) -> str | None:
    """Create an app-type user in ``slot`` and return its activation code."""
    headers = {"Referer": f"{base_url}/"}

    async def _update(field: int, value: str) -> None:
        url = f"{base_url}/update.html?mspUsersMap_.{slot}_{field}={value}"
        async with session.post(url, headers=headers):
            pass

    try:
        await _update(_FIELD_TYPE, str(_USER_TYPE_APP))
        await _update(_FIELD_NAME, name.replace(" ", "%20"))
        async with session.post(
            f"{base_url}/create-actcode.html?user={slot}", headers=headers
        ):
            pass
    except aiohttp.ClientError as err:
        _LOGGER.error("Failed to create user in slot %s: %s", slot, err)
        return None

    # The generated code is exposed in the slot's .mug pairing file.
    try:
        async with session.get(
            f"{base_url}/user-file.mug?user={slot}", headers=headers
        ) as resp:
            data = await resp.read()
    except aiohttp.ClientError as err:
        _LOGGER.error("Failed to read activation code for slot %s: %s", slot, err)
        return None
    if data[:1] != b"{":
        return None
    try:
        return json.loads(data).get("activation-code")
    except ValueError:
        return None


# --- ICONA bridge helpers -------------------------------------------------


def _hdr(body_len: int, req_id: int) -> bytes:
    return _ICONA_MAGIC + struct.pack("<HH", body_len, req_id) + b"\x00\x00"


def _channel_open(name: str, tid: int, req_id: int) -> bytes:
    body = (
        struct.pack("<HH", _COMMAND, 1)
        + struct.pack("<I", tid)
        + name.encode()
        + struct.pack("<H", req_id)
        + b"\x00"
    )
    return _hdr(len(body), 0) + body


def _json_msg(req_id: int, obj: dict) -> bytes:
    payload = json.dumps(obj, separators=(",", ":")).encode() + b"\n"
    return _hdr(len(payload), req_id) + payload


async def _read_frame(reader: asyncio.StreamReader, timeout: float = 8.0) -> bytes:
    header = await asyncio.wait_for(reader.readexactly(8), timeout)
    body_len = struct.unpack("<H", header[2:4])[0]
    if not body_len:
        return b""
    return await asyncio.wait_for(reader.readexactly(body_len), timeout)


async def _local_activate(
    host: str, port: int, code: str, description: str
) -> str | None:
    """Redeem an activation code on the UAUT channel and return the minted token."""
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(_channel_open("UAUT", _UAUT_TID, 0x0001))
        await writer.drain()
        open_ack = await _read_frame(reader)
        # The channel id to use for messages is echoed in the open response.
        chan_id = (
            struct.unpack("<H", open_ack[8:10])[0] if len(open_ack) >= 10 else 0x0001
        )

        writer.write(
            _json_msg(
                chan_id,
                {
                    "message": "user-activation",
                    "activation-code": code,
                    "description": description,
                    "message-type": "request",
                    "message-id": 1,
                },
            )
        )
        await writer.drain()

        # Read a few frames until we see the activation response.
        for _ in range(4):
            frame = await _read_frame(reader)
            idx = frame.find(b"{")
            if idx < 0:
                continue
            try:
                msg = json.loads(frame[idx:])
            except ValueError:
                continue
            if msg.get("message") != "user-activation":
                continue
            if msg.get("response-code") == 200:
                return msg.get("user-token")
            _LOGGER.error(
                "Device rejected activation code (%s): %s",
                msg.get("response-code"),
                msg.get("response-string"),
            )
            return None
        return None
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
