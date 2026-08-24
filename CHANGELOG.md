# Changelog

This file is maintained automatically by
[release-please](https://github.com/googleapis/release-please) from
[Conventional Commit](https://www.conventionalcommits.org/) messages.

## [1.5.0](https://github.com/simllll/hass-comelit-icona/compare/v1.4.0...v1.5.0) (2026-08-24)


### Features

* add reauth and reconfigure flows ([#6](https://github.com/simllll/hass-comelit-icona/issues/6)) ([f5dc4b2](https://github.com/simllll/hass-comelit-icona/commit/f5dc4b2dcc496ba63c905220fb42638dd97c2ed5))
* live video stream + reliable snapshots ([#8](https://github.com/simllll/hass-comelit-icona/issues/8)) ([3a54a81](https://github.com/simllll/hass-comelit-icona/commit/3a54a8172db9071c7f6634a31bb9805abde90390))

## [1.4.0](https://github.com/simllll/hass-comelit-icona/compare/v1.3.2...v1.4.0) (2026-08-24)


### Features

* auto-provision a dedicated user with fully-local token minting ([#4](https://github.com/simllll/hass-comelit-icona/issues/4)) ([0ef6cc2](https://github.com/simllll/hass-comelit-icona/commit/0ef6cc2d31a863f4d64d3d713b685606b37028c2))

## [1.3.2](https://github.com/simllll/hass-comelit-icona/compare/v1.3.1...v1.3.2) (2026-08-24)


### Bug Fixes

* replace non-working activation-code path with dedicated-user token extraction ([bd5713b](https://github.com/simllll/hass-comelit-icona/commit/bd5713b6a33e2ffa71b99e7f5b831fe93fb58d08))

## [1.3.1](https://github.com/simllll/hass-comelit-icona/compare/v1.3.0...v1.3.1) (2026-08-24)


### Bug Fixes

* remove HTML-like &lt;ip&gt; from strings.json (hassfest translations check) ([102dd29](https://github.com/simllll/hass-comelit-icona/commit/102dd29919f2f1c63663501da44a230748736daa))

## 1.3.0 — highlights of the major rewrite

This is a substantially rewritten and expanded version of the original
[nicolas-fricke/ha-component-comelit-intercom](https://github.com/nicolas-fricke/ha-component-comelit-intercom).

- **Doors & gates** as `lock` entities (open) — doors and ViP actuators.
- **Real-time doorbell events**, one per entrance panel + a "Floor call"
  (Etagen). Local (held CTPP registration) is primary; Comelit cloud push
  (FCM) is an automatic fallback. Event types: `ring`, `missed_call`.
- **Entrance camera** — on-demand snapshot (and snapshot on ring) pulled from
  the intercom's own H.264 video, locally.
- **Auto-activation** — mint a dedicated token from an activation code in the
  config flow (no more sharing the monitor/phone identity).
- **Sensors** — connectivity, ringing, last ring, ring count, events source.
- **DHCP discovery** (Comelit OUI), device model/firmware/serial, diagnostics.
- Bundled ICONA Bridge protocol reference (`docs/PROTOCOL.md`).
