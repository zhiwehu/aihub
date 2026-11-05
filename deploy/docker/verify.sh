#!/bin/bash
# Prove the container can reach the native model tier on all three legs.
#
# Synthesises a short sentence with macOS `say`, then runs the server's own
# Pipeline code *inside* the container against the live config — this exercises
# the same HTTP calls a real voice session makes (ASR multipart → LLM SSE →
# TTS PCM), not just a TCP ping.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DATA="${AIHUB_DATA:-$ROOT/data}"
WAV="$DATA/.verify-16k.wav"
CONTAINER="${AIHUB_CONTAINER:-aihub-core}"

log() { printf '%s\n' "$*"; }
die() { printf '错误: %s\n' "$*" >&2; exit 1; }

command -v ffmpeg >/dev/null || die "需要 ffmpeg（brew install ffmpeg）"
docker inspect "$CONTAINER" >/dev/null 2>&1 || die "容器 $CONTAINER 不存在，先 docker compose up -d"

cleanup() { rm -f "$WAV"; }
trap cleanup EXIT

log "生成测试语音…"
tmp="$(mktemp -t aihub-verify).aiff"
/usr/bin/say -v Tingting -o "$tmp" "你好，我是小宝，今天天气不错。"
ffmpeg -v error -y -i "$tmp" -ar 16000 -ac 1 -f wav "$WAV"
rm -f "$tmp"

log "在容器内跑真实链路…"
docker exec -i "$CONTAINER" python - <<'PY'
import asyncio, json, wave
import aiohttp
from aihub_server.pipeline import Pipeline
from aihub_server.config import validate

config = validate(json.load(open('/data/settings.json')))

async def main():
    async with aiohttp.ClientSession() as http:
        p = Pipeline(config, http, runtime=None)

        with wave.open('/data/.verify-16k.wav', 'rb') as f:
            pcm = f.readframes(f.getnframes())
        print('  ASR  →', repr(await p.transcribe(pcm)), flush=True)

        reply = []
        async for piece in p.raw_chat([{'role': 'user', 'content': '用一句话介绍你自己'}],
                                      max_tokens=64):
            reply.append(piece)
        print('  LLM  →', repr(''.join(reply)), flush=True)

        total = 0
        async for block in p.speech('你好，我是小宝。'):
            total += len(block)
        print('  TTS  →', total, 'bytes PCM @16k', f'({total/32000:.2f}s)', flush=True)

asyncio.run(main())
PY

log "完成。"
