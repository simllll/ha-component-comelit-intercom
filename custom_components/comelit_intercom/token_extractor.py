"""
Token extractor for Comelit devices.

Extracts user authentication tokens by creating and downloading
device configuration backups.
"""

import asyncio
import gzip
import logging
import os
import re
import tarfile
import tempfile
from pathlib import Path

import aiohttp

_LOGGER = logging.getLogger(__name__)


async def extract_token(
    host: str, password: str = "comelit", port: int = 8080, match: str | None = None
) -> str | None:
    """
    Extract authentication token from Comelit device.

    Creates a new backup on the device, downloads it, and extracts
    the user authentication token from the configuration files.
    """
    base_url = f"http://{host}:{port}"

    # The Comelit web interface uses IP-based sessions instead of cookies.
    # Once we authenticate from an IP address, all subsequent requests from
    # that IP are authorized for a period of time. This is why we don't need
    # to handle cookies or session tokens.
    timeout = aiohttp.ClientTimeout(total=60, connect=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            _LOGGER.info("Starting token extraction")

            # Step 1: Login to establish IP-based session
            # The 'l-pwd' field is the login password field name in the web interface
            login_data = {"l-pwd": password}
            login_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"{base_url}/",  # Required by the device for security
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }

            async with session.post(
                f"{base_url}/do-login.html", data=login_data, headers=login_headers
            ) as resp:
                if resp.status != 200:
                    _LOGGER.error(f"Login failed with status: {resp.status}")
                    return None

                login_content = await resp.text()

                if "Access granted" not in login_content:
                    _LOGGER.error("Login failed - check password")
                    return None

                _LOGGER.info("Login successful")

            # Step 2: Create a new backup
            # We need to create a fresh backup to ensure we get the current token
            # (in case it was changed since the last backup)
            _LOGGER.info("Creating new backup...")
            headers = {
                "X-Requested-With": "XMLHttpRequest",  # Required to trigger AJAX response
                "Referer": f"{base_url}/config-backup.html",
            }

            async with session.post(
                f"{base_url}/create-backup.html", headers=headers
            ) as resp:
                create_response = await resp.text()
                if "Backup successfully created" not in create_response:
                    _LOGGER.error(f"Backup creation failed: {create_response}")
                    return None

                _LOGGER.info("Backup created successfully")

            # Step 3: Wait for backup creation to complete
            # The device needs a moment to actually create the backup file
            await asyncio.sleep(2)

            async with session.get(f"{base_url}/config-backup.html") as resp:
                if resp.status != 200:
                    _LOGGER.error("Failed to get backup list")
                    return None

                backup_page = await resp.text()

            # Step 4: Find the latest backup
            # Backup filenames are timestamps like "1234567890.tar.gz"
            # We want the highest number (most recent timestamp)
            backup_files = re.findall(r"([0-9]+\.tar\.gz)", backup_page)
            if not backup_files:
                _LOGGER.error("No backup files found")
                return None

            # Sort numerically to get the most recent backup
            backup_files.sort()
            latest_backup = backup_files[-1]
            _LOGGER.info(f"Using latest backup: {latest_backup}")

            # Step 5: Download the backup
            async with session.get(f"{base_url}/{latest_backup}") as resp:
                if resp.status != 200:
                    _LOGGER.error(f"Failed to download backup: {resp.status}")
                    return None

                backup_data = await resp.read()
                _LOGGER.info(f"Downloaded {len(backup_data)} bytes")

            # Step 6: Extract token from backup
            return await extract_token_from_backup(backup_data, match=match)

        except Exception as e:
            _LOGGER.error(f"Error in token extraction: {e}")
            import traceback

            _LOGGER.error(traceback.format_exc())
            return None


