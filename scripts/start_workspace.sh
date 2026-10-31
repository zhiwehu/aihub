#!/bin/bash
# Start / stop the AIHub stack from a workspace directory that holds the repos:
#
#   aihub/{aihub-common,aihub-models,aihub-tools,aihub-server,aihub-web,aihub-firmware,.venv}
#
# The canonical copy lives here and is versioned; the workspace-root start.sh is a
# two-line wrapper that execs it.
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
WEB="$ROOT/aihub-web/public"
DATA="${AIHUB_DATA:-$ROOT/data}"
PORT="${AIHUB_PORT:-8765}"
MODELS_PORT="${AIHUB_MODELS_PORT:-8790}"
DEVICE_HOST="${AIHUB_DEVICE_HOST:-auto}"
DEVICE_PORT="${AIHUB_DEVICE_PORT:-8766}"
PIDFILE="$DATA/server.pid"
MEDIA_PIDFILE="$DATA/media.pid"
LOGFILE="$DATA/server.log"
MEDIA_LOG="$DATA/media.log"
TOKENFILE="$DATA/.models-token"
ASR_MODEL="${AIHUB_ASR_MODEL:-mlx-community/Qwen3-ASR-0.6B-8bit}"

BACKGROUND=0
WITH_MODELS=1
ACTION=start

usage() {
  cat <<'TXT'
用法: ./start.sh [选项]

  (无参数)          前台启动；Ctrl+C 停止
  -b, --background  后台启动
      --no-models   只起服务端，不加载模型（快速看界面时用）
      --all         显式表示全部启动（默认行为，保留是为了好读）
      --status      查看状态
      --stop        停止（含模型 worker 与后处理服务）
      --restart     先停后起
      --port N      控制台端口（默认 8765）
      --data DIR    数据目录（默认 <workspace>/data）
      --device-host auto|<ip>|none
                    设备监听地址；auto 自动探测局域网 IP（默认）
  -h, --help

环境变量: AIHUB_DATA AIHUB_PORT AIHUB_MODELS_PORT AIHUB_DEVICE_HOST AIHUB_DEVICE_PORT
TXT
}

while [ $# -gt 0 ]; do
  case "$1" in
    -b|--background) BACKGROUND=1 ;;
    --with-models|--all) WITH_MODELS=1 ;;
    --no-models)     WITH_MODELS=0 ;;
    --status)        ACTION=status ;;
    --stop)          ACTION=stop ;;
    --restart)       ACTION=restart ;;
    --port)          PORT="$2"; shift ;;
    --data)          DATA="$2"; PIDFILE="$DATA/server.pid"; MEDIA_PIDFILE="$DATA/media.pid"
                     LOGFILE="$DATA/server.log"; MEDIA_LOG="$DATA/media.log"
                     TOKENFILE="$DATA/.models-token"; shift ;;
    --device-host)   DEVICE_HOST="$2"; shift ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '%s\n' "$*"; }
fail() { printf '错误: %s\n' "$*" >&2; exit 1; }

alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

read_pid() { [ -f "$1" ] && cat "$1" 2>/dev/null || true; }

port_busy() { [ -n "$(lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1)" ]; }

http_ok() { curl -s -o /dev/null -m 3 "http://127.0.0.1:$1$2" 2>/dev/null; }

lan_ip() {
  for iface in en0 en1 en2; do
    ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
    [ -n "$ip" ] && { echo "$ip"; return; }
  done
  route -n get default 2>/dev/null | awk '/interface:/{print $2}' | head -1 | xargs -I{} ipconfig getifaddr {} 2>/dev/null || true
}

models_token() {
  if [ ! -f "$TOKENFILE" ]; then
    mkdir -p "$DATA"
    "$PY" -c 'import secrets,sys;open(sys.argv[1],"w").write(secrets.token_urlsafe(32))' "$TOKENFILE"
    chmod 600 "$TOKENFILE"
  fi
  cat "$TOKENFILE"
}

