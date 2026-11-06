# Intel Core Ultra 5 225H：Ubuntu / Debian 服务端 Docker 部署

更新：2026-11-06。Ubuntu 24.04、Debian 12/13，x86_64。
LLM / ASR / TTS 用机器上已有的 HTTP 服务，本文不装模型。

| 容器 | 作用 | 端口 |
| --- | --- | --- |
| core | 管理端、网页客户端入口、ESP32 网关 | 127.0.0.1:8765 / 0.0.0.0:8768 / LAN IP:8766 |
| processing | 后处理、转写、纪要 | 127.0.0.1:8790 |

网页客户端页面由 `aihub-client-web` 构建部署，连 core 的 8768。

## 1. 准备

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates python3 python3-venv
```

按 [Ubuntu](https://docs.docker.com/engine/install/ubuntu/) 或
[Debian](https://docs.docker.com/engine/install/debian/) 官方步骤装 Docker Engine 和
Compose 插件，然后：

```bash
mkdir -p "$HOME/aihub-src" && cd "$HOME/aihub-src"
git clone git@github.com:zhiwehu/aihub.git
cd aihub
./scripts/install.sh --dev
```

## 2. 构建镜像

```bash
umask 077
mkdir -p "$HOME/aihub-deploy/"{data,models,music,backups}
cd "$HOME/aihub-src/aihub"
curl -fL --retry 3 \
  https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/assets/silero_vad_v6.onnx \
  -o "$HOME/aihub-deploy/models/silero_vad_v6.onnx"
VOICE_VAD_MODEL="$HOME/aihub-deploy/models/silero_vad_v6.onnx" \
  ./deploy/docker/prepare-context.sh --no-client
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

```bash
cd "$HOME/aihub-deploy"
python3 - <<'PYENV'
import os, secrets
from pathlib import Path
lines = {
    'AIHUB_DEPLOY': str(Path.cwd()),
    'AIHUB_MODELS_TOKEN': secrets.token_urlsafe(32),
    'DEVICE_HOST': '192.168.1.50',
    'CLIENT_ORIGINS': '',
    'CLIENT_PUBLIC_URL': '',
    'ASR_URL': 'http://127.0.0.1:8781/v1',
    'ASR_MODEL': 'REPLACE_WITH_ACTUAL_ASR_ID',
    'LLM_URL': 'http://127.0.0.1:8782/v1',
    'LLM_MODEL': 'REPLACE_WITH_ACTUAL_LLM_ID',
    'TTS_URL': 'http://127.0.0.1:8767/v1',
    'TTS_MODEL': 'REPLACE_WITH_ACTUAL_TTS_ID',
    'TTS_VOICE': 'REPLACE_WITH_ACTUAL_VOICE',
    'TTS_SAMPLE_RATE': '24000',
}
fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    for k, v in lines.items():
        f.write(f'{k}={v}\n')
PYENV
nano .env
```

- `DEVICE_HOST`：换成主机固定局域网 IP（下文 192.168.1.50 同样替换）。
- `CLIENT_ORIGINS`：页面与 8768 不同源时填其 origin，如 http://192.168.1.50:8080，多个用逗号分隔。
- `CLIENT_PUBLIC_URL`：客户端页面地址，管理端生成连接码时显示。
- 模型 URL 只写到 `/v1`，不带认证和引号。

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

```bash
cd "$HOME/aihub-src/aihub"
.venv/bin/python - <<'PYCONFIG'
import subprocess
from pathlib import Path
root = Path.home() / 'aihub-deploy'
values = dict(line.split('=', 1) for line in (root / '.env').read_text().splitlines()
              if line.strip() and not line.lstrip().startswith('#'))
required = ('ASR_URL', 'ASR_MODEL', 'LLM_URL', 'LLM_MODEL',
            'TTS_URL', 'TTS_MODEL', 'TTS_VOICE', 'TTS_SAMPLE_RATE')
if any(not values.get(k) or 'REPLACE_WITH_' in values[k] for k in required):
    raise SystemExit('请先填写 .env 中现有模型服务的实际参数')
command = ['.venv/bin/python', 'deploy/linux/configure.py',
           '--output', str(root / 'data/settings.json'),
           '--vad-model', str(root / 'models/silero_vad_v6.onnx')]
for kind in ('asr', 'llm', 'tts'):
    for field in ('url', 'model'):
        command += [f'--{kind}-{field}', values[f'{kind}_{field}'.upper()]]
command += ['--tts-voice', values['TTS_VOICE'],
            '--tts-sample-rate', values['TTS_SAMPLE_RATE']]
subprocess.run(command, check=True)
PYCONFIG
```

```bash
python3 - <<'PYPATH'
import json
from pathlib import Path
p = Path.home() / 'aihub-deploy/data/settings.json'
v = json.loads(p.read_text())
v['audio']['vad_model'] = '/app/assets/silero_vad_v6.onnx'
v['tools'].update(planner='llm', music=True, music_directory='/music')
p.write_text(json.dumps(v, ensure_ascii=False, indent=2) + '\n')
PYPATH
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
      AIHUB_CLIENT_ORIGINS: "${CLIENT_ORIGINS}"
      AIHUB_CLIENT_PUBLIC_URL: "${CLIENT_PUBLIC_URL}"
    volumes:
      - ${AIHUB_DEPLOY}/data:/data
      - ${AIHUB_DEPLOY}/music:/music:ro
    command: ["--data", "/data", "--host", "127.0.0.1", "--port", "8765",
              "--client-host", "0.0.0.0", "--client-port", "8768",
              "--device-host", "${DEVICE_HOST:?set DEVICE_HOST}",
              "--device-bind", "${DEVICE_HOST:?set DEVICE_HOST}",
              "--device-port", "8766"]
```

host 网络让两个容器和宿主机上的模型服务直接互通，所以不写 `ports:`。

## 5. 启动

```bash
cd "$HOME/aihub-deploy"
docker compose config --quiet
docker compose up -d
docker compose ps
curl -f http://127.0.0.1:8765/api/status
ss -ltnp | grep -E '8765|8766|8768|8790'
```

管理端只监听回环，从本机访问 `http://127.0.0.1:8765`；远程用 SSH 转发：

```bash
ssh -N -L 8765:127.0.0.1:8765 用户名@192.168.1.50
```

防火墙只放行 8766、8768 和客户端页面端口，不要放行 8765。

## 6. 网页客户端

页面在 [`aihub-client-web`](https://github.com/zhiwehu/aihub-client-web) 构建部署。
不同源（比如 `http://192.168.1.50:8080`）时，把该 origin 写进 `CLIENT_ORIGINS`，
把页面地址写进 `CLIENT_PUBLIC_URL`，再 `docker compose up -d --force-recreate core`。

在管理端「客户端接入」生成连接码，页面里填：

- 服务地址：`http://192.168.1.50:8768`
- 连接码：管理端生成的那串

页面用 localhost / 127.0.0.1 打开才能用麦克风；局域网 HTTP 页面要 HTTPS 才行。
也可以把客户端 `dist/` 装进 core 镜像（`prepare-context.sh` 默认模式），由 8768 直接提供页面。

## 7. ESP32

在管理端配网并生成设备凭证，设备 WebSocket 地址：

```text
ws://192.168.1.50:8766/xiaozhi/v1/
```

OTA 授权用的是设备凭证，不是管理令牌。需要网页 USB 刷机时，把
`aihub-firmware/flash` 只读挂到 core 的 `/firmware`，并设置
`AIHUB_FIRMWARE_ROOT=/firmware`。

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
