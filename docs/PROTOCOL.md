# Comelit ICONA Bridge protocol reference

Reverse-engineered notes for the ICONA Bridge protocol as spoken by Comelit ViP
intercoms over **TCP/UDP port 64100**. Verified live against a **6742W "Mini ViP
handsfree Wifi"** (server-info `model: MnWi`, firmware `2.3.1`). Cross-references
the community 6701W notes (antoiba86) where behaviour differs.

> This documents the *local* protocol only. It exists so the integration is
> maintainable and portable across firmware; see "Firmware differences" for why
> a heavy protocol-abstraction layer is **not** needed.

## 1. Framing

Every message is an 8-byte header + body:

```
00 06            magic (constant)
LL LL            body length   (uint16, little-endian)
RR RR            request id    (uint16, little-endian)
00 00            padding
```

- **JSON body**: starts with `{` (0x7B). UTF-8, compact.
- **Binary body**: channel-management (`request id == 0`) or VIP signalling.

## 2. Channels

Open a channel with a COMMAND packet, use it, close with END.

| Name | wire type id | purpose |
|------|:-----------:|---------|
| `UAUT` | 7  | authentication / activation |
| `UCFG` | 2  | configuration (`get-configuration`) |
| `INFO` | 20 | `server-info` |
| `CTPP` | 16 | call/door control **and local call signalling** |
| `CSPB` | 17 | secondary control (opened alongside CTPP) |
| `PUSH` | 2  | push-token enrollment |
| `UADM` | ?  | admin (create user / generate code) — needs admin auth |
| `RTPC` | — | device-initiated: RTP control for video |
| `UDPM` | — | device-initiated: UDP media negotiation for video |

Channel open (COMMAND `0xABCD`):
```
cd ab            MessageType.COMMAND (LE16)
01 00            sequence = 1 (LE16)
TT TT TT TT      channel type id (LE32)
<name ascii>     e.g. "CTPP"
RR RR            request id (LE16)
00               trailing byte
[ 00  LEN(LE32)  <extra ascii> 00 ]   optional additional-data (e.g. apt addr)
```
The device echoes the request id as the channel's server id (used as the header
`request id` for subsequent data frames on that channel). Close = END `0x01EF`.

## 3. Authentication

On `UAUT`: `{"message":"access","user-token":"<32hex>","message-type":"request","message-id":2}`
→ `{"response-code":200,"response-string":"Access Granted"}`.

## 4. Configuration

On `UCFG`: `{"message":"get-configuration","addressbooks":"all","message-type":"request","message-id":3}`.
Returns `vip.apt-address`, `vip.apt-subaddress` (per identity!), and
`vip.user-parameters.{entrance,actuator,opendoor,rtsp-camera}-address-book`.

## 5. Activation — minting a dedicated token (no admin auth)

Create a user + code in the device web UI (`http://<ip>:8080/users.html`), then on
`UAUT` (the code is the credential — **no prior auth**):
```json
{"message":"user-cloud-activation","cloud-activation-code":"<CODE>",
 "description":"Home Assistant","message-type":"request","message-id":42}
```
→ `{"response-code":200,"response-string":"Success","user-token":"<32hex>"}`.

The subaddress for the new identity is read afterwards from `get-configuration`.
(Admin messages `activate-user` / `admin-fast-activation` on `UADM` require admin
auth — not used here.)

## 6. Door / actuator open (CTPP)

Open `CTPP` (extra-data = `apt-address`+`apt-subaddress`), send the init, then
`OPEN_DOOR` (`0x1800`) / `OPEN_DOOR_CONFIRM` (`0x1820`); actuators use a
`0x18..45BE` init variant. Addresses built from `apt-address` + `output-index`.

## 7. Local doorbell events (held CTPP registration)

Hold a `CTPP` registration and the device delivers incoming calls over it — **no
cloud**. Sequence:

1. Open `CTPP` with extra-data `apt-address`+`apt-subaddress` (e.g. `00000B061`).
   **The subaddress must match the authenticated identity.**
