# Changelog

This file is maintained automatically by
[release-please](https://github.com/googleapis/release-please) from
[Conventional Commit](https://www.conventionalcommits.org/) messages.

## [1.6.1](https://github.com/simllll/hass-comelit-icona/compare/v1.6.0...v1.6.1) (2026-08-24)


### Bug Fixes

* single shared video call for stream + stills, recycle dead calls ([#19](https://github.com/simllll/hass-comelit-icona/issues/19)) ([7e932c1](https://github.com/simllll/hass-comelit-icona/commit/7e932c12a4644ff1de75ceea294823ef14307a7d))

## [1.6.0](https://github.com/simllll/hass-comelit-icona/compare/v1.5.1...v1.6.0) (2026-08-24)


### Features

* map MSVF model code to 6741W Mini ViP ([#15](https://github.com/simllll/hass-comelit-icona/issues/15)) ([3806909](https://github.com/simllll/hass-comelit-icona/commit/38069093318f7fbd7ae482f8b192ef179b0dd9b6))


### Bug Fixes

* live view — override stream_source (was async_stream_source) ([#16](https://github.com/simllll/hass-comelit-icona/issues/16)) ([59f178a](https://github.com/simllll/hass-comelit-icona/commit/59f178aa7a154ac3403ff97426e941c2e0879c7f))
* match doorbell caller addresses across device models ([#17](https://github.com/simllll/hass-comelit-icona/issues/17)) ([61c9a26](https://github.com/simllll/hass-comelit-icona/commit/61c9a261d17b395efd08e32f3cb80efbd5759f2f))
* persist last-ring timestamp across restarts ([#12](https://github.com/simllll/hass-comelit-icona/issues/12)) ([3012e9a](https://github.com/simllll/hass-comelit-icona/commit/3012e9a03f2b6594d0cee43f830e8ceef69449f5))

## [1.5.1](https://github.com/simllll/hass-comelit-icona/compare/v1.5.0...v1.5.1) (2026-08-24)


### Bug Fixes

* use a fresh one-shot call for snapshots ([#10](https://github.com/simllll/hass-comelit-icona/issues/10)) ([377ff04](https://github.com/simllll/hass-comelit-icona/commit/377ff04e2ada93fbe0ade0083466b138813be026))

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
