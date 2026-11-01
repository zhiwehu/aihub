#!/bin/bash
# Assemble a small Docker build context from the sibling repos.
#
# The workspace layout is aihub/{aihub-common,aihub-tools,aihub-server,aihub-web,...}.
# Building straight from the workspace root would ship .venv/ and data/ to the
# daemon, so instead this copies only the four trees the image needs into
# ./context and the Dockerfile is built from there.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"          # aihub/
CTX="$HERE/context"

[ -x "$ROOT/.venv/bin/python" ] || {
  echo "错误: 找不到 $ROOT/.venv。先在工作区根目录建好虚拟环境。" >&2; exit 1; }

rm -rf "$CTX"
mkdir -p "$CTX/pkgs" "$CTX/web" "$CTX/assets"
cp "$HERE/Dockerfile" "$CTX/Dockerfile"   # context must be self-contained

for pkg in aihub-common aihub-tools aihub-server; do
  src="$ROOT/$pkg"
  [ -d "$src/src" ] || { echo "错误: $src 缺少 src/" >&2; exit 1; }
  mkdir -p "$CTX/pkgs/$pkg"
  cp "$src/pyproject.toml" "$CTX/pkgs/$pkg/"
  cp -R "$src/src" "$CTX/pkgs/$pkg/src"
  find "$CTX/pkgs/$pkg/src" -name '__pycache__' -type d -prune -exec rm -rf {} +
  echo "  + pkgs/$pkg"
done

[ -f "$ROOT/aihub-web/public/index.html" ] || {
  echo "错误: 找不到 $ROOT/aihub-web/public/index.html" >&2; exit 1; }
cp -R "$ROOT/aihub-web/public/." "$CTX/web/"
echo "  + web/ ($(find "$CTX/web" -type f | wc -l | tr -d ' ') 个文件)"

# Silero VAD ONNX: the server borrows it from faster_whisper's assets, which are
# not a dependency here, so the image has to carry its own copy.
vad=""
if [ -n "${VOICE_VAD_MODEL:-}" ] && [ -f "${VOICE_VAD_MODEL}" ]; then
  vad="$VOICE_VAD_MODEL"
else
  for candidate in "$HOME"/.cache/uv/archive-v0/*/faster_whisper/assets/silero_vad_v6.onnx; do
    [ -f "$candidate" ] && { vad="$candidate"; break; }
  done
fi
[ -n "$vad" ] || {
  echo "错误: 找不到 silero_vad_v6.onnx。" >&2
  echo "  从 https://github.com/snakers4/silero-vad 下载 v6 ONNX 后：" >&2
  echo "  VOICE_VAD_MODEL=/path/to/silero_vad_v6.onnx $0" >&2
  exit 1; }
cp "$vad" "$CTX/assets/silero_vad_v6.onnx"
echo "  + assets/silero_vad_v6.onnx  (来自 $vad)"

echo
echo "构建上下文就绪: $CTX ($(du -sh "$CTX" | cut -f1))"
echo "下一步: docker compose -f $HERE/compose.yaml build"
