# Intel Core Ultra 5 225H：Ubuntu / Debian 服务端 Docker 部署

更新：2026-11-06。适用于 Ubuntu 24.04、Debian 12/13 的 x86_64 主机。
步骤按当前代码核对过，未在 225H 真机做端到端测试，也不承诺性能。

## 1. 选择部署方案

本文部署两个容器，连接机器上已有的 LLM、ASR、TTS HTTP 服务；不装模型，也不动原服务。
网页客户端不在部署范围，由 `aihub-client-web` 仓库单独构建。

| 服务 | 内容 | 本机地址 |
| --- | --- | --- |
| core | AIHub 管理端、可选 ESP32 网关 | 8765 / 8766 |
| processing | 录音后处理、转写、会议纪要；调用现有 ASR/LLM | 127.0.0.1:8790 |

先确认三个服务的 API 基础地址（含 `/v1`）、模型 ID、认证方式、TTS 音色和 PCM 采样率；
文中的 8781 / 8782 / 8767 只是示例。

## 2. 安装依赖，获取代码

按 [Ubuntu 官方步骤](https://docs.docker.com/engine/install/ubuntu/) 或
[Debian 官方步骤](https://docs.docker.com/engine/install/debian/) 安装 Docker Engine、
Buildx 和 Compose 插件。假定当前用户可直接运行 `docker`。安装常规依赖：

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates python3 python3-venv
docker version
docker compose version
uname -m
```

`uname -m` 应为 `x86_64`；镜像都在本机构建。

```bash
mkdir -p "$HOME/aihub-src"
cd "$HOME/aihub-src"
git clone git@github.com:zhiwehu/aihub.git
cd aihub
./scripts/install.sh --dev
```

需要配置好 GitHub SSH Key。ESP32 固件源码不用装到服务器；需要网页刷机时再准备
`aihub-firmware` 的 `flash/` 目录（见第 8 节）。

## 3. 创建运行目录，构建 AIHub 镜像

运行文件放在 `$HOME/aihub-deploy`。

```bash
umask 077
mkdir -p "$HOME/aihub-deploy/"{data,models,music,backups}
cd "$HOME/aihub-src/aihub"
curl -fL --retry 3 \
  https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/assets/silero_vad_v6.onnx \
  -o "$HOME/aihub-deploy/models/silero_vad_v6.onnx"
sha256sum "$HOME/aihub-deploy/models/silero_vad_v6.onnx"
VOICE_VAD_MODEL="$HOME/aihub-deploy/models/silero_vad_v6.onnx" \
  ./deploy/docker/prepare-context.sh --no-client
docker build -t aihub-core:225h-20261106 deploy/docker/context
```

后处理单独构建，复用上面的上下文：

```bash
cd "$HOME/aihub-src/aihub"
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

降噪用镜像内的 ffmpeg；说话人重分轨需要另装 torch/speechbrain。
`prepare-context.sh` 会重建整个上下文，重复本节时后处理包和构建也要重做。

## 4. 填写现有模型服务参数

创建私有 `.env`（命令拒绝覆盖已有文件），把地址和 `REPLACE_WITH_...` 换成实际值。
URL 只写到 `/v1`，不带路径、认证或引号；Key 放在单独的 `model-keys.env`。

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

`TTS_SAMPLE_RATE` 按原服务的真实 PCM 输出填。下面是 Key 文件，无认证可留空，
用原服务的 Key，不要重新生成：

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

AIHub 用 `Authorization: Bearer <Key>`；其他协议需要自己加兼容网关。
下面的命令从 `.env` 生成 `settings.json`，有未替换的占位符或文件已存在就退出：

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

把配置里的路径换成容器路径：

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

起步用 `planner=llm`。要换 REX 需先迁移模型、适配器和 Linux 运行时，不能只改开关。

## 5. 创建 Linux 专用 Compose

保存为 `$HOME/aihub-deploy/compose.yaml`，不要和仓库自带的 `compose.yaml` 或 `start.sh`
同时用。

用 host 网络：后处理只监听 `127.0.0.1:8790`，这样两个容器和宿主机上的模型服务直接互通，
也不用写 `ports:`。

```yaml
name: aihub-225h
services:
  processing:
    image: aihub-processing:225h-20261106
    network_mode: host
    restart: unless-stopped
    env_file: [model-keys.env]
    environment:
      AIHUB_MODELS_TOKEN: ${AIHUB_MODELS_TOKEN:?initialize .env first}
      AIHUB_MINUTES_PROVIDER: http
      AIHUB_MINUTES_URL: ${LLM_URL:?set existing LLM URL}
      AIHUB_MINUTES_MODEL: ${LLM_MODEL:?set existing LLM model}
      AIHUB_MINUTES_KEY_ENV: VOICE_LLM_KEY
      AIHUB_MEDIA_ASR_PROVIDER: http
      AIHUB_MEDIA_ASR_URL: ${ASR_URL:?set existing ASR URL}
      AIHUB_MEDIA_ASR_MODEL: ${ASR_MODEL:?set existing ASR model}
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
      AIHUB_MODELS_TOKEN: ${AIHUB_MODELS_TOKEN:?initialize .env first}
    volumes:
      - ${AIHUB_DEPLOY}/data:/data
      - ${AIHUB_DEPLOY}/music:/music:ro
    command: ["--data", "/data", "--host", "127.0.0.1", "--port", "8765",
              "--no-client"]
```

两个容器必须共用同一个 data 目录和同一个 `AIHUB_MODELS_TOKEN`。Key 由
`model-keys.env` 提供：core 按 `settings.json` 的 `key_env` 读取，processing 按两个
`*_KEY_ENV` 读取；无认证时留空。不要和旧部署共用 data 目录。改模型地址后重建对应
容器，改 Key 后重建两个。

## 6. 分步启动和验证

先确认三个模型服务在跑，用它们自带的健康检查核对地址、模型 ID、认证和音色。
AIHub 需要空闲的 8765、8790，设备入口另需 8766。

AIHub 需要的接口契约：

| 功能 | AIHub 发出的请求 | 必需响应 |
| --- | --- | --- |
| 实时 ASR、录音重转写 | `POST <ASR_URL>/audio/transcriptions`，multipart WAV + `model` | JSON `text` |
| 实时 LLM | `POST <LLM_URL>/chat/completions`，`stream=true` | SSE `choices[].delta.content` |
| 会议纪要 | 同一 LLM 接口，`stream=false` | `choices[0].message.content` |
| TTS | `POST <TTS_URL>/audio/speech`，`model/input/voice/response_format=pcm` | 单声道、16 位小端裸 PCM，采样率与设置一致 |

TTS 的 Content-Type 必须是 `application/octet-stream`、`audio/pcm`、`audio/raw` 或
`audio/x-pcm`；只有 WAV/MP3 的服务需要加适配层。三个 URL 可以相同，模型 ID 和音色
按实际填写。

```bash
ss -ltnp
cd "$HOME/aihub-deploy"
docker compose config --quiet
docker compose up -d processing core
docker compose ps
docker compose logs --tail=80 processing core
curl -f http://127.0.0.1:8765/api/status
```

core 健康检查只说明管理服务可用，模型接口仍需单独验证。

管理端在 `http://127.0.0.1:8765`（配置和记录，不是聊天客户端）。远程访问用 SSH 转发：

```bash
ssh -N -L 8765:127.0.0.1:8765 用户名@服务器局域网IP
```

确认管理端能打开、`/api/status` 正常，再按第 8 节接入设备做语音端到端验证。

## 7. 音乐目录配置

音乐放在 `$HOME/aihub-deploy/music`，MCP 里填容器路径 `/music`（子目录也可以）。
增删文件不用重建容器。

换磁盘就改挂载路径：

```yaml
      - /mnt/media/Music:/music:ro
```

确认 Docker 能读，`docker compose up -d --force-recreate core`，MCP 里仍写 `/music`。

## 8. 接入 ESP32

为 core 的 `command` 追加设备参数，IP 换成主机的固定局域网地址（不是 `127.0.0.1`）：

```yaml
              "--device-host", "192.168.1.50", "--device-bind", "192.168.1.50",
              "--device-port", "8766"
```

重建 core 后确认 8766 只监听该局域网 IP。在管理端配网并设置设备凭证；WebSocket 地址
是 `ws://192.168.1.50:8766/xiaozhi/v1/`。OTA 授权用设备凭证，不是管理令牌。
不配置 MQTT/UDP。

需要网页刷机时，把 `aihub-firmware/flash` 挂进 core：

```yaml
      AIHUB_FIRMWARE_ROOT: /firmware
```

```yaml
      - /home/你的用户名/aihub-src/aihub-firmware/flash:/firmware:ro
```

只读挂载；目录不存在时刷机助手隐藏，其他功能不受影响。

不要把 8766 或 8765 暴露到公网。接入后依次验证问候、工具、音乐、暂停/继续/下一首和
语音打断；真实扬声器效果要试听。

## 9. 日常维护与排错

```bash
cd "$HOME/aihub-deploy"
docker compose logs --since=10m --tail=150 core processing
docker stats --no-stream
docker compose stop
docker compose start
```

| 现象 | 优先检查 |
| --- | --- |
| VAD 不可用 | `settings.json` 必须指向 `/app/assets/silero_vad_v6.onnx`，不能是宿主路径 |
| 模型连接拒绝 | 现有服务的地址、状态和认证 |
| 后处理 401 / 403 | 两个容器的 `AIHUB_MODELS_TOKEN` 是否一致 |
| 有文字无声音 / TTS 格式错误 | HTTP TTS 的音色、采样率、`response_format=pcm` 和 Content-Type |
| 音乐目录不可用 | `docker compose exec core ls /music`，MCP 填容器路径，检查磁盘权限 |
| REX 规划器不可用 | 本例是 `planner=llm`；REX 需要完整模型、适配器及运行时 |
| 纪要影响聊天速度 | 纪要任务和白话聊天共用 LLM，按原服务的并发策略处理 |
| 语音响应慢 | 分别测 ASR、LLM、TTS 耗时与内存，检查原服务负载 |

更新前记录源码提交和镜像 ID。新镜像用新标签，重复第 3 节构建，改 Compose 里的标签，
保留 `.env` 和 data。

```bash
cd "$HOME/aihub-deploy"
docker compose stop
tar -czf "backups/runtime-$(date +%Y%m%d-%H%M%S).tar.gz" data .env model-keys.env compose.yaml
docker compose start
```

stop/start 只影响 core 和 processing。备份含凭证和录音，不要外传。回滚时换回旧镜像和
配置；不要用 `down -v` 修问题。

## 10. 验证范围与参考

Compose、配置生成和镜像构建已做本地检查；模型兼容性、语音质量、资源占用和 ESP32
效果要在 225H 上按第 6/8 节验收。验收时记录内存、镜像摘要、模型版本、首字/首音延迟
和 ASR 实时率。

- [Intel 225H 官方规格](https://www.intel.com/content/www/us/en/products/sku/241749/intel-core-ultra-5-processor-225h-18m-cache-up-to-4-90-ghz/specifications.html)
- [Docker Linux host 网络](https://docs.docker.com/engine/network/drivers/host/)
- [Silero VAD 文件来源](https://github.com/SYSTRAN/faster-whisper/tree/master/faster_whisper/assets)
- [AIHub HTTP 后处理配置](../../packages/processing/docs/http-processing.md)
