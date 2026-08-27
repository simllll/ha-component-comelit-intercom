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
> cloud fallback, a camera, a dedicated-identity setup, DHCP discovery and more.

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
- 🎥 **Entrance camera** — live video plus stills, decoded locally from the
  intercom's own H.264 video, with the entrance's audio on the WebRTC view. The
  still **refreshes automatically on that entrance's ring**, so automations can
  attach a fresh image to a notification.
- 🎙️ **Two-way audio (talk-back)** — hear the entrance and talk back from the
  browser over go2rtc's WebRTC. Answer an incoming call automatically
  (`Auto-answer`) or with the **Answer doorbell** button, then use the mic
  button on a WebRTC card. Opt-in; off by default.
- 🔑 **Dedicated identity** — use a Home Assistant user paired via the app so it
  doesn't clash with your phone or the wall monitor (needed for local events).
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

Enter the IP address and leave the rest as-is — that's it. With no token given,
Home Assistant **automatically creates its own dedicated user** on the device
and activates it **entirely locally** (no Comelit cloud, no app). This needs the
device web password (factory default `comelit`); change the field if you set a
custom one.

Because Home Assistant gets its **own identity** (its own ViP sub-address), it
can hold cloud-free **local** doorbell events without clashing with the wall
monitor or stealing a phone's notifications. Re-running setup reuses the same
user instead of creating duplicates.

Advanced alternatives:

- **Dedicated user by name/email** — if you'd rather pair a user yourself in the
  Comelit app, enter its name or email; Home Assistant reads *that* user's token
  from a device backup instead of creating one.
- **Token** — paste an existing 32-char user token directly.

### Re-authenticating / changing the token

If the token stops working, Home Assistant prompts you to **re-authenticate** —
leave the token blank to auto-provision a fresh user, or paste a new one; no
reinstall needed. You can also open the integration's **Reconfigure** dialog at
any time to change the IP or view/edit the current token.

> **Fully local.** The integration mints its token on the LAN by generating an
> activation code in the device's web UI and redeeming it on the ICONA bridge —
> the same handshake the app uses, minus the cloud round-trip. Everything the
> integration does (control, local events, camera) stays local.

## Entities

| Entity | Type | Notes |
|--------|------|-------|
| Door / gate | `lock` (open) | One per door and ViP actuator |
| Doorbell (per entrance) | `event` (doorbell) | Fires `ring` / `missed_call` |
| Floor call | `event` (doorbell) | The apartment's own station ("Etagen") |
| Entrance camera | `camera` | Live video (on-demand) + stills; still refreshes on that entrance's ring |
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

## Camera & video

The entrance `camera` provides both a **live feed** and **stills**, decoded
locally from the intercom's H.264 video:

- **Live feed is on-demand.** It starts automatically when you open the camera's
  live view (Home Assistant connects to a local RTSP stream the integration
  serves) and stops on its own a short time after you stop watching. There is no
  manual on/off — just open or close the camera. The intercom serves only one
  video call at a time.
- **Stills refresh on ring.** When that entrance rings, the camera pulls a fresh
  snapshot automatically, so an automation can attach a current image to a push
  notification. You can also request a still any time (e.g. `camera.snapshot`);
  it's taken from a short video call to the panel.

### Audio & two-way talk-back

Audio is carried as G.711 (PCMA) and only survives the **WebRTC** stream — HLS
drops it. Home Assistant's built-in **go2rtc** relays it to the browser, so make
sure the camera plays over WebRTC (a WebRTC/Picture card, or the more-info
dialog on a recent HA).

- **Hear the entrance** works on the plain live view (best-effort; some models
  only send audio once a call is answered).
- **Talk back** needs an **answered call**: enable **Auto-answer** in the options
  (or press the **Answer doorbell** button while it's ringing). Then the mic
  button appears on the WebRTC card and your voice is sent to the entrance over
  go2rtc's ONVIF backchannel. The browser only grants microphone access on a
  **secure (HTTPS) origin**.

Example — notify with a snapshot on ring:

```yaml
automation:
  - alias: Doorbell push with snapshot
    trigger:
      - platform: event
        event_type: comelit_intercom_doorbell
    action:
      - service: notify.mobile_app_your_phone
        data:
          message: "Someone's at the door"
          data:
            image: /api/camera_proxy/camera.comelit_intercom_entrance
```

## Options

Integration → **Configure**:
- **Doorbell ring notifications** — enable/disable.
- **Enable audio** — advertise the entrance audio track on the stream (on by
  default). Turn off if a client has trouble with the G.711 audio.
- **Auto-answer doorbell** — automatically answer an incoming call so two-way
  audio (talk-back) is available. Experimental, off by default; on shared /
  multi-unit systems it can affect other units.
- **Verbose debug logging** — log protocol/video/audio internals for bug reports.
- **Push identity token** — advanced: enroll cloud push under a different token.

## Limitations

- **Local events need a dedicated identity** — created automatically at setup
  (or supplied by you). If it can't be held, events use cloud fallback (needs
  internet on the intercom and HA).
- **No door/gate open-state** — the openers are momentary relay pulses with no
  state feedback, hence `lock` entities that "open".
- **One video call at a time** — the intercom serves a single call, so live view
  and stills share it. Continuous live view may occasionally drop and reconnect.
- **Audio needs WebRTC** — the entrance audio and talk-back only work on the
  WebRTC stream (via go2rtc); HLS players show video only. Talk-back also needs
  an answered call (auto-answer or the Answer button) and an HTTPS origin for the
  browser mic.

## Credits

- [nicolas-fricke/ha-component-comelit-intercom](https://github.com/nicolas-fricke/ha-component-comelit-intercom) — the original integration this is built upon.
- [antoiba86/hass-comelit-intercom-local](https://github.com/antoiba86/hass-comelit-intercom-local) — local video stack reference.
- [madchicken/comelit-client](https://github.com/madchicken/comelit-client) — ICONA Bridge protocol reference.

## License

See [LICENSE](LICENSE).