async def extract_token_from_backup(
    backup_data: bytes, match: str | None = None
) -> str | None:
    """Extract a user token from a backup archive.

    If ``match`` is given, return the token of the user whose name or email
    contains it (case-insensitive) — used to pick a dedicated Home Assistant
    identity paired via the app. Otherwise return the first non-null token.
    """
    try:
        loop = asyncio.get_running_loop()

        def _match_user(content: str) -> str | None:
            # Each user is a line: mspUsersMap.0.N = ... 6:4:"NAME" ... 9:4:"TOKEN" ... 11:4:"EMAIL" ...
            needle = match.lower()
            for line in content.splitlines():
                if "mspUsersMap" not in line:
                    continue
                name = re.search(r'\b6:4:"([^"]*)"', line)
                token = re.search(r'\b9:4:"([a-f0-9]{32})"', line, re.IGNORECASE)
                email = re.search(r'\b11:4:"([^"]*)"', line)
                if not token or token.group(1) == "0" * 32:
                    continue
                hay = f"{name.group(1) if name else ''} {email.group(1) if email else ''}".lower()
                if needle in hay:
                    _LOGGER.info("Matched user %r -> token %s...", match, token.group(1)[:8])
                    return token.group(1)
            return None

        def _extract():
            with tempfile.TemporaryDirectory() as tmpdir:
                backup_path = Path(tmpdir) / "backup.tar.gz"
                backup_path.write_bytes(backup_data)

                # Extract tar.gz
                try:
                    with tarfile.open(backup_path, "r:gz") as tar:
                        tar.extractall(tmpdir)
                except Exception as e:
                    _LOGGER.error(f"Failed to extract backup: {e}")
                    return None

                # Find and process users.cfg which contains user configuration
                # This file is typically located in etc/comelit/ within the backup
                for root, _dirs, files in os.walk(tmpdir):
                    for file in files:
                        if file == "users.cfg":
                            file_path = Path(root) / file
                            _LOGGER.debug(f"Found {file} at: {file_path}")

                            # Some firmware versions gzip the users.cfg file even without
                            # a .gz extension. Check the magic bytes to detect this.
                            with open(file_path, "rb") as f:
                                magic = f.read(2)

                            if magic == b"\x1f\x8b":  # gzip magic number (1f 8b)
                                _LOGGER.debug("users.cfg is gzipped, decompressing...")
                                with gzip.open(file_path, "rb") as f:
                                    content = f.read().decode("utf-8", errors="ignore")
                            else:
                                content = file_path.read_text(errors="ignore")

                            _LOGGER.debug(f"users.cfg size: {len(content)} bytes")

                            # If a specific user was requested, match by name/email.
                            if match:
                                tok = _match_user(content)
                                if tok:
                                    return tok
                                _LOGGER.warning(
                                    "No user matching %r found in backup", match
                                )
                                return None

                            # The users.cfg file uses a serialized format where:
                            # - Fields are numbered (1:, 2:, etc.)
                            # - Field 9 contains the authentication token
                            # - Format is: 9:4:"TOKEN_HERE" where 4 is the field type (string)
                            # - Tokens are always 32 character hexadecimal strings
                            matches = re.findall(
                                r'9:4:"([a-f0-9]{32})"', content, re.IGNORECASE
                            )
                            if matches:
                                _LOGGER.info(f"Found {len(matches)} tokens in {file}")
                                # Return the first valid token
                                # Skip null tokens (all zeros) which indicate no user configured
                                for token in matches:
                                    if token != "00000000000000000000000000000000":
                                        _LOGGER.info(f"Extracted token: {token[:8]}...")
                                        return token

                            # Fallback: Some older firmware versions might store tokens differently
                            # Try to find any 32-character hex string as a last resort
                            hex_matches = re.findall(
                                r"\b([a-f0-9]{32})\b", content, re.IGNORECASE
                            )
                            if hex_matches:
                                _LOGGER.info(
                                    f"Found {len(hex_matches)} potential tokens via hex pattern"
                                )
                                for candidate in hex_matches:
                                    if candidate != "00000000000000000000000000000000":
                                        return candidate

                _LOGGER.error("No token found in backup")
                return None

        # Run the file extraction in a thread pool to avoid blocking the event loop
        # File I/O operations can be slow and would block async operations
        return await loop.run_in_executor(None, _extract)

    except Exception as e:
        _LOGGER.error(f"Error extracting token: {e}")
        return None
