#!/bin/bash
# Build a Linux copy of the Rex runtime under <data>/rex-runtime-linux.
#
# The vendored <data>/rex-runtime was installed on macOS, so its compiled wheels
# (tokenizers.abi3.so, aiohttp/*.so, …) are Mach-O and importing them in a Linux
# container fails with "invalid ELF header". This script installs the same pinned
# versions - taken from that tree, so the two stay in lockstep - into a sibling
# directory that a container can import.
#
#   ./build-rex-runtime.sh            # first build
#   ./build-rex-runtime.sh --force    # rebuild from scratch
#
# The result is ~1.4 GB inside the data directory, not in the image: the image
# stays at ~395 MB and the runtime is mounted with the data volume.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
DATA="${AIHUB_DATA:-$ROOT/data}"
SOURCE="$DATA/rex-runtime"
TARGET="$DATA/rex-runtime-linux"
IMAGE="${AIHUB_IMAGE:-aihub-core:local}"
TORCH="${AIHUB_REX_TORCH:-2.15.0+cpu}"
INDEX="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
TORCH_INDEX=https://download.pytorch.org/whl/cpu

say() { printf '%s\n' "$*"; }
die() { printf '错误: %s\n' "$*" >&2; exit 1; }

[ -d "$SOURCE" ] || die "找不到 ${SOURCE}（原生模式的 Rex 运行时，用来读取版本清单）"
[ "$(uname -s)" = "Darwin" ] || say "提示: 这个脚本通常在 macOS 宿主上运行，用于生成 Linux 版运行时"

if [ -d "$TARGET" ] && [ "${1:-}" != "--force" ]; then
  say "已存在 ${TARGET}（$(du -sh "$TARGET" | cut -f1)），要重建请加 --force"
  exit 0
fi

REQ="$(mktemp -t rex-req)"
trap 'rm -f "$REQ"' EXIT
"$PY" - "$SOURCE" > "$REQ" <<'PY'
import sys
from pathlib import Path

# torch is installed separately from the CPU index; CUDA payloads are pruned.
SKIP = ('torch', 'nvidia', 'triton', 'cuda', 'pip', 'setuptools', 'wheel')
rows = []
for path in sorted(Path(sys.argv[1]).glob('*.dist-info')):
    name, _, version = path.name[:-len('.dist-info')].rpartition('-')
    if not name or not version:
        continue
    if name.split('_')[0] in SKIP:
        continue
    rows.append(f'{name}=={version}')
print('\n'.join(rows))
PY
say "版本清单: $(wc -l < "$REQ" | tr -d ' ') 个包（来自 ${SOURCE}）"

mkdir -p "$TARGET"
say "安装 Linux 依赖到 $TARGET …"
docker run --rm -i \
  -v "$TARGET:/target" \
  -v "$REQ:/req.txt:ro" \
  --entrypoint sh "$IMAGE" -c "
set -e
pip install -q --upgrade --target /target --index-url $INDEX -r /req.txt 2>&1 | grep -viE 'warning' | tail -3 || true
pip install -q --upgrade --force-reinstall --no-deps --target /target \
  --index-url $TORCH_INDEX 'torch==$TORCH' 2>&1 | grep -viE 'warning' | tail -3 || true
# PyPI's default torch wheel drags the whole CUDA stack in; the planner runs on CPU.
rm -rf /target/nvidia /target/triton /target/cuda
" || die "构建失败"

# Keep only the CPU torch metadata; pip can leave the CUDA entry behind.
for dist in "$TARGET"/torch-*.dist-info; do
  case "$dist" in *+cpu*) ;; *) rm -rf "$dist" ;; esac
done

say "构建完成: $TARGET ($(du -sh "$TARGET" | cut -f1))"
say "冒烟测试 …"
docker run --rm -i -v "$TARGET:/target" --entrypoint python "$IMAGE" -c "
import sys; sys.path.insert(0,'/target')
import torch, transformers, datasets
print('  torch', torch.__version__, '| transformers', transformers.__version__,
      '| datasets', datasets.__version__)
" || die "运行时无法导入"
say "下一步: 在 .env 或 compose 里设置 AIHUB_REX_RUNTIME=/data/rex-runtime-linux，然后 docker compose up -d"
