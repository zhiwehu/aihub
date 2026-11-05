# Delivery validation

Scope selected by the user: keep six repositories. Core HTTP processing shipped
in aihub-models commit 7313877; initial Linux lifecycle work shipped in server
commit 34169ab. The remaining client/server and admin-web commits follow.

## Evidence

- Models full pytest suite: 63 passed, including loopback HTTP WAV, bearer auth,
  provider errors, invalid output, timeout, cancellation and ASR retry exhaustion.
- Server full pytest suite: 300 passed, 18 subtests passed, 1 pre-existing failure:
  `test_wake_phrase_alone_activates_without_creating_empty_reply` (unchanged).
- Server client tests cover credential requirements, absent management routes,
  forged device ID, cross-client resume, recording/audio/transcript/minutes/export
  isolation, revocation, pause/resume writes, unknown historical ownership,
  administrator source/device filters, explicit CORS and loopback Origin handling.
- Linux generator test confirms explicit HTTP model IDs and refuses overwrites.
- Web: all public JS syntax checks plus 11 Node tests passed.
- Firmware: 66 Node tests and 9 compiled C++ logic tests passed; source unchanged.
- Chrome browser: isolated temporary data and ports 18765/18768; created a temporary
  credential, authenticated the independent client, sent text, interrupted fake
  speech, observed source/device history links and correct source classification.
  Found/fixed credential-response decoding and Origin-port compatibility failures.
- Shell syntax checks passed for workspace/model-host/build-context scripts.

## Practical limits and rollout

No runtime configuration or recordings in the workspace data directory were
changed. The old live process still needs an intentional cutover after backup.
Follow deploy/linux/README.md and clients/web-demo/README.md. Newly added SQLite
tables are additive; old source-less records remain unknown. Model endpoints and
credential environment variables are operator inputs, not fabricated deployments.

Browser verification used a fake inference pipeline and did not grant microphone
permission. It does not validate real ASR/TTS quality or audio-device routing.
No Intel machine, Linux systemd activation, Docker image rebuild, actual ESP32
recording controls, long-recording processing or latency/memory measurement was
verified. The legacy shared device token cannot prove an individual hardware ID;
this existing limitation is documented rather than presented as verified identity.
The browser client has dedicated server-issued identity and record isolation.

Client-listener shutdown explicitly closes authenticated and pending WebSockets;
its regression test passes within a one-second deadline. Final server suite is
300 passed + 18 subtests, with the same single baseline wake-phrase failure.
Admin Web delivery commit: 7c08083. No live cutover was performed.
