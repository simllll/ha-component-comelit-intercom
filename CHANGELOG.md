# Changelog

This file is maintained automatically by
[release-please](https://github.com/googleapis/release-please) from
[Conventional Commit](https://www.conventionalcommits.org/) messages.

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
