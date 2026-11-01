#!/bin/bash
# Point the server config at the native model tier over HTTP.
#
#   ./configure.sh            # backup settings.json, switch to provider=http
#   ./configure.sh --restore  # put the last backup back
#
# The URLs must be reachable *from inside the container*, which is why they use
# host.docker.internal rather than 127.0.0.1. The model ids are left untouched:
# the workers validate that the requested model matches the one they loaded.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
PY="$ROOT/.venv/bin/python"
DATA="${AIHUB_DATA:-$ROOT/data}"
SETTINGS="$DATA/settings.json"
ASR_PORT=8781
LLM_PORT=8782
TTS_PORT=8767

say() { printf '%s\n' "$*"; }
die() { printf '错误: %s\n' "$*" >&2; exit 1; }

[ -f "$SETTINGS" ] || die "找不到 $SETTINGS"
# Fixed-name snapshot of the pre-docker config. Written once, never overwritten:
# re-running configure.sh keeps the original to restore from.
BACKUP="$DATA/settings.json.pre-docker"

if [ "${1:-}" = "--restore" ]; then
  [ -f "$BACKUP" ] || die "找不到 ${BACKUP}（没有切换到 docker 模式的记录）"
  cp "$BACKUP" "$SETTINGS"
  say "已恢复 $BACKUP → $SETTINGS"
  say "接着 ./model-host.sh stop 停掉模型层，再 ./start.sh 回原生模式。"
  exit 0
fi

if [ -f "$BACKUP" ]; then
  say "已有原始配置快照 ${BACKUP}（不覆盖）"
else
  cp "$SETTINGS" "$BACKUP"
  say "已备份原始配置 → $BACKUP"
fi

"$PY" - "$SETTINGS" "$ASR_PORT" "$LLM_PORT" "$TTS_PORT" <<'PY'
import json, sys, tempfile, os
from aihub_server.config import validate

path, asr_port, llm_port, tts_port = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
# settings.json stores the config document itself (no wrapper key).
config = json.load(open(path))

host = 'host.docker.internal'
config['asr'].update(provider='http', url=f'http://{host}:{asr_port}/v1')
config['llm'].update(provider='http', url=f'http://{host}:{llm_port}/v1')
config['tts'].update(provider='http', url=f'http://{host}:{tts_port}/v1',
                     voice='Serena', sample_rate=24000)

value = validate(config)
fd, name = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.settings-')
with os.fdopen(fd, 'w') as f:
    json.dump(value, f, ensure_ascii=False, indent=2)
    f.flush(); os.fsync(f.fileno())
os.replace(name, path)
print('已切换 provider=http:')
for kind in ('asr', 'llm', 'tts'):
    print(f"  {kind:4} {value[kind]['url']}  model={value[kind]['model']}  voice={value[kind].get('voice','-')}")
PY

say
say "提示: 恢复原生模式用 ./configure.sh --restore"
