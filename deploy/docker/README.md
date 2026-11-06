# Core Docker deployment

One code base, one image set, one compose file — on macOS and Linux alike. Only
the model services behind the containers differ.

```
containers (identical on every host)                     model services (per host)
┌──────────────────────────────────────────────┐   ┌──────────────────────────────┐
│ core   :8765 console (loopback)              │   │ macOS: native MLX workers    │
│        :8768 client  (loopback)              │──▶│        host.docker.internal  │
│        :8766 devices (LAN)                   │   │ Linux: AtomGradient / vLLM / │
│ processing :8790 minutes / retranscription   │   │        any OpenAI-compatible │
│ bridge :18095 optional protocol adapter      │   │        endpoint              │
└──────────────────────────────────────────────┘   └──────────────────────────────┘
```

## Why inference stays outside the containers

`packages/processing` can run inference through MLX, which needs Apple Silicon
macOS and cannot work inside a Linux container. On a Linux host the models are
already-deployed HTTP services. Either way the containers only speak HTTP, so the
images carry no weights and no model runtime.

## What actually differs per host

| | macOS | Linux |
|---|---|---|
| Networking | published ports + `host.docker.internal` (base compose) | `compose.host.yaml` when models bind 127.0.0.1 |
| Model endpoints | native workers on the host: `host.docker.internal:8781/8782/8767` | whatever is reachable: `127.0.0.1`, LAN or container |
| Protocol adapter | not needed (ASR/LLM/TTS are OpenAI-compatible) | `--profile bridge` only when the provider uses a private protocol (AtomGradient) |
| Client artifact | same verified artifact, mounted read-only | same |
| Images | `linux/arm64` | `linux/amd64` |

Everything else — services, data layout, ports, console behaviour, client
authentication — is identical.

## Build

```sh
./scripts/install.sh                    # base environment
./scripts/install.sh --local --dev      # macOS only: MLX inference + test extras

# Verified client artifact (independent repository, checksum checked)
.venv/bin/python scripts/install-client.py /absolute/path/to/client-release

# Both images, native platform
./deploy/docker/build-images.sh

# Offline bundle for an Intel host (linux/amd64 + tarball)
./deploy/docker/build-bundle.sh
```

`build-images.sh` derives a small build context with `prepare-context.sh
--no-client`: this repository's packages, the console, and a Silero VAD ONNX.
The web client is deliberately **not** baked in — see below.

## Configure and run

```sh
cd deploy/docker
cp .env.example .env
cp env.models.env.example env/models.env && chmod 600 env/models.env
$EDITOR .env                            # paths, LAN address, model endpoints

docker compose up -d                                     # macOS / LAN-reachable models
docker compose -f compose.yaml -f compose.host.yaml up -d # Linux, models on loopback
```

macOS additionally needs the native model tier and the container-facing URLs in
`settings.json`:

```sh
./model-host.sh start     # asr/llm/tts workers on 127.0.0.1
./configure.sh            # rewrite settings.json to host.docker.internal
```

`model-host.sh` no longer starts the processing service — that is the
`processing` container now.

## The web client is an artifact, not part of the image

The 8768 listener serves `/demo/` because it owns the client credentials and the
same-origin WebSocket, but the files come from a mounted, verified release:

```yaml
- "${AIHUB_CLIENT_ROOT}:/app/client-web:ro"
```

`scripts/install-client.py` verifies `protocol_version` and every SHA256 in the
release manifest before installing. Upgrading the client is a `docker compose
restart core` away — no image rebuild, and the client can ship on its own
cadence. An empty directory just means `/demo/` is unavailable; the console and
the device gateway keep working.

## Optional protocol bridge

`bundle/bridge.py` adapts OpenAI-style ASR/TTS to a provider that only speaks its
own protocol (today: AtomGradient's HTTP ASR + bidirectional WebSocket TTS). It is
a plain aiohttp service with every upstream address configurable:

```sh
# .env
COMPOSE_PROFILES=bridge
ATOM_ASR_URL=http://host.docker.internal:18094/v1/asr
ATOM_TTS_HTTP_URL=http://host.docker.internal:18094/api/v1/tts
ATOM_TTS_WS_URL=ws://host.docker.internal:18093/api/v3/tts/bidirection
```

Then point the console's TTS (and/or ASR) at `http://bridge:18095/v1`
(`http://127.0.0.1:18095/v1` under host networking).

Portability notes, both verified on Docker Desktop 4.35 / macOS:

- `--network host` does **not** reach the Mac's loopback, so the host-network
  compose override is Linux-only. The base compose publishes ports instead.
- `pid: host` on macOS is the Linux VM's namespace, so the bridge cannot read the
  provider's macOS PID; `/health` simply omits the process metrics.
- `TTS_MODE=http` disables the WebSocket attempt and uses the HTTP endpoint only.

## Verify

```sh
./verify.sh    # synthesises speech, then runs the server's Pipeline inside the
               # container: ASR multipart → LLM SSE → TTS PCM
```

## Files

| File | Purpose |
|---|---|
| `compose.yaml` | the deployment: core + processing (+ bridge profile) |
| `compose.host.yaml` | Linux-only network override for loopback-bound models |
| `build-images.sh` | build core and processing for this host's platform |
| `build-bundle.sh` | same images for linux/amd64, packed with a compose file |
| `prepare-context.sh` | assemble the minimal build context (no `.venv`, no data) |
| `Dockerfile` / `Dockerfile.processing` | core and processing images |
| `bundle/bridge.py` | optional private-protocol adapter |
| `bundle/install.sh` | target-host installer for the offline bundle |
| `model-host.sh` | macOS: start/stop the native ASR/LLM/TTS workers |
| `configure.sh` | macOS: point `settings.json` at `host.docker.internal` |
| `verify.sh` | end-to-end check through the real pipeline |

`context/`, `env/`, `.env` are generated and ignored by Git. `env/models.env`
holds bearer keys — mode 600, never commit.

## Clients on other machines (LAN)

By default both the console and the client listener publish on loopback. To open
the web client from another machine, publish only the client listener and keep
the console private:

```sh
# .env
AIHUB_CLIENT_BIND=0.0.0.0
AIHUB_CLIENT_LOOPBACK_PROXY=0
AIHUB_CLIENT_PUBLIC_URL=http://192.168.1.50:8768/demo/
# Only needed when the page itself is hosted on another origin:
# AIHUB_CLIENT_ORIGINS=http://192.168.1.50:8768
```

Open `AIHUB_CLIENT_PUBLIC_URL` on the other machine and paste a connection code
generated in the console. The page always talks to its own origin, so no server
address has to be typed anywhere.

Microphone caveat: browsers expose `getUserMedia` only in a secure context.
`http://localhost` qualifies, a plain `http://192.168.x.x` address does not — chat
and recording start, but the microphone is refused. For voice from another
machine put the client listener behind HTTPS, or use the device path (8766),
which carries its own credentials and has no such restriction.

## Security notes

- The console publishes on `127.0.0.1` only, which is why the base compose can
  pass `--local-console`. Do not publish 8765 on the LAN with that flag.
- The client listener (8768) never inherits administrator routes and always
  requires a client credential.
- `AIHUB_CLIENT_LOOPBACK_PROXY=1` only relaxes the Origin-port-omission case for
  loopback Host + same-origin fetches. Drop it if you publish 8768 beyond
  loopback, and prefer an HTTPS reverse proxy.
- The device listener (8766) is authenticated by device credentials.
