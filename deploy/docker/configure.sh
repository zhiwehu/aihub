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
ROOT="$(cd "$HERE/../.." && pwd)"
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

"$PY" - "$SETTINGS" "$ASR_PORT" "$LLM_PORT" "$TTS_PORT" "$HERE/.env" "$DATA/docker-mounts" <<'PY'
import ipaddress, json, os, subprocess, sys, tempfile
from pathlib import Path
from aihub_server.config import validate

path, asr_port, llm_port, tts_port, env_path, mounts_root = sys.argv[1:7]
# settings.json stores the config document itself (no wrapper key).
config = json.load(open(path))

host = 'host.docker.internal'
config['asr'].update(provider='http', url=f'http://{host}:{asr_port}/v1')
config['llm'].update(provider='http', url=f'http://{host}:{llm_port}/v1')
config['tts'].update(provider='http', url=f'http://{host}:{tts_port}/v1',
                     voice='Serena', sample_rate=24000)


# Bind-mount the music and file folders at their own host paths, so the paths
# saved in settings.json stay valid in both deployment modes. compose reads these
# two variables from .env for interpolation; missing folders fall back to the data
# directory so the mounts never fail.
def host_dir(value, name):
    # AIHUB_MUSIC_DIR / AIHUB_FILES_DIR win over the console setting, for people
    # who would rather keep the paths out of settings.json.
    raw = (os.environ.get('AIHUB_' + name.upper() + '_DIR') or value or '').strip()
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.is_dir():
            return str(candidate)
    fallback = Path(mounts_root) / name
    fallback.mkdir(parents=True, exist_ok=True)
    return str(fallback)

music_dir = host_dir(config['tools'].get('music_directory'), 'music')
files_dir = host_dir(config['tools'].get('file_directory'), 'files')

# The container only sees its own bridge interface, so the address devices are
# told to dial has to come from the host. Without this the wizard used to write
# 172.x into the device's NVS, which no device can reach.
def lan_address():
    for iface in ('en0', 'en1', 'en2', 'en16'):
        try:
            result = subprocess.run(['ipconfig', 'getifaddr', iface],
                                    capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            continue
        raw = (result.stdout or '').strip()
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if address.is_private and not (address.is_loopback or address.is_link_local):
            return raw
    return ''

device_host = lan_address()
Path(env_path).write_text(f'AIHUB_MUSIC_DIR={music_dir}\n'
                          f'AIHUB_FILES_DIR={files_dir}\n'
                          f'AIHUB_DEVICE_HOST={device_host}\n')
if device_host:
    preference = Path(path).parent / 'connections.json'
    try:
        saved = json.loads(preference.read_text())
    except (OSError, ValueError):
        saved = {'mqtt_enabled': False}
    saved.update(device_enabled=True, device_host=device_host, device_port=8766)
    saved.setdefault('mqtt_enabled', False)
    preference.write_text(json.dumps(saved, ensure_ascii=False, indent=2))
    print(f'设备入口地址: {device_host}:8766（已写入 connections.json）')
else:
    print('设备入口地址: 未探测到局域网地址（en0/en1/en16），设备入口将使用 connections.json 里的旧值')
print('挂载目录:')
print(f'  音乐 {music_dir} (只读)')
print(f'  文件 {files_dir} (读写)')

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
