# AIHub

Core repository: server, administration, tools, shared primitives and recording
processing. Separate repositories: `aihub-client-web` (browser client) and
`aihub-firmware` (ESP32 and provisioning). The original Python package names and
CLI entry points remain compatible; repository consolidation does not merge the
server, processing and inference processes.

## Install and run

```sh
./scripts/install.sh --dev              # base HTTP path; Python 3.11+
# macOS optional inference: ./scripts/install.sh --local --dev
./start.sh --background
./start.sh --status
./start.sh --stop
```

Runtime data defaults to `./data`, isolated from Git. Set `AIHUB_DATA` to an
explicit existing deployment directory only during an intentional cutover. For
parallel validation choose unused `AIHUB_PORT`, `AIHUB_CLIENT_PORT`,
`AIHUB_MODELS_PORT` and `--device-host none`; use `--no-models` for smoke checks.
The base install does not include MLX; configure HTTP models on Linux or install
macOS local extras before starting owned inference workers.

The administrator console is included at `apps/admin-web/public`; no client dev
server is needed. It defaults to localhost:8765. The client-only listener defaults
to localhost:8768 and requires a client artifact and dedicated credentials.

## Independent client and firmware inputs

Build a release in the client repository (`npm run build`), then install its
explicit output directory:

```sh
.venv/bin/python scripts/install-client.py /absolute/path/to/client-release
```

This verifies protocol version and SHA256 hashes, installing the artifact into
`.artifacts/client-web`. The launcher exports that path to the server. Other
hosting can set `AIHUB_CLIENT_ROOT`; the server never reads a sibling client source
tree. The directory can be transferred from CI or unpacked from a release archive.

Firmware is optional: set `AIHUB_FIRMWARE_ROOT` to an installed flashing release
(or an explicit firmware `flash/` artifact). Missing firmware assets disable only
the flashing panel. Neither independent repository is needed to install/run core.

## Structure and validation

- `packages/common`: `aihub_common`, leaf primitives.
- `packages/tools`: `aihub_tools`, tools and orchestration; no server imports.
- `packages/server`: `aihub_server`, HTTP/WebSocket gateway, persistence and APIs.
- `packages/processing`: `aihub_models`, processing and optional Mac workers.
- `apps/admin-web`: static management UI and its tests.
- `deploy/`: Docker and Linux deployment examples; `scripts/`: root tooling.

Run `./scripts/test.sh`. It runs every package suite independently and the admin
Web checks. The inherited wake-phrase test failure is documented, retained and
reported as a nonzero result, never skipped to make the migration appear green.

See [migration, history and rollout](docs/migration.md),
[Linux HTTP deployment](deploy/linux/README.md), and
[device credentials](docs/device-credentials.md).
