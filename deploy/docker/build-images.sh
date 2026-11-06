#!/bin/bash
# Build the core and processing images. Same command on macOS and Linux; only
# --platform and the tag differ between a local build and an offline bundle.
#
#   ./deploy/docker/build-images.sh [tag]          # native arch, tag "local"
#   PLATFORM=linux/amd64 ./deploy/docker/build-images.sh 225h-abc1234
#
# Server-only core image: the web client is a separately versioned artifact,
# mounted at run time (see ../../scripts/install-client.py).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
TAG="${1:-local}"
PLATFORM="${PLATFORM:-}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

command -v docker >/dev/null || { echo '需要 Docker。' >&2; exit 1; }
# Default to the daemon's own architecture: reusing a cached base image of
# another architecture would produce an image that cannot run natively.
[ -n "$PLATFORM" ] || PLATFORM="linux/$(docker version --format '{{.Server.Arch}}')"
[ -x "$ROOT/.venv/bin/python" ] || {
  echo "找不到 $ROOT/.venv，先在仓库根目录执行 ./scripts/install.sh。" >&2; exit 1; }
case "$TAG" in
  */*|*' '*) echo "tag 不能包含 / 或空格" >&2; exit 2 ;;
esac

if [ -n "${VOICE_VAD_MODEL:-}" ] && [ -f "${VOICE_VAD_MODEL}" ]; then
  cp "$VOICE_VAD_MODEL" "$TMP/silero_vad_v6.onnx"
else
  echo '==> 下载 Silero VAD v6'
  curl -fL --retry 3 \
    https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/assets/silero_vad_v6.onnx \
    -o "$TMP/silero_vad_v6.onnx"
fi
VOICE_VAD_MODEL="$TMP/silero_vad_v6.onnx" "$HERE/prepare-context.sh" --no-client

build() {  # $1 = tag, rest = docker build args
  local image="$1"; shift
  docker build --platform "$PLATFORM" -t "$image" "$@"
}

echo "==> 平台 $PLATFORM"
echo "==> 构建 core:$TAG"
build "aihub-core:$TAG" "$HERE/context"

echo "==> 构建 processing:$TAG"
mkdir -p "$HERE/context/pkgs/aihub-models"
cp "$ROOT/packages/processing/"{pyproject.toml,README.md,LICENSE} "$HERE/context/pkgs/aihub-models/"
cp -R "$ROOT/packages/processing/src" "$HERE/context/pkgs/aihub-models/"
cp "$HERE/Dockerfile.processing" "$HERE/context/Dockerfile.processing"
build "aihub-processing:$TAG" -f "$HERE/context/Dockerfile.processing" "$HERE/context"

echo
echo "镜像就绪: aihub-core:$TAG  aihub-processing:$TAG"
echo "下一步: 准备好 .env 与 env/models.env，然后 docker compose up -d"
