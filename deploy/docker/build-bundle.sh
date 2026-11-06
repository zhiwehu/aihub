#!/bin/bash
# Build the two AIHub images for the Intel host and pack them with a Compose file.
#
#   ./deploy/docker/build-bundle.sh [tag]
#
# Output: dist/aihub-225h-<tag>.tar.gz, ready to copy to the target host.
# Build on any machine with Docker; images are linux/amd64 by default.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
TAG="${1:-$(git -C "$ROOT" rev-parse --short HEAD)}"
IMAGE_TAG="225h-$TAG"
PLATFORM="${PLATFORM:-linux/amd64}"
DIST="$ROOT/dist"
BUNDLE="$DIST/aihub-225h"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

command -v docker >/dev/null || { echo '需要 Docker。' >&2; exit 1; }
[ -x "$ROOT/.venv/bin/python" ] || {
  echo "找不到 $ROOT/.venv，先在仓库根目录执行 ./scripts/install.sh。" >&2; exit 1; }
case "$TAG" in
  */*|*' '*) echo "tag 不能包含 / 或空格" >&2; exit 2 ;;
esac

echo "==> 标签 ${IMAGE_TAG}，平台 ${PLATFORM}"
if [ -n "${VOICE_VAD_MODEL:-}" ] && [ -f "$VOICE_VAD_MODEL" ]; then
  cp "$VOICE_VAD_MODEL" "$TMP/silero_vad_v6.onnx"
else
  curl -fL --retry 3 \
    https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/assets/silero_vad_v6.onnx \
    -o "$TMP/silero_vad_v6.onnx"
fi
VOICE_VAD_MODEL="$TMP/silero_vad_v6.onnx" "$HERE/prepare-context.sh" --no-client

echo "==> 构建 core"
docker build --platform "$PLATFORM" -t "aihub-core:$IMAGE_TAG" "$HERE/context"

echo "==> 构建 processing"
mkdir -p "$HERE/context/pkgs/aihub-models"
cp "$ROOT/packages/processing/"{pyproject.toml,README.md,LICENSE} "$HERE/context/pkgs/aihub-models/"
cp -R "$ROOT/packages/processing/src" "$HERE/context/pkgs/aihub-models/"
cp "$HERE/Dockerfile.processing" "$HERE/context/Dockerfile.processing"
docker build --platform "$PLATFORM" \
  -f "$HERE/context/Dockerfile.processing" -t "aihub-processing:$IMAGE_TAG" "$HERE/context"

echo "==> 打包"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/images"
sed "s/@TAG@/$IMAGE_TAG/g" "$HERE/bundle/compose.yaml.in" > "$BUNDLE/compose.yaml"
cp "$HERE/bundle/.env.example" "$BUNDLE/.env.example"
cp "$HERE/bundle/install.sh" "$BUNDLE/install.sh"
chmod 755 "$BUNDLE/install.sh"
cp "$HERE/INTEL-225H.zh-CN.md" "$BUNDLE/README.md"
docker save "aihub-core:$IMAGE_TAG" "aihub-processing:$IMAGE_TAG" | gzip -9 > "$BUNDLE/images/aihub-images.tar.gz"
tar -czf "$DIST/aihub-225h-$TAG.tar.gz" -C "$BUNDLE" .

echo
echo "包: $DIST/aihub-225h-$TAG.tar.gz ($(du -h "$DIST/aihub-225h-$TAG.tar.gz" | cut -f1))"
echo "下一步: scp 到目标机，解压后编辑 .env，执行 ./install.sh"
