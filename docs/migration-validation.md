# Three-repository migration validation

2026-11-05. Source tips and import/split mapping: source-map.json.

## Automated evidence

- Isolated environment installation via root scripts/install.sh --dev passed.
  All four package __file__ values resolve inside this core's packages/, never
  the running six-repository workspace. MQTT dependencies are explicit test extras.
- Common: 54 passed. Processing: 63 passed. Tools: 79 passed + 12 subtests.
- Server: 305 passed + 18 subtests; only the original documented wake-phrase test
  fails. It remains unmodified and is not skipped or masked. Root test.sh preserves
  a nonzero result for that inherited failure.
- Root artifact integrity test: 1 passed (valid install, tamper rejection without
  overwriting the previously installed artifact).
- Admin Web: 11 Node checks passed; public JavaScript syntax checks passed.
- Independent client: 2 capture tests passed at 44.1/48 kHz; build creates a
  protocol-versioned SHA256 artifact. Client JavaScript syntax checks passed.
- Firmware clone: 66 Node checks and 9 compiled C++ logic checks passed. Firmware
  code and protocol remain unchanged; README identifies the new core owner.
- Shell syntax checks passed. Required import boundaries were checked with AST.
- All five original common/models/tools/server/web source tips are ancestors of
  core HEAD through non-squashed subtree merges; client split provenance is pinned.

## Runtime / packaging evidence

- Root start.sh launched native server and processing from this repository on
  18765/18768/18790 with dedicated disposable data and inference workers disabled.
- Real HTTP/WebSocket smoke checks passed: included admin, explicit client static
  artifact, mandatory credentials, absent client management routes, authenticated
  hello and server-assigned source identity despite forged device ID.
- Docker image aihub-core:migration-20261105 built from the new core context and
  explicit client artifact. A disposable container on 19765/19768 passed the same
  checks, without any old source directory or live-data mount.
- Context preparation now verifies the artifact manifest and copies only its
  allowlisted files. Runtime data, .venv, model weights and secrets are excluded.
- Native smoke services stopped through the new root entry point; disposable
  Docker container removed. The built image and client artifact remain available.

## Limits / deployment status

The original live Docker container and model processes continue unchanged. This
migration does not move recordings/configuration, reconfigure hardware or switch
production ingress. Follow migration.md for a backed-up cutover and rollback.
No actual microphone, long-recording, ESP32 flash or Intel performance claim is
made from the isolated smoke checks. Old repositories remain available and clean.

## Published code revisions

Core migration implementation: d270463. Independent client: a8eed5e. Firmware
layout documentation: f76b416 (code unchanged). All targets are published on main
without force pushes. Original source repositories remain in place; no production
cutover was performed. Client release artifacts include the source license.