2. Send the init (`0x18C0`, flags `0x0011 0x0040`, addresses, our init timestamp).
3. Device replies `0x1800` (ACK) then `0x1860`/action `0x0010` (registration
   renewal).
4. **Answer every renewal** with a `0x1800` + `0x1820` ACK pair whose timestamp is
   **`init_ts + 0x01010000`** (6742W). Failing this → the device retransmits and
   eventually drops.
5. Keep the socket open (the device is quiet between renewals — don't self-timeout).

VIP frame layout: `prefix(LE16) ts(LE32) action(BE16) flags(BE16) … FFFFFFFF
caller\0 callee\0\0`.

Ring/event frames (device → client):

| prefix | action | meaning |
|:------:|:------:|---------|
| `0x18C0` | `0x0028` | incoming call (ring) |
| `0x1860` | `0x0001` | IN_ALERTING (ring) |
| `0x1840` | `0x0000` | call ended unanswered (missed call) |
| `0x1860` | `0x0003` | door opened / FSM |
| `0x1860` | `0x0010` | registration renewal (answer with ACK pair) |

The **caller** VIP address in the frame identifies the source: an entrance panel
(e.g. `00000100`) vs the apartment's own floor/"Etagen" station (`apt-address` +
sub, e.g. `00000B060`).

**Addressing differs by system mode.** Apartment-block systems (e.g. 6742W,
`model: MnWi`) use plain numeric addresses (`00000100`). **Kit / single-house
mode** (e.g. 6741W, `model: MSVF`) uses an **`S` mode prefix** in the
configuration address book (`SB100001` entrance, `SB000001` apartment,
`SBIO0255` actuator), but the ring frame reports the caller **without** that
prefix (`B100001`). So caller↔address-book comparisons must tolerate a
dropped-prefix mismatch — the integration matches by equality / either-direction
prefix / either-direction suffix (`address_matches`).

> **Identity matters:** the wall-monitor token (`local-monitor-dev`) is already
> held by the physical monitor, so a duplicate registration is kicked. Use a
> dedicated app-class identity (see §5). The official app registers then closes
> and relies on push — an always-on HA client instead *holds* the registration.

## 8. Cloud push events (fallback)

`push-info` on `PUSH` enrolls a push token (`os-type`, `device-token`,
`bundle-id`, `apt-address`). The device then delivers rings via Comelit cloud →
FCM/APNS (requires internet). Payload: `event: "incoming-event"`, body
"Incoming call received", `data` with `call-id` + `connection-info`
(direct `ip:64100` + cloud mqtt/stun). Used as automatic fallback when the local
held registration can't be established.

## 9. Video (on-demand)

Video is negotiated on `CTPP` and delivered as **H.264 RTP over UDP**, wrapped in
the ICONA header: `[ICONA 8B][RTP 12B][H.264]`, payload type 99, FU-A/STAP-A/single
NALs. Sequence: `call_init 0x18C0/0x0028` → `codec 0x1840/0x0008` →
`rtpc_link 0x1840/0x000A` → `video_config 0x1840/0x001A`; the device opens `RTPC`
+ `UDPM` channels and streams UDP media (`intercom:64100 → client:<udp port>`).
Depacketise (reorder by RTP seq, reassemble FU-A) → Annex-B H.264 → 320×240.
No RTSP URL is exposed unless `rtsp-camera-address-book` is populated.

## Firmware differences (why no heavy abstraction layer)

The core protocol (framing, channels, auth, config, door open, VIP signalling,
video) is **identical** across 6701W and 6742W. Known deltas are small and
parameterisable:

| aspect | 6701W (antoiba) | 6742W (`MnWi`) |
|--------|-----------------|----------------|
| CTPP renewal ACK increment | `0x01000000` | **`0x01010000`** |
| capabilities | local | `cloudnext-device`, `push-notifications-channel`, `fast-activation-channel` |
| events | local CTPP only | local CTPP **or** cloud FCM |

Recommendation: keep one client and **parameterise the few differing constants**
(e.g. the ACK increment) rather than maintaining separate protocol
implementations. Capability-gate optional features from `server-info.capabilities`.