stop_stack() {
  say "停止模型 worker…"
  for kind in asr llm tts; do
    curl -s -o /dev/null -m 6 -X POST "http://127.0.0.1:$PORT/api/services/$kind/stop" 2>/dev/null || true
  done
  sleep 1
  for p in 8781 8782 8767; do
    pid=$(lsof -nP -iTCP:"$p" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done

  say "停止后处理服务…"
  pid=$(read_pid "$MEDIA_PIDFILE")
  if alive "$pid"; then kill "$pid" 2>/dev/null || true; sleep 1; fi
  rm -f "$MEDIA_PIDFILE"

  say "停止服务端…"
  pid=$(read_pid "$PIDFILE")
  if alive "$pid"; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do alive "$pid" || break; sleep .2; done
    alive "$pid" && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
  say "已停止。"
}

show_status() {
  pid=$(read_pid "$PIDFILE")
  if alive "$pid"; then
    say "服务端: 运行中 (pid $pid)  http://127.0.0.1:$PORT"
  else
    say "服务端: 未运行"
  fi
  if http_ok "$PORT" /api/status; then
    curl -s -m 3 "http://127.0.0.1:$PORT/api/status" | "$PY" -c 'import json,sys;d=json.load(sys.stdin);print("  在线会话: %s  VAD: %s" % (d.get("online"), d.get("vad_available")))' 2>/dev/null || true
    curl -s -m 3 "http://127.0.0.1:$PORT/api/services" | "$PY" -c '
import json,sys
try: rows=json.load(sys.stdin)
except Exception: sys.exit()
for s in rows: print("  模型 %-4s %s" % (s["kind"], s.get("state")))
' 2>/dev/null || true
  fi
  pid=$(read_pid "$MEDIA_PIDFILE")
  if alive "$pid"; then say "后处理服务: 运行中 (pid $pid)  127.0.0.1:$MODELS_PORT"; else say "后处理服务: 未运行"; fi
  if [ -d "$WEB" ]; then say "网页根目录: $WEB"; else say "网页根目录: 缺失 ($WEB)"; fi
}

if [ "$ACTION" = stop ]; then
  stop_stack
  exit 0
fi
if [ "$ACTION" = status ]; then
  show_status
  exit 0
fi

# ---- preflight -----------------------------------------------------------
[ -x "$PY" ] || fail "找不到 $VENV。先在工作区根目录执行:
  uv venv --python 3.13 .venv
  uv pip install --python .venv/bin/python -e ./aihub-common -e ./aihub-tools -e \"./aihub-models[local]\" -e ./aihub-server"
[ -d "$ROOT/aihub-server/src/aihub_server" ] || fail "工作区结构不对，缺少 aihub-server"
[ -d "$WEB" ] || say "提示: 没找到网页构建目录 $WEB，首页会显示说明页。"

if [ "$ACTION" = restart ]; then stop_stack; fi

pid=$(read_pid "$PIDFILE")
if alive "$pid"; then
  say "已有服务在运行 (pid $pid)。用 --restart 重启，或 --status 查看。"
  exit 0
fi
if port_busy "$PORT"; then
  fail "端口 $PORT 已被占用（可能是旧后端）。先停掉它:
  cd ~/ai/miaoban/realtime_backend && ./start.sh --stop
  lsof -ti:8781,8782,8767 | xargs kill"
fi
for p in 8781 8782 8767; do
  if port_busy "$p"; then
    fail "模型端口 $p 被占用。旧后端的 worker 通常不会随控制台退出，需要单独停:
  lsof -ti:8781,8782,8767 | xargs kill"
  fi
done

mkdir -p "$DATA"
chmod 700 "$DATA" 2>/dev/null || true
TOKEN="$(models_token)"

case "$DEVICE_HOST" in
  none) DEVICE_ARGS="" ;;
  auto) ip=$(lan_ip)
        if [ -n "$ip" ]; then DEVICE_ARGS="--device-host $ip --device-port $DEVICE_PORT"
        else say "提示: 没探测到局域网 IP，不开放设备监听（仅本机控制台可用）。"; DEVICE_ARGS=""; fi ;;
  *)    DEVICE_ARGS="--device-host $DEVICE_HOST --device-port $DEVICE_PORT" ;;
