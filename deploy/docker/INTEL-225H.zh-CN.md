# Intel Core Ultra 5 225H：Ubuntu / Debian 服务端 Docker 部署

更新：2026-11-06。Ubuntu 24.04、Debian 12/13，x86_64。
LLM / ASR / TTS 用机器上已有的 HTTP 服务，本文不装模型。

| 容器 | 作用 | 端口 |
| --- | --- | --- |
| core | 管理端、网页客户端入口、ESP32 网关 | 127.0.0.1:8765 / 0.0.0.0:8768 / 0.0.0.0:8766 |
| processing | 后处理、转写、纪要 | 127.0.0.1:8790 |

## 1. 准备

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates nodejs python3 python3-venv
```

按 [Ubuntu](https://docs.docker.com/engine/install/ubuntu/) 或
[Debian](https://docs.docker.com/engine/install/debian/) 官方步骤装 Docker Engine 和
Compose 插件，然后：

```bash
mkdir -p "$HOME/aihub-src" && cd "$HOME/aihub-src"
git clone git@github.com:zhiwehu/aihub.git
git clone https://github.com/zhiwehu/aihub-client-web.git
cd aihub && ./scripts/install.sh --dev
cd ../aihub-client-web && npm run build
cd ../aihub
.venv/bin/python scripts/install-client.py ../aihub-client-web/dist
```

页面地址：`http://<服务器IP>:8768/demo/`。

## 2. 构建镜像

```bash
umask 077
mkdir -p "$HOME/aihub-deploy/"{data,models,music,backups}
cd "$HOME/aihub-src/aihub"
curl -fL --retry 3 \
  https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/assets/silero_vad_v6.onnx \
  -o "$HOME/aihub-deploy/models/silero_vad_v6.onnx"
VOICE_VAD_MODEL="$HOME/aihub-deploy/models/silero_vad_v6.onnx" \
  ./deploy/docker/prepare-context.sh
docker build -t aihub-core:225h-20261106 deploy/docker/context
```

后处理：

```bash
mkdir -p deploy/docker/context/pkgs/aihub-models
cp packages/processing/{pyproject.toml,README.md,LICENSE} deploy/docker/context/pkgs/aihub-models/
cp -R packages/processing/src deploy/docker/context/pkgs/aihub-models/
cat > deploy/docker/context/Dockerfile.processing <<'EOF'
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
COPY pkgs/aihub-common /tmp/pkgs/common
COPY pkgs/aihub-models /tmp/pkgs/models
RUN pip install /tmp/pkgs/common /tmp/pkgs/models && rm -rf /tmp/pkgs
ENTRYPOINT ["python", "-m", "aihub_models"]
CMD ["serve", "--data", "/data", "--port", "8790"]
EOF
docker build -f deploy/docker/context/Dockerfile.processing \
  -t aihub-processing:225h-20261106 deploy/docker/context
```

## 3. 配置

`.env` 只给 Compose 用，4 个值：

```bash
cd "$HOME/aihub-deploy"
python3 - <<'PYENV'
import os, secrets
from pathlib import Path
lines = {
    'AIHUB_DEPLOY': str(Path.cwd()),
    'AIHUB_MODELS_TOKEN': secrets.token_urlsafe(32),
    'ASR_URL': 'http://127.0.0.1:8781/v1',
    'ASR_MODEL': 'REPLACE_WITH_ACTUAL_ASR_ID',
    'LLM_URL': 'http://127.0.0.1:8782/v1',
    'LLM_MODEL': 'REPLACE_WITH_ACTUAL_LLM_ID',
}
fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    for k, v in lines.items():
        f.write(f'{k}={v}\n')
PYENV
nano .env
```

`ASR_*`/`LLM_*` 只给后处理容器用（它的环境变量来自 Compose）。

TTS 不用配环境变量。首次启动生成的 `settings.json` 除 VAD 外沿用默认值，其中 TTS 默认是
macOS `say`，容器里用不了，所以只把这一项换成兼容 HTTP API；模型 ID、音色和采样率在
管理端「模型」页填（容器内要用 `127.0.0.1`，不能用宿主路径和 macOS 语音）。

```bash
mkdir -p "$HOME/aihub-deploy/data"
python3 - <<'PYSETTINGS'
import json
from pathlib import Path
p = Path.home() / 'aihub-deploy/data/settings.json'
if p.exists():
    raise SystemExit(f'{p} 已存在')
v = {
    'asr': {'provider': 'builtin', 'model': 'mlx-community/Qwen3-ASR-0.6B-8bit',
            'url': 'http://127.0.0.1:8000/v1', 'key_env': 'VOICE_ASR_KEY', 'language': 'Chinese'},
    'llm': {'provider': 'builtin', 'model': 'mlx-community/Qwen3-4B-Instruct-2507-4bit',
            'url': 'http://127.0.0.1:1234/v1', 'key_env': 'VOICE_LLM_KEY', 'max_tokens': 240},
    'tts': {'provider': 'http', 'model': 'tts-1', 'voice': 'Serena',
            'url': 'http://127.0.0.1:8767/v1', 'key_env': 'VOICE_TTS_KEY', 'sample_rate': 24000},
    'wake': {'mode': 'device', 'phrase': '小宝同学', 'idle_seconds': 30},
    'audio': {'barge_in': True, 'vad_model': '/app/assets/silero_vad_v6.onnx',
              'speech_threshold': 0.65, 'onset_ms': 160, 'silence_ms': 640,
              'max_utterance_seconds': 15},
    'system_prompt': '你是小宝，一个温暖、自然的语音伙伴。用简短中文回答。'
                     '只输出可直接朗读的正文，不使用emoji、颜文字、动作或表情旁白。',
    'retention_days': 30,
}
p.write_text(json.dumps(v, ensure_ascii=False, indent=2) + '\n')
p.chmod(0o600)
PYSETTINGS
```

