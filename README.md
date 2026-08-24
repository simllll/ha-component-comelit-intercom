# Comelit ICONA Intercom for Home Assistant

A fully-featured, **local-first** Home Assistant integration for Comelit ViP
intercoms that speak the **ICONA Bridge** protocol (TCP port 64100). Open your
doors and gates, get real-time doorbell events, and pull the entrance camera —
no MQTT, no Docker, and no cloud for control (cloud is only an optional fallback
for ring notifications).

[![Validate](https://github.com/simllll/hass-comelit-icona/actions/workflows/validate.yml/badge.svg)](https://github.com/simllll/hass-comelit-icona/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)

> **Attribution.** This project began as a fork of
> [nicolas-fricke/ha-component-comelit-intercom](https://github.com/nicolas-fricke/ha-component-comelit-intercom)
> (thank you! 🙏) and also draws on
> [antoiba86/hass-comelit-intercom-local](https://github.com/antoiba86/hass-comelit-intercom-local)
> for the video stack. It is a **major rewrite** with local doorbell events,
> cloud fallback, a camera, auto-activation, DHCP discovery and more.

## Features

- 🔓 **Doors & gates** as `lock` entities (open) — every door and ViP actuator.
- 🔔 **Real-time doorbell events** — a doorbell `event` per entrance panel plus a
  **Floor call** ("Etagen") entity, with `ring` and `missed_call`.
  - **Local-first**: the integration holds a registration on the intercom and
    receives calls directly over the LAN — instant, no internet, and it knows
    **which** doorbell rang.
  - **Cloud fallback**: if a local registration can't be held, it automatically
    falls back to Comelit's cloud push (FCM). An **Events source** sensor shows
    `local` / `cloud` / `none`.
- 🎥 **Entrance camera** — on-demand snapshot (and a fresh snapshot on ring),
  decoded locally from the intercom's own H.264 video.
- 🔑 **Auto-activation** — mint a dedicated Home Assistant identity from an
  activation code during setup (no clashing with your phone or the wall monitor).
- 📈 **Sensors** — connectivity, ringing, last ring, ring count, events source.
- 🔎 **DHCP discovery**, device model/firmware/serial, and downloadable
  diagnostics (secrets redacted).

## Supported devices

Comelit ViP intercoms exposing the ICONA Bridge (port 64100). Developed and
verified against a **6742W "Mini ViP handsfree Wifi"** (firmware 2.3.1); other
ViP models that speak ICONA should work. See
[`docs/PROTOCOL.md`](docs/PROTOCOL.md) for protocol details and firmware notes.

## Installation

### HACS (recommended)

1. Install [HACS](https://hacs.xyz/).
2. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/simllll/hass-comelit-icona`, category **Integration**.
3. Search for **Comelit ICONA Intercom**, download, and restart Home Assistant.

### Manual

Copy `custom_components/comelit_intercom` into your HA `custom_components/`
directory and restart.

## Setup

Home Assistant will **auto-discover** the intercom when it joins your network
(via its Comelit MAC prefix). You can also add it manually:
Settings → Devices & Services → **Add Integration** → *Comelit ICONA Intercom*.

You'll be asked for the IP and **one** credential:

- **Activation code (recommended).** In the device web UI
  (`http://<ip>:8080/users.html`) add a user (e.g. "Home Assistant") and
  *generate an activation code*. Paste it here — the integration mints its own
  **dedicated token**. This is required for cloud-free **local** doorbell events
  (the wall-monitor token conflicts; a phone's token would stop the phone's
  notifications).
- **Token** (advanced) — paste an existing 32-char user token.
- **Leave both empty** — the integration auto-extracts the wall-monitor token
  from a device backup (default `comelit` password). Control works, but local
  events fall back to cloud.

## Entities

| Entity | Type | Notes |
|--------|------|-------|
| Door / gate | `lock` (open) | One per door and ViP actuator |
| Doorbell (per entrance) | `event` (doorbell) | Fires `ring` / `missed_call` |
| Floor call | `event` (doorbell) | The apartment's own station ("Etagen") |
| Entrance camera | `camera` | On-demand snapshot; refreshes on that entrance's ring |
| Connectivity | `binary_sensor` (connectivity) | ICONA bridge reachable |
| Ringing | `binary_sensor` (sound) | On during a ring (auto-off 30 s) |
| Last ring | `sensor` (timestamp) | Most recent ring |
| Ring count | `sensor` (total increasing) | Persisted across restarts |
| Events source | `sensor` (enum) | `local` / `cloud` / `none` |

The doorbell `event` carries `source`, `doorbell`, and `caller` attributes; a
`comelit_intercom_doorbell` bus event fires for every ring (catch-all for
automations).

## How doorbell events work

On current firmware the wall monitor receives calls over the native ViP bus,
while apps are notified via cloud push. This integration does what an app won't:
it **holds** a local registration and receives incoming calls over it — so you
get instant, cloud-free events and can tell entrance vs floor apart. If that
registration can't be held (e.g. the monitor token is in use), it transparently
falls back to cloud push. Toggle notifications and override the push identity in
the integration's **Configure** dialog.

## Options

Integration → **Configure**:
- **Doorbell ring notifications** — enable/disable.
- **Push identity token** — advanced: enroll cloud push under a different token.

## Limitations

- **Local events need a dedicated identity** (activation code); otherwise events
  use cloud fallback (needs internet on the intercom and HA).
- **No door/gate open-state** — the openers are momentary relay pulses with no
  state feedback, hence `lock` entities that "open".
- **Video is snapshot-only** for now; live streaming (RTSP → go2rtc) is planned.
  Each snapshot briefly places a video call to the entrance panel.

## Credits

- [nicolas-fricke/ha-component-comelit-intercom](https://github.com/nicolas-fricke/ha-component-comelit-intercom) — the original integration this is built upon.
- [antoiba86/hass-comelit-intercom-local](https://github.com/antoiba86/hass-comelit-intercom-local) — local video stack reference.
- [madchicken/comelit-client](https://github.com/madchicken/comelit-client) — ICONA Bridge protocol reference.

## License

See [LICENSE](LICENSE).