esac

# ---- start ---------------------------------------------------------------
export AIHUB_WEB_ROOT="$WEB"
export AIHUB_MODELS_URL="http://127.0.0.1:$MODELS_PORT"
export AIHUB_MODELS_TOKEN="$TOKEN"

say "启动后处理服务 (127.0.0.1:$MODELS_PORT)…"
nohup "$PY" -m aihub_models serve --data "$DATA" --port "$MODELS_PORT" \
  --token "$TOKEN" --asr-model "$ASR_MODEL" >"$MEDIA_LOG" 2>&1 &
echo $! > "$MEDIA_PIDFILE"

say "启动服务端 (http://127.0.0.1:$PORT)…"
# shellcheck disable=SC2086
nohup "$PY" -m aihub_server --data "$DATA" --port "$PORT" $DEVICE_ARGS >>"$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"

for _ in $(seq 1 40); do
  http_ok "$PORT" /api/status && break
  sleep .25
done
if ! http_ok "$PORT" /api/status; then
  say "服务端没有起来，日志尾部："
  tail -20 "$LOGFILE" >&2
  exit 1
fi

if [ "$WITH_MODELS" = 1 ]; then
  managed_kinds=$(curl -s -m 5 "http://127.0.0.1:$PORT/api/services" | "$PY" -c '
import json,sys
try: rows=json.load(sys.stdin)
except Exception: raise SystemExit
print(" ".join(s["kind"] for s in rows if s.get("managed")))' || true)
  external_kinds=$(curl -s -m 5 "http://127.0.0.1:$PORT/api/services" | "$PY" -c '
import json,sys
try: rows=json.load(sys.stdin)
except Exception: raise SystemExit
print(" ".join(s["kind"] for s in rows if not s.get("managed")))' || true)

  if [ -z "${managed_kinds:-}" ]; then
    say "没有可启动的本机模型（全部是系统或远端提供商），跳过。"
  else
    [ -z "${external_kinds:-}" ] || say "跳过非受管提供商: ${external_kinds}（系统或远端，无需启动）"
    say "拉起模型 worker: ${managed_kinds}（首次加载较慢，LLM 可能要一两分钟）…"
    for kind in $managed_kinds; do
      curl -s -o /dev/null -m 10 -X POST "http://127.0.0.1:$PORT/api/services/$kind/start" || true
    done
    for _ in $(seq 1 150); do
      settled=$(curl -s -m 3 "http://127.0.0.1:$PORT/api/services" | "$PY" -c '
import json,sys
try: rows=json.load(sys.stdin)
except Exception: print("0 0"); raise SystemExit
managed=[s for s in rows if s.get("managed")]
print(sum(1 for s in managed if s.get("state") in ("running","failed")), len(managed))' 2>/dev/null || echo "0 0")
      done_n=${settled% *}
      total_n=${settled#* }
      [ "${done_n:-0}" = "${total_n:-1}" ] && break
      sleep 2
    done
  fi
fi

show_status
if [ -n "${DEVICE_ARGS:-}" ]; then
  token=$("$PY" - "$DATA/auth.json" <<'PYEOF'
import json,sys
try: print(json.load(open(sys.argv[1]))['device_token'])
except Exception: pass
PYEOF
)
  say ""
  say "设备 OTA: http://${ip:-<局域网IP>}:$DEVICE_PORT/xiaozhi/ota/$token/"
  say "           ↑ 含设备令牌，是凭证；不要贴到截图、Issue 或公开地方。"
fi
say ""
say "日志: $LOGFILE   后处理: $MEDIA_LOG"
say "停止: ./start.sh --stop"

if [ "$BACKGROUND" = 0 ]; then
  say "前台运行中，Ctrl+C 停止。"
  trap 'echo; stop_stack; exit 0' INT TERM
  while alive "$(read_pid "$PIDFILE")"; do sleep 1; done
fi
