"""FCM push manager for Comelit doorbell/ring notifications.

Rings are delivered by Comelit's cloud via Firebase Cloud Messaging, not over
the local ICONA socket. This manager:
  1. registers an FCM token under the Comelit app's Firebase project,
  2. enrolls that token with the intercom (push-info on the PUSH channel),
  3. holds an FCM listener and turns incoming ring pushes into HA events.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .comelit_client import IconaBridgeClient
from .const import (
    CONF_PUSH_TOKEN,
    CONF_TOKEN,
    DEFAULT_PORT,
    CONF_PORT,
    CONF_HOST,
    DOMAIN,
    EVENT_DOORBELL,
    FCM_API_KEY,
    FCM_APP_ID,
    FCM_BUNDLE_ID,
    FCM_PROJECT_ID,
    FCM_SENDER_ID,
    PUSH_REENROLL_INTERVAL,
    STORAGE_KEY_FCM,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def signal_doorbell(entry_id: str) -> str:
    """Dispatcher signal fired when a ring push arrives."""
    return f"{DOMAIN}_doorbell_{entry_id}"


class ComelitPushManager:
    """Manages FCM registration, device enrollment and the ring listener."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        vip_config_provider,
        on_ring=None,
    ) -> None:
        """Initialize.

        vip_config_provider: a zero-arg callable returning the current vip
        config dict (from the coordinator), so we can read apt-address lazily.
        on_ring: optional callback(payload) — when set, ring pushes are handed
        to it (the events manager) instead of being dispatched directly here.
        """
        self.hass = hass
        self.entry = entry
        self._vip_config_provider = vip_config_provider
        self._on_ring = on_ring
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_FCM}_{entry.entry_id}"
        )
        self._client: Any | None = None  # FcmPushClient
        self._fcm_token: str | None = None
        self._cancel_reenroll = None
        self._started = False

    @property
    def host(self) -> str:
        return self.entry.data[CONF_HOST]

    @property
    def port(self) -> int:
        return self.entry.data.get(CONF_PORT, DEFAULT_PORT)

    @property
    def push_identity_token(self) -> str:
        """ICONA token whose identity the push token is enrolled under.

        Defaults to the control token; can be overridden so a paired phone
        keeps its own push registration untouched.
        """
        return self.entry.options.get(CONF_PUSH_TOKEN) or self.entry.data.get(
            CONF_PUSH_TOKEN
        ) or self.entry.data[CONF_TOKEN]

    async def async_start(self) -> None:
        """Register the FCM token, enroll it, and start the listener."""
        if self._started:
            return
        try:
            from firebase_messaging import (  # noqa: PLC0415
                FcmPushClient,
                FcmRegisterConfig,
            )
        except ImportError as err:  # pragma: no cover
            _LOGGER.error(
                "firebase-messaging not installed; ring notifications disabled: %s",
                err,
            )
            return

        creds = await self._store.async_load()

        fcm_config = FcmRegisterConfig(
            project_id=FCM_PROJECT_ID,
            app_id=FCM_APP_ID,
            api_key=FCM_API_KEY,
            messaging_sender_id=FCM_SENDER_ID,
        )
        self._client = FcmPushClient(
            self._on_notification,
            fcm_config,
            creds,
            self._on_credentials_updated,
        )

        # Google's GCM register occasionally returns PHONE_REGISTRATION_ERROR;
        # it clears on a clean retry.
        for attempt in range(1, 8):
            try:
                self._fcm_token = await self._client.checkin_or_register()
                break
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("FCM register attempt %d failed: %s", attempt, err)
                await asyncio.sleep(3)
        if not self._fcm_token:
            _LOGGER.error("Could not obtain an FCM token; ring notifications disabled")
            return

        await self._client.start()
        self._started = True
        _LOGGER.info("Comelit FCM listener started")

        await self._enroll()
        self._schedule_reenroll()

    async def async_stop(self) -> None:
        """Stop the listener and cancel the re-enroll timer."""
        if self._cancel_reenroll is not None:
            self._cancel_reenroll()
            self._cancel_reenroll = None
        if self._client is not None:
            try:
                await self._client.stop()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Error stopping FCM client: %s", err)
        self._started = False

    async def _on_credentials_updated(self, creds: dict) -> None:
        """Persist refreshed FCM credentials."""
        await self._store.async_save(creds)

    def _schedule_reenroll(self) -> None:
        self._cancel_reenroll = async_call_later(
            self.hass, PUSH_REENROLL_INTERVAL, self._handle_reenroll
        )

    @callback
    def _handle_reenroll(self, _now) -> None:
        self.hass.async_create_task(self._reenroll_and_reschedule())

    async def _reenroll_and_reschedule(self) -> None:
        await self._enroll()
        self._schedule_reenroll()

    async def _enroll(self) -> None:
        """Tell the intercom to push ring events to our FCM token."""
        if not self._fcm_token:
            return
        vip = self._vip_config_provider() or {}
        apt_address = vip.get("apt-address")
        apt_subaddress = vip.get("apt-subaddress", 0)
        if not apt_address:
            _LOGGER.warning("No apt-address yet; deferring push enrollment")
            return

        client = IconaBridgeClient(self.host, self.port)
        try:
            await client.connect()
            code = await client.authenticate(self.push_identity_token)
            if code != 200:
                _LOGGER.error("Push enroll auth failed (code %s)", code)
                return
            code = await client.register_push_token(
                self._fcm_token,
                apt_address,
                apt_subaddress,
                bundle_id=FCM_BUNDLE_ID,
            )
            if code == 200:
                _LOGGER.info("Push token enrolled with intercom")
            else:
                _LOGGER.error("Push enroll returned code %s", code)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Push enrollment failed: %s", err)
        finally:
            await client.shutdown()

    def _on_notification(
        self, notification: dict, persistent_id: str, context: Any
    ) -> None:
        """FCM callback (runs in the event loop). Parse and dispatch a ring."""
        try:
            data = notification.get("data", {}) if isinstance(notification, dict) else {}
            event = data.get("event")
            if event != "incoming-event":
                _LOGGER.debug("Ignoring FCM event %s", event)
                return

            payload: dict[str, Any] = {"persistent_id": persistent_id}
            # Inner "data" is a JSON string with call-id + connection-info.
            raw = data.get("data")
            if isinstance(raw, str):
                try:
                    inner = json.loads(raw)
                    payload["call_id"] = inner.get("call-id")
                    payload["connection_info"] = inner.get("connection-info")
                except json.JSONDecodeError:
                    pass
            # Human-readable notification (title/body).
            note = data.get("notification")
            if isinstance(note, str):
                try:
                    payload["notification"] = json.loads(note)
                except json.JSONDecodeError:
                    payload["notification"] = {"body": note}

            _LOGGER.info("Doorbell ring received (call_id=%s)", payload.get("call_id"))
            payload["source"] = "cloud"
            payload.setdefault("event_type", "ring")
            if self._on_ring is not None:
                self._on_ring(payload)
            else:
                self.hass.bus.async_fire(EVENT_DOORBELL, payload)
                async_dispatcher_send(
                    self.hass, signal_doorbell(self.entry.entry_id), payload
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Error handling FCM notification: %s", err)
