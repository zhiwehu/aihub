#!/bin/bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
local_models=0;dev=0
for option in "$@"; do
  case "$option" in --local) local_models=1;; --dev) dev=1;; *) echo "Usage: $0 [--local] [--dev]" >&2;exit 2;; esac
done
python_bin="${AIHUB_PYTHON:-python3}"
[ -x "$ROOT/.venv/bin/python" ] || "$python_bin" -m venv "$ROOT/.venv"
processing="$ROOT/packages/processing"
if [ "$local_models" = 1 ]; then
  [ "$(uname -s)" = Darwin ] || { echo 'MLX local models require macOS; use HTTP on Linux.' >&2;exit 2; }
  processing="$processing[local]"
fi
server="$ROOT/packages/server"
[ "$dev" = 0 ] || server="$server[test]"
if command -v uv >/dev/null 2>&1; then
  installer=(uv pip install --python "$ROOT/.venv/bin/python")
else
  installer=("$ROOT/.venv/bin/python" -m pip install)
fi
"${installer[@]}" -e "$ROOT/packages/common" -e "$ROOT/packages/tools" -e "$processing" -e "$server"