声音回答前，在管理端「模型」页把 ASR/LLM 切到 HTTP API，填实际地址、模型 ID 和音色。

只有模型服务需要鉴权时才建 `model-keys.env`（没认证可跳过），Key 直接用原服务的：

```bash
python3 - <<'PYKEY'
from pathlib import Path
p = Path('model-keys.env')
with p.open('x') as f:
    f.write('VOICE_ASR_KEY=\nVOICE_LLM_KEY=\nVOICE_TTS_KEY=\n')
p.chmod(0o600)
PYKEY
nano model-keys.env
```

## 4. Compose

保存为 `$HOME/aihub-deploy/compose.yaml`：

```yaml
name: aihub-225h
services:
  processing:
    image: aihub-processing:225h-20261106
    network_mode: host
    restart: unless-stopped
    env_file: [model-keys.env]
    environment:
      AIHUB_MODELS_TOKEN: ${AIHUB_MODELS_TOKEN:?set in .env}
      AIHUB_MINUTES_PROVIDER: http
      AIHUB_MINUTES_URL: ${LLM_URL:?set LLM_URL}
      AIHUB_MINUTES_MODEL: ${LLM_MODEL:?set LLM_MODEL}
      AIHUB_MINUTES_KEY_ENV: VOICE_LLM_KEY
      AIHUB_MEDIA_ASR_PROVIDER: http
      AIHUB_MEDIA_ASR_URL: ${ASR_URL:?set ASR_URL}
      AIHUB_MEDIA_ASR_MODEL: ${ASR_MODEL:?set ASR_MODEL}
      AIHUB_MEDIA_ASR_KEY_ENV: VOICE_ASR_KEY
    volumes:
      - ${AIHUB_DEPLOY}/data:/data
  core:
    image: aihub-core:225h-20261106
    network_mode: host
    restart: unless-stopped
    env_file: [model-keys.env]
    environment:
      AIHUB_MODELS_URL: http://127.0.0.1:8790
      AIHUB_MODELS_TOKEN: ${AIHUB_MODELS_TOKEN:?set in .env}
      AIHUB_CLIENT_ORIGINS: http://127.0.0.1:8768,http://localhost:8768
    volumes:
      - ${AIHUB_DEPLOY}/data:/data
      - ${AIHUB_DEPLOY}/music:/music:ro
    command: ["--data", "/data", "--host", "127.0.0.1", "--port", "8765",
              "--client-host", "0.0.0.0", "--client-port", "8768",
              "--device-bind", "0.0.0.0", "--device-port", "8766"]
```

host 网络让两个容器和宿主机的模型服务直接互通，所以不写 `ports:`。

## 5. 启动

```bash
cd "$HOME/aihub-deploy"
docker compose config --quiet
docker compose up -d
docker compose ps
curl -f http://127.0.0.1:8765/api/status
ss -ltnp | grep -E '8765|8766|8768|8790'
```

远程管理用 SSH 转发（管理端只在回环）：

```bash
ssh -N -L 8765:127.0.0.1:8765 用户名@服务器局域网IP
```

防火墙只放行 8766 和 8768，不要放行 8765。

## 6. 网页客户端

页面已由 8768 提供，局域网任意电脑打开 `http://<服务器IP>:8768/demo/`，
「服务地址」保留页面默认值。

登录管理端（经上面的 SSH 转发打开 `http://127.0.0.1:8765`）需要管理员令牌：

```bash
docker compose exec core python -m aihub_server --data /data --print-admin-token
```

登录后在「模型」页填 ASR/LLM/TTS 实际模型 ID、音色和采样率；在「客户端接入」生成
连接码，填进客户端页面。

## 7. ESP32

设备连 `ws://<服务器IP>:8766/xiaozhi/v1/`。地址以管理端「设备连接」里显示的为准，
那里可以直接改设备地址，设备也会按 OTA 下发的地址拨号。

需要网页 USB 刷机时，把 `aihub-firmware/flash` 只读挂到 core 的 `/firmware`，
并设置 `AIHUB_FIRMWARE_ROOT=/firmware`。

## 8. 维护

```bash
cd "$HOME/aihub-deploy"
docker compose logs --since=10m --tail=150 core processing
docker compose stop
docker compose start
```

备份（含凭证和录音，不要外传）：

```bash
cd "$HOME/aihub-deploy"
docker compose stop
tar -czf "backups/runtime-$(date +%Y%m%d-%H%M%S).tar.gz" data .env model-keys.env compose.yaml
docker compose start
```

更新时用新镜像标签重建 core / processing，改 Compose 标签后 `up -d`，保留 `.env` 和
data。不要用 `down -v`。

## 9. 参考

- [Intel 225H 规格](https://www.intel.com/content/www/us/en/products/sku/241749/intel-core-ultra-5-processor-225h-18m-cache-up-to-4-90-ghz/specifications.html)
- [Docker host 网络](https://docs.docker.com/engine/network/drivers/host/)
- [AIHub HTTP 后处理配置](../../packages/processing/docs/http-processing.md)
