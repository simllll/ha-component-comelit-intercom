# Changelog

This file is maintained automatically by
[release-please](https://github.com/googleapis/release-please) from
[Conventional Commit](https://www.conventionalcommits.org/) messages.

## [1.11.1](https://github.com/simllll/hass-comelit-icona/compare/v1.11.0...v1.11.1) (2026-08-27)


### Bug Fixes

* gate mic-backchannel SDP behind auto_answer (unbreaks 1.11.0 video) ([#55](https://github.com/simllll/hass-comelit-icona/issues/55)) ([bfc532d](https://github.com/simllll/hass-comelit-icona/commit/bfc532df9369ab59eb0cdc3296a39d1d152b7535))

## [1.11.0](https://github.com/simllll/hass-comelit-icona/compare/v1.10.1...v1.11.0) (2026-08-27)


### Features

* inbound call answer + two-way audio (ported from mnestrud fork) ([#51](https://github.com/simllll/hass-comelit-icona/issues/51)) ([55502fe](https://github.com/simllll/hass-comelit-icona/commit/55502fe7935e45d1198763ee997f734ab75c58f6))


### Bug Fixes

* peer/TAP door opening for 1456S (opendoor-action "peer") ([#52](https://github.com/simllll/hass-comelit-icona/issues/52)) ([22d2207](https://github.com/simllll/hass-comelit-icona/commit/22d2207cf0a269b20eabde6c1b3e10b21a880eb3))
* resolve renewal-ACK addresses from the message, not config ([#54](https://github.com/simllll/hass-comelit-icona/issues/54)) ([c65f6dc](https://github.com/simllll/hass-comelit-icona/commit/c65f6dcb0de7df040e5ec9734a6fdfa9bcf5fcc0))

## [1.10.1](https://github.com/simllll/hass-comelit-icona/compare/v1.10.0...v1.10.1) (2026-08-25)


### Bug Fixes

* distinguish 6741W floor call via the origin tag (issue [#45](https://github.com/simllll/hass-comelit-icona/issues/45)) ([#46](https://github.com/simllll/hass-comelit-icona/issues/46)) ([f3fdf04](https://github.com/simllll/hass-comelit-icona/commit/f3fdf04c5e88f39a5e11b6d08cee061709b27681))

## [1.10.0](https://github.com/simllll/hass-comelit-icona/compare/v1.9.3...v1.10.0) (2026-08-25)


### Features

* add an option to enable/disable the audio stream ([#40](https://github.com/simllll/hass-comelit-icona/issues/40)) ([aba387c](https://github.com/simllll/hass-comelit-icona/commit/aba387c9c148538ecd7355f6ddff0e0f6471f3fc))


### Bug Fixes

* forward rings that arrive during an active video/snapshot call ([#43](https://github.com/simllll/hass-comelit-icona/issues/43)) ([8491a1e](https://github.com/simllll/hass-comelit-icona/commit/8491a1edc7ba121569e8ee13dafc7807997b84ad))
* stop injecting silence into mid-call audio gaps (clicks) ([#42](https://github.com/simllll/hass-comelit-icona/issues/42)) ([32bcd59](https://github.com/simllll/hass-comelit-icona/commit/32bcd59dea498fe7442ae50e2cf976a027e35dd3))

## [1.9.3](https://github.com/simllll/hass-comelit-icona/compare/v1.9.2...v1.9.3) (2026-08-25)


### Bug Fixes

* run the audio feed loop so entrance PCMA reaches clients ([#38](https://github.com/simllll/hass-comelit-icona/issues/38)) ([3f0a2a2](https://github.com/simllll/hass-comelit-icona/commit/3f0a2a237b3a52116caa26dfc1502a4f68a0d300))

## [1.9.2](https://github.com/simllll/hass-comelit-icona/compare/v1.9.1...v1.9.2) (2026-08-25)


### Bug Fixes

* advertise the PCMA audio track in the RTSP SDP ([#36](https://github.com/simllll/hass-comelit-icona/issues/36)) ([beacd56](https://github.com/simllll/hass-comelit-icona/commit/beacd56617131949fde46ea05e14803dbe9338b7))

## [1.9.1](https://github.com/simllll/hass-comelit-icona/compare/v1.9.0...v1.9.1) (2026-08-25)


### Bug Fixes

* read incoming audio RTP on the RTPC1 TCP channel ([#34](https://github.com/simllll/hass-comelit-icona/issues/34)) ([ab6f14f](https://github.com/simllll/hass-comelit-icona/commit/ab6f14f3a156bae54ebd544f90eb4fe768bc1d49))

## [1.9.0](https://github.com/simllll/hass-comelit-icona/compare/v1.8.1...v1.9.0) (2026-08-25)


### Features

* add a Verbose debug logging option ([#32](https://github.com/simllll/hass-comelit-icona/issues/32)) ([6809b08](https://github.com/simllll/hass-comelit-icona/commit/6809b0832c14d9780747f62d9cea863be1e0c66a))

## [1.8.1](https://github.com/simllll/hass-comelit-icona/compare/v1.8.0...v1.8.1) (2026-08-25)


### Bug Fixes

* create the Floor call doorbell dynamically on first ring ([#30](https://github.com/simllll/hass-comelit-icona/issues/30)) ([619d850](https://github.com/simllll/hass-comelit-icona/commit/619d8509f9dd044d7322bedb7d69d534fb11ac22))

## [1.8.0](https://github.com/simllll/hass-comelit-icona/compare/v1.7.2...v1.8.0) (2026-08-25)


### Features

* receive entrance audio (RX) — accept the audio RTP request-id ([#28](https://github.com/simllll/hass-comelit-icona/issues/28)) ([7fefcdc](https://github.com/simllll/hass-comelit-icona/commit/7fefcdce9f51919cfeb68d4b149fda93614f1dd1))

## [1.7.2](https://github.com/simllll/hass-comelit-icona/compare/v1.7.1...v1.7.2) (2026-08-25)


### Bug Fixes

* don't create a Floor call event in single-house/kit mode ([#26](https://github.com/simllll/hass-comelit-icona/issues/26)) ([a6f94a6](https://github.com/simllll/hass-comelit-icona/commit/a6f94a617b1e4fc0337c63329fe903bdc856f558))

## [1.7.1](https://github.com/simllll/hass-comelit-icona/compare/v1.7.0...v1.7.1) (2026-08-25)


### Bug Fixes

* suppress false missed_call events and events-source flapping ([#24](https://github.com/simllll/hass-comelit-icona/issues/24)) ([305d6c9](https://github.com/simllll/hass-comelit-icona/commit/305d6c9d895aa0ce6f48b3de0b693f159c2e7656))

## [1.7.0](https://github.com/simllll/hass-comelit-icona/compare/v1.6.1...v1.7.0) (2026-08-24)


### Code Refactoring

* single shared connection for events + video (fix CTPP contention) ([#21](https://github.com/simllll/hass-comelit-icona/issues/21)) ([6f08468](https://github.com/simllll/hass-comelit-icona/commit/6f084684052d58cbf350e3b16834a750d3960f1f))


### Miscellaneous

* release refactor commits and cut 1.7.0 ([#22](https://github.com/simllll/hass-comelit-icona/issues/22)) ([d85e5cb](https://github.com/simllll/hass-comelit-icona/commit/d85e5cbee4e50152aa406679a87bd29d4c2f7a82))

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
