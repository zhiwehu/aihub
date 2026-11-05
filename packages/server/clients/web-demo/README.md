# Independent browser client (protocol v1)

Source, static resources and client APIs are independent of `aihub-web`. No build
step and no administrator token are needed. The CLI starts a client-only listener
on `127.0.0.1:8768`; open `/demo/`. It has no management routes, even on localhost.
The management console stays at `127.0.0.1:8765`. Use `--client-host`/`--client-port`
to change client ingress; keep the admin console on loopback.

In the admin console create a named client credential under client connections.
Copy that credential to the client page. It is shown only once and only its SHA256
digest is stored in the server's SQLite database. Each credential defines one
client instance with its own authorized records; use separate credentials for
separate browsers. Keep it private. Revocation disconnects its active sockets.
No registration system is introduced.

The browser keeps the credential in memory for this page only. Reload requires
entering it again; old records remain accessible with the same credential.
WebSocket hello carries `token`, `version:1`, optional session/resume token,
`audio:{format:'pcm_s16le',sample_rate:16000}` and `wake_mode:'manual'`. The server
assigns `device_id=web:<client-id>` and refuses resumes owned by another client.
Chat PCM is streamed, not automatically saved as a persistent recording.

Client HTTP APIs use `Authorization: Bearer <client-credential>`:

- GET `/client/v1/sessions`, `/sessions/<sid>/messages`
- GET/POST `/client/v1/recordings`; POST requires `{session_id}` for an owned active socket
- GET `/client/v1/recordings/<id>`, `/audio`, `/transcript`, `/speech`, `/speech-map`, `/clean`
- POST `/client/v1/recordings/<id>/stop`
- GET `/client/v1/meeting-templates`
- GET/POST `/client/v1/recordings/<id>/minutes`; POST `{template_id}`
- GET `/client/v1/recordings/<id>/minutes/<job-id>` and `/export?format=md`

Paths after the first entry use the same prefix. Ownership is checked before
proxying minutes or serving audio. Unknown/other-client IDs return 404. The client
constructs scoped download URLs and does not use administrator download links
returned in legacy metadata. Unauthorized requests return 401.

Recording socket commands are `recording.start`, `recording.pause`,
`recording.resume`, `recording.stop`. Pause and resume require the correct active
state; repeated/invalid transitions produce an error. Pause preserves recording
ID and prevents PCM writes. The current ESP32 firmware keeps its existing start/
stop behavior; new browser pause controls do not imply firmware supports them.
Disconnect finalizes the recording using existing server behavior; reconnect and
refresh to confirm persisted status. A saved file with zero samples is labelled
as having no audio rather than successful capture.

For separate static hosting copy this directory's files preserving `/demo/assets/`
paths, configure the server address in the page, and set `AIHUB_CLIENT_ORIGINS` on
the server to an exact comma-separated origin allowlist (scheme, host and port).
No wildcard CORS or credential cookies. WebSocket origins use the same allowlist.
Prefer one HTTPS origin reverse-proxying `/client/` and `/ws` to **8768**, never to
the administrator port. Preserve Host and upgrade headers. Microphone capture
requires HTTPS or localhost. Use `AIHUB_CLIENT_ROOT` to point a packaged server to
an explicit static artifact directory; the editable workspace uses this directory.

Old recordings without source metadata remain administrator-readable and are
labelled unknown; they are not assigned to new clients by guessing device names.
The shared legacy ESP32 token authenticates the device group, not an individual
hardware identity: existing device IDs remain device-declared labels. Use the
existing per-device MQTT credentials for stronger hardware attribution. Per-device WS credentials are now available for new provisioning; see
../../docs/device-credentials.md. Existing shared-token devices are not silently migrated.
