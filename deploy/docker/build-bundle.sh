#!/bin/bash
# Build the two AIHub images for an Intel x86_64 host and pack them together with
# the same Compose files every other host uses.
#
#   ./deploy/docker/build-bundle.sh [tag]
#
# Output: dist/aihub-225h-<tag>.tar.gz, ready to copy to the target host.
# Images are linux/amd64 by default (override with PLATFORM=...). Only .env
# differs from a macOS deployment — compose files and services are identical.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
TAG="${1:-$(git -C "$ROOT" rev-parse --short HEAD)}"
IMAGE_TAG="225h-$TAG"
DIST="$ROOT/dist"
BUNDLE="$DIST/aihub-225h"

case "$TAG" in
  */*|*' '*) echo "tag 不能包含 / 或空格" >&2; exit 2 ;;
esac

echo "==> 标签 ${IMAGE_TAG}，平台 ${PLATFORM:-linux/amd64}"
PLATFORM="${PLATFORM:-linux/amd64}" "$HERE/build-images.sh" "$IMAGE_TAG"

echo "==> 打包"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/images"
cp "$HERE/compose.yaml" "$HERE/compose.host.yaml" "$HERE/bundle/install.sh" "$BUNDLE/"
cp "$HERE/bundle/bridge.py" "$BUNDLE/bridge.py"
chmod 755 "$BUNDLE/install.sh"
cp "$HERE/env.models.env.example" "$BUNDLE/env.models.env.example"
{ cat "$HERE/.env.example";
  printf '\n# Pinned by this bundle.\nAIHUB_CORE_IMAGE=aihub-core:%s\nAIHUB_PROCESSING_IMAGE=aihub-processing:%s\n' "$IMAGE_TAG" "$IMAGE_TAG"; } \
  > "$BUNDLE/.env.example"
cp "$HERE/INTEL-225H.zh-CN.md" "$BUNDLE/README.md"
if [ -f "$HERE/client-web/index.html" ]; then
  mkdir -p "$BUNDLE/client-web"
  cp -R "$HERE/client-web/." "$BUNDLE/client-web/"
  echo "  + client-web/（已安装的客户端 artifact）"
fi
docker save "aihub-core:$IMAGE_TAG" "aihub-processing:$IMAGE_TAG" | gzip -9 > "$BUNDLE/images/aihub-images.tar.gz"
tar -czf "$DIST/aihub-225h-$TAG.tar.gz" -C "$BUNDLE" .

echo
echo "包: $DIST/aihub-225h-$TAG.tar.gz ($(du -h "$DIST/aihub-225h-$TAG.tar.gz" | cut -f1))"
echo "下一步: scp 到目标机，解压后编辑 .env，执行 ./install.sh"
