# Implementation status (2026-11-05)

- [x] processing-http: explicit HTTP minutes and retranscription providers; models suite 63 passed.
- [x] linux-runtime: non-overwriting HTTP settings generator, owned-process lifecycle, portable LAN discovery, systemd/environment examples and rollback instructions.
- [x] client-identity: hashed dedicated browser credentials, scoped HTTP/WebSocket access, source persistence, isolation/origin/revocation/legacy-record tests.
- [x] client-web: standalone static client at separate port 8768/demo/, scoped chat/PCM/recording/pause/resume/history/minutes. No admin modules or credentials.
- [x] admin-records: remove microphone/chat UI and capture implementation; retain playback/minutes; add source/device/status/time filtering, device record links and credential management.
- [x] deployment inputs: Docker build context explicitly carries client artifacts, metadata files and a separate client port; stop scripts no longer kill arbitrary port listeners.
- [x] software regression: server 299 passed + 18 subtests, only the documented existing wake-phrase failure; Web 11 passed; firmware 66 Node tests + 9 C++ logic checks passed. Browser checked temporary credential creation, client connection, text input, interrupt, source attribution and device-to-history navigation with a fake pipeline.
- [ ] Hardware acceptance: actual microphone capture/playback, long recordings on Intel 225H, real external Linux endpoints, real ESP32 recording controls and measured latency/memory. Docker image rebuild and systemd activation are not performed on this Mac.
- [ ] Runtime cutover: back up live data/configuration, stop legacy launcher processes explicitly if they lack identity records, then restart using the new entry point. No live data was migrated or production services restarted during implementation.
- [ ] Legacy device identity: shared ESP32 WebSocket tokens still authenticate a device group; device IDs remain device-declared. Per-device WS credential migration is not claimed complete. Existing MQTT per-device credentials remain supported.
