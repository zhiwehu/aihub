# Core Docker deployment

For a Linux x86_64 CPU setup reusing existing HTTP model services, with core and processing containers, see the
[Intel Core Ultra 5 225H guide (中文)](INTEL-225H.zh-CN.md). That guide deploys
the server only: the web client is built and released from its own repository, so
the image is prepared with `prepare-context.sh --no-client` while the server still
runs its client listener for that external page. It also uses a separate Linux
host-network Compose example; do not combine its networking with the bridge-network
deployment below.

This image contains core common/tools/server packages and the included management
console. Processing and inference remain separate services; Linux external HTTP
models do not require MLX. See ../linux/README.md for provider settings/systemd.

## Explicit build inputs

From the core repository root install the environment, install a verified client
release and supply a trusted VAD ONNX model. For a server-only image (no web
client), skip the client install and pass `--no-client` to the context script:

```sh
./scripts/install.sh
.venv/bin/python scripts/install-client.py /absolute/path/to/client-release
VOICE_VAD_MODEL=/absolute/path/to/silero_vad_v6.onnx ./deploy/docker/prepare-context.sh
docker build -t aihub-core:local deploy/docker/context
```

The build context copies only this repository's packages/admin assets, the
explicit client artifact when one is selected, and VAD. It never reads sibling
source repositories, `.venv`, runtime data, credentials or weights beyond the
explicitly selected VAD. Docker installs package metadata/license/readme along
with source.

Before `docker compose` copy env.models.env.example to env/models.env and supply
real endpoint bearer keys/shared processing token. Protect it with mode 600.
Create deployment .env from .env.example and set data/mount/network paths.
The optional Mac `model-host.sh` can create owned-worker env/pid records; do not
use it to manage independently deployed Linux model services.

```sh
cd deploy/docker
docker compose build
docker compose up -d --no-build
docker compose ps
```

The default project/container/image is `aihub-core`, distinct from the original
six-repo deployment. Do not start it on ports or a data directory already used by
the old system. Administrator and browser ports publish only on host loopback;
client Web uses separate credentials and has no administrator routes.

Set `AIHUB_FIRMWARE_DIR` to an explicit flashing release directory. If unavailable,
an empty default data/flash mount leaves the flashing panel unavailable while
other management functions work. Firmware source is never copied into core.

`AIHUB_CLIENT_LOOPBACK_PROXY=1` is valid only while the client port remains
published on host loopback. It permits the Origin-port-omission compatibility
case with loopback Host plus browser same-origin metadata; credentials remain
mandatory. Remove the assertion for non-loopback publication. Prefer HTTPS
reverse proxying client routes to 8768, keeping admin ingress private.

Use `AIHUB_CONTAINER_PORT`, `AIHUB_CLIENT_PORT`, `AIHUB_DEVICE_HOST` and explicit
model URLs for deployment. The optional device listener remains at container
8766; map it intentionally on the host. `model-host.sh stop` signals only owned
processes verified by identity records, never arbitrary port listeners.

See ../../docs/migration.md for backup, cutover, retained source history and
rollback. Never run old/new versions against one runtime directory concurrently.
