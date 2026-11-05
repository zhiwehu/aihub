# Per-device WebSocket and OTA credentials

Approved extension: 2026-11-05. Device credentials are separate from browser,
administrator, shared legacy WS and MQTT credentials. Each random token is bound
by the administrator to a device ID (MAC IDs are normalized to lowercase). The
server stores SHA256 digests, not recoverable secrets. This authenticates possession
of the provisioned secret, not physical hardware attestation.

Use **Client connections → Device credentials** in the administrator console to
create/list/revoke credentials. The token is shown once. If device ingress is
running, creation also returns the matching OTA URL. The equivalent admin APIs:

- GET `/api/device-credentials`: ID, device ID and creation time only.
- POST `/api/device-credentials`, body `{"device_id":"aa:bb:cc:dd:ee:ff"}`: returns
  ID, device ID, token, creation time and, when available, WebSocket/OTA settings.
- DELETE `/api/device-credentials/<credential-id>`: revokes that credential and
  closes its active sockets. Recording/session shutdown follows existing behavior.

Only administrator ingress exposes these APIs. Browser client and device listeners
do not. The registry is bounded to 100 credentials; revoke obsolete or abandoned
setup credentials through the console. New credentials do not invalidate old ones:
install and verify the replacement before revoking the old credential.

New USB provisioning submits the inspected `device.mac` to the prepare API as
`device_id`, receives a fresh credential and writes it to existing NVS fields.
Wi-Fi passwords stay in the browser/device; the server receives only host and MAC.
A retry may issue another credential; unsuccessful setup does not revoke the
working credential or roll back hardware automatically. Do not rerun setup merely
to obtain the same secret: it is deliberately not recoverable from the server.

Existing firmware protocols and NVS layout are unchanged. The token is sent in the
existing WebSocket Authorization/hello field. The server ignores a different
self-declared device ID and uses the bound identity. New source instances use
`ws-device:<bound-device-id>` so credential replacement preserves device attribution.
Resume requires that authenticated identity plus the existing resume secret.
Cross-device and shared-token resumes into a bound-device session are rejected.

The existing `/xiaozhi/ota/<token>/` route accepts either a valid device credential
or the legacy shared token. It returns only the credential presented in the URL,
never a device-to-global-token upgrade. Revoked or invalid tokens return 404.
OTA URLs themselves contain credentials: avoid logs/screenshots or untrusted
proxies that record request paths. Use HTTPS/WSS on untrusted networks; default
LAN HTTP compatibility is retained for existing hardware.

Shared-token devices and old `{}` prepare requests remain compatible, but are
identified as the legacy WS credential group; their hardware labels remain
self-declared. No existing device is automatically migrated or disconnected.
Per-device MQTT authentication remains unchanged.

The SQLite table is additive. Back up runtime data before deploying. To roll back
without locking out newly provisioned devices, first restore their prior NVS
settings from a verified backup or provision legacy shared settings while the new
server is still available, then return to the older server. Simply reverting the
server cannot make new device credentials work with old code.

Integration tests cover binding, source attribution, cross-identity resume,
revocation, OTA isolation and legacy compatibility. Hardware flashing and real
ESP32 reconnect/recording behavior still require physical acceptance.
