# Intel Core Ultra 5 225H：Ubuntu / Debian Docker 部署

更新：2026-11-06。适用于 Ubuntu 24.04、Debian 12/13 的 x86_64 主机。
这是按当前代码和上游接口核对过的部署步骤，尚未在 225H 真机上完成端到端测试，
不包含实时率、首音延迟或 GPU/NPU 加速的实测承诺。

## 1. 选择部署方案

本文提供单机 CPU 起步方案，四个服务均使用 Docker：

| 服务 | 内容 | 本机地址 |
| --- | --- | --- |
| core | AIHub 管理端、网页客户端入口、ESP32 网关 | 8765 / 8768 / 8766 |
| processing | 录音后处理、转写、会议纪要 | 127.0.0.1:8790 |
| llm | llama.cpp + Qwen2.5-3B-Instruct GGUF | 127.0.0.1:8080 |
| speech | Speaches CPU，Whisper ASR + Kokoro 中文 TTS | 127.0.0.1:8000 |

这是为了先跑通 Linux 的一套模型选择，不会保留 Mac 上 MLX 模型的声音和回答风格。
建议预留 16 GB 以上内存，32 GB 更方便同时运行和处理录音；预留约 30 GB 磁盘并为
录音另留空间。这是资源规划建议，不是已测得的最低要求。先用 3B、4K 上下文和单路
LLM 请求，跑通后再调整模型和并发。已有兼容的 HTTP 模型服务时，可跳过对应模型容器，
替换配置里的 URL、模型 ID、音色和 API Key。

225H 是 Intel 平台，不使用 `--local`、MLX、macOS `say` 或 CUDA 镜像。
本文先使用 CPU，不需要映射 `/dev/dri`。Intel GPU/NPU 需要独立的推理后端与驱动验证。

## 2. 安装依赖，获取代码

先按 [Ubuntu 官方步骤](https://docs.docker.com/engine/install/ubuntu/) 或
[Debian 官方步骤](https://docs.docker.com/engine/install/debian/) 安装 Docker Engine、
Buildx 和 Compose 插件。下面假定当前用户可以运行 `docker`，不要混用 Docker Desktop
和另一套 Engine。安装常规依赖：

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates python3 python3-venv ffmpeg nodejs npm
docker version
docker compose version
uname -m
node --version
```

`uname -m` 应为 `x86_64`。Node 使用 18 或更新版本；如果发行版自带版本太旧，先更新。
所有镜像在这台 Intel 主机上构建/拉取，不直接使用 Mac 构建的 arm64 镜像。

```bash
mkdir -p "$HOME/aihub-src"
cd "$HOME/aihub-src"
git clone git@github.com:zhiwehu/aihub.git
git clone git@github.com:zhiwehu/aihub-client-web.git
cd aihub
./scripts/install.sh --dev
cd ../aihub-client-web
npm test
npm run build
cd ../aihub
.venv/bin/python scripts/install-client.py "$HOME/aihub-src/aihub-client-web/dist"
```

以上 SSH 克隆要求你的 GitHub SSH Key 已配置。ESP32 固件源码无需安装到服务器；
需要网页 USB 刷机时，额外准备 `aihub-firmware` 的 `flash/` 发布目录，在后面的 Compose
中挂载并设置 `AIHUB_FIRMWARE_ROOT`。不要从 Mac 复制 `.venv`、REX 的 Python 运行时、
`models.env` 或整份旧 `settings.json` 来代替 Linux 安装。

## 3. 创建运行目录，构建 AIHub 镜像

本例把运行文件放在 `$HOME/aihub-deploy`，不放进 Git 仓库。
以下路径可整体替换，但配置和挂载必须保持对应。

```bash
umask 077
mkdir -p "$HOME/aihub-deploy/"{data,models,music,backups}
cd "$HOME/aihub-src/aihub"
curl -fL --retry 3 \
  https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/assets/silero_vad_v6.onnx \
  -o "$HOME/aihub-deploy/models/silero_vad_v6.onnx"
sha256sum "$HOME/aihub-deploy/models/silero_vad_v6.onnx"
VOICE_VAD_MODEL="$HOME/aihub-deploy/models/silero_vad_v6.onnx" ./deploy/docker/prepare-context.sh
docker build -t aihub-core:225h-20261106 deploy/docker/context
```

后处理不在 core 镜像中，需要单独构建。复用刚生成的最小上下文，仅添加后处理包，
避免把 `.venv`、录音、令牌和大模型发送给 Docker 构建器：

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

这里仅装基础后处理依赖；声纹识别、深度降噪等额外模型能力不随本例启用。
每次重新执行 `prepare-context.sh` 都会重建上下文，因此更新时也要重新执行上述后处理
上下文和构建命令。首次构建需要能访问 Python 包源和 Debian 软件源。

## 4. 准备模型和首次配置

下载 Qwen 官方 GGUF；该模型仅作为可运行的 CPU 起步示例，不是要求替换你已有模型。
如果网络受限，可以在其他机器下载后传入，文件名与 Compose 中保持一致。

```bash
curl -fL --retry 3 \
  https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf \
  -o "$HOME/aihub-deploy/models/chat.gguf"
sha256sum "$HOME/aihub-deploy/models/chat.gguf"
docker pull ghcr.io/ggml-org/llama.cpp:server
docker pull ghcr.io/speaches-ai/speaches:latest-cpu
```

固定本次拉取的镜像摘要，避免日后重启时不知不觉换上游版本。后续需要升级时再重新
拉取、记录新摘要并验证。该初始化命令拒绝覆盖已有 `.env`：

```bash
cd "$HOME/aihub-deploy"
python3 - <<'PY'
import os, secrets, subprocess
from pathlib import Path
def digest(image):
    return subprocess.check_output(
        ['docker', 'image', 'inspect', '--format', '{{index .RepoDigests 0}}', image],
        text=True).strip()
lines = {
    'AIHUB_DEPLOY': str(Path.cwd()),
    'AIHUB_MODELS_TOKEN': secrets.token_urlsafe(32),
    'LLM_IMAGE': digest('ghcr.io/ggml-org/llama.cpp:server'),
    'SPEECH_IMAGE': digest('ghcr.io/speaches-ai/speaches:latest-cpu'),
}
fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    for k, v in lines.items():
        f.write(f'{k}={v}\n')
PY
cd "$HOME/aihub-src/aihub"
.venv/bin/python deploy/linux/configure.py \
  --output "$HOME/aihub-deploy/data/settings.json" \
  --vad-model "$HOME/aihub-deploy/models/silero_vad_v6.onnx" \
  --asr-url http://127.0.0.1:8000/v1 --asr-model Systran/faster-whisper-small \
  --llm-url http://127.0.0.1:8080/v1 --llm-model aihub-chat \
  --tts-url http://127.0.0.1:8000/v1 --tts-model speaches-ai/Kokoro-82M-v1.0-ONNX \
  --tts-voice zf_xiaobei --tts-sample-rate 24000
```

配置生成器拒绝覆盖已有 `settings.json`。以下仅对刚生成的配置做容器路径转换：

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path.home() / 'aihub-deploy/data/settings.json'
v = json.loads(p.read_text())
v['audio']['vad_model'] = '/app/assets/silero_vad_v6.onnx'
v['tools'].update(planner='llm', music=True, music_directory='/music')
p.write_text(json.dumps(v, ensure_ascii=False, indent=2) + '\n')
PY
```

`planner=llm` 是这个新部署的起步配置，不会自动迁移现有 REX 模型和适配器。
如果需要继续使用 REX，应另行迁移基础模型、适配器并安装匹配架构的 Linux 运行时，
验证工具规划后再切换；不要只把规划器开关改成 `rex`。已有
`build-rex-runtime.sh` 依赖原始运行时版本清单，不是全新 Linux 安装的一键入口。

## 5. 创建 Linux 专用 Compose

将以下内容保存为 `$HOME/aihub-deploy/compose.yaml`。这是本文独立方案，
**不同时运行仓库原有的 `deploy/docker/compose.yaml` 或 `start.sh`**。

采用 Linux host 网络，是因为当前后处理 CLI 监听 `127.0.0.1:8790`。
这里各容器共用宿主网络，`127.0.0.1` 可以互通，无需 `host.docker.internal`，
也不写 `ports:`。管理端、网页入口和模型服务仍显式绑定回环地址。

```yaml
name: aihub-225h
services:
  llm:
    image: ${LLM_IMAGE:?initialize .env first}
    network_mode: host
    restart: unless-stopped
    volumes:
      - ${AIHUB_DEPLOY}/models/chat.gguf:/models/chat.gguf:ro
    command: ["--model", "/models/chat.gguf", "--alias", "aihub-chat",
              "--host", "127.0.0.1", "--port", "8080", "--ctx-size", "4096",
              "--parallel", "1", "--threads", "6", "--n-gpu-layers", "0"]
  speech:
    image: ${SPEECH_IMAGE:?initialize .env first}
    network_mode: host
    restart: unless-stopped
    environment:
      UVICORN_HOST: 127.0.0.1
      UVICORN_PORT: "8000"
      WHISPER__INFERENCE_DEVICE: cpu
      WHISPER__COMPUTE_TYPE: int8
      WHISPER__CPU_THREADS: "4"
      WHISPER__NUM_WORKERS: "1"
      PRELOAD_MODELS: '["Systran/faster-whisper-small","speaches-ai/Kokoro-82M-v1.0-ONNX"]'
    volumes:
      - speech-cache:/home/ubuntu/.cache/huggingface/hub
  processing:
    image: aihub-processing:225h-20261106
    network_mode: host
    restart: unless-stopped
    environment:
      AIHUB_MODELS_TOKEN: ${AIHUB_MODELS_TOKEN:?initialize .env first}
      AIHUB_MINUTES_PROVIDER: http
      AIHUB_MINUTES_URL: http://127.0.0.1:8080/v1
      AIHUB_MINUTES_MODEL: aihub-chat
      AIHUB_MEDIA_ASR_PROVIDER: http
      AIHUB_MEDIA_ASR_URL: http://127.0.0.1:8000/v1
      AIHUB_MEDIA_ASR_MODEL: Systran/faster-whisper-small
    volumes:
      - ${AIHUB_DEPLOY}/data:/data
  core:
    image: aihub-core:225h-20261106
    network_mode: host
    restart: unless-stopped
    environment:
      AIHUB_MODELS_URL: http://127.0.0.1:8790
      AIHUB_MODELS_TOKEN: ${AIHUB_MODELS_TOKEN:?initialize .env first}
      AIHUB_CLIENT_PUBLIC_PORT: "8768"
    volumes:
      - ${AIHUB_DEPLOY}/data:/data
      - ${AIHUB_DEPLOY}/music:/music:ro
    command: ["--data", "/data", "--host", "127.0.0.1", "--port", "8765",
              "--client-host", "127.0.0.1", "--client-port", "8768"]
volumes:
  speech-cache:
```

core 与 processing 必须挂载**同一个** data 目录并使用同一个处理服务令牌。
speech 的下载缓存使用 Docker 命名卷，保留镜像中预建目录的权限，避免非 root 用户
无法写入宿主目录。不要清理这个卷，除非准备重新下载语音模型。
不要把旧部署同时连接到这个 data 目录。`.env` 中有令牌，不上传 GitHub，也不要公开
`docker compose config` 的完整输出。本例模型端点无 API Key，只在本机可达；接外部
服务时，在相应容器的私有 `env_file` 中提供 `VOICE_ASR_KEY`、`VOICE_LLM_KEY`、
`VOICE_TTS_KEY`，后处理也要得到其使用的 ASR/LLM Key。

## 6. 分步启动和验证

先检查端口，确认没有旧服务占用 8000、8080、8765、8768、8790：

```bash
ss -ltnp
cd "$HOME/aihub-deploy"
docker compose config --quiet
docker compose up -d llm speech
docker compose logs --tail=60 llm speech
```

首次启动 speech 会下载模型，需要访问 Hugging Face；日志报下载失败时先解决网络或
缓存问题，不要反复启动 core 当作修复。等待模型下载完成后分别验证：

```bash
curl -f http://127.0.0.1:8080/health
curl -f http://127.0.0.1:8000/v1/models
curl -f http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"aihub-chat","messages":[{"role":"user","content":"请用一句中文问好"}],"max_tokens":40,"stream":false}'
curl -fN http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"aihub-chat","messages":[{"role":"user","content":"你好"}],"max_tokens":30,"stream":true}'
curl -f http://127.0.0.1:8000/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"model":"speaches-ai/Kokoro-82M-v1.0-ONNX","input":"你好，欢迎使用声桥。","voice":"zf_xiaobei","response_format":"pcm"}' \
  -o /tmp/aihub-tts.pcm
ffplay -f s16le -ar 24000 -ac 1 /tmp/aihub-tts.pcm
```

无声卡的服务器可以把测试文件传到有声卡的电脑检查。再录制一段中文并保存成
`/tmp/aihub-asr.wav`（16 kHz 单声道 WAV），运行：

```bash
curl -f http://127.0.0.1:8000/v1/audio/transcriptions \
  -F file=@/tmp/aihub-asr.wav -F model=Systran/faster-whisper-small -F language=zh
docker compose up -d processing core
docker compose ps
docker compose logs --tail=80 processing core
curl -f http://127.0.0.1:8765/api/status
```

LLM 应同时支持流式 `delta.content` 和非流式 `message.content`，ASR 返回 JSON `text`。
TTS 必须返回 **24 kHz、单声道、16 位小端裸 PCM**；AIHub 不把 WAV/MP3 响应当作裸 PCM。
core 健康检查成功只代表管理服务可用，不能替代上述三项模型验证。

在服务器本机打开 `http://127.0.0.1:8765`。其他电脑用 SSH 转发管理端和网页端：

```bash
ssh -N -L 8765:127.0.0.1:8765 -L 8768:127.0.0.1:8768 用户名@服务器局域网IP
```

在那台电脑打开 `http://127.0.0.1:8765`，创建网页客户端连接码，再打开
`http://127.0.0.1:8768/demo/`，填写服务地址 `http://127.0.0.1:8768` 和连接码。
先验证文字聊天，再允许麦克风，测试识别、回复、播放、打断；最后测试录音保存、
回听、转写和纪要。浏览器麦克风需要 localhost 或 HTTPS，局域网 HTTP 地址不能替代。

## 7. 音乐目录配置

把音乐放进宿主机 `$HOME/aihub-deploy/music`，MCP 设置中填写**容器路径** `/music`。
也可以填写 `/music/轻音乐` 等子目录。添加文件或切换已挂载范围内的子目录不需要
重新创建容器。

要使用另一块磁盘，先将 Compose 的音乐挂载改为实际宿主路径，例如：

```yaml
      - /mnt/media/Music:/music:ro
```

确认宿主目录存在且 Docker 可读，再执行 `docker compose up -d --force-recreate core`。
MCP 仍填写 `/music`。仅在 MCP 中填写一个未挂载的宿主路径，不会自动生成 Docker
挂载；也不需要给 AIHub 挂载 `docker.sock`。保存后用 MCP 的曲库扫描按钮验证。

## 8. 接入 ESP32

网页测试通过后，再为 core 的 `command` 追加以下参数，将示例 IP 换成这台 Linux
主机的固定局域网 IPv4 地址（不是容器地址，也不是 `127.0.0.1`）：

```yaml
              "--device-host", "192.168.1.50", "--device-bind", "192.168.1.50",
              "--device-port", "8766"
```

这些是追加到原 `command: [...]` 列表中的元素，需要把原列表末尾的 `]` 移到最后。
重建 core 容器，确认 `ss -ltnp` 的 8766 只监听这个局域网 IP，管理端仍只监听回环。
通过管理端的设备配网流程设置设备地址和逐设备凭证；WebSocket 地址为
`ws://192.168.1.50:8766/xiaozhi/v1/`。使用新版设备凭证时，OTA 也需要对应授权，
不要把管理令牌、网页连接码当作设备凭证。本例不配置 MQTT/UDP。

只对设备所在局域网放行该端口，且不要做公网端口转发。接入后按顺序验证问候、
天气/工具、播放音乐、暂停、继续、下一首和语音打断。协议自动测试通过不代表已经
验证这台 ESP32 的真实扬声器效果。远程网页用户建议通过 HTTPS 反向代理连接 8768，
管理入口继续私有；不要为了远程网页直接公开 8765。

## 9. 日常维护与排错

```bash
cd "$HOME/aihub-deploy"
docker compose logs --since=10m --tail=150 core processing llm speech
docker stats --no-stream
docker compose stop
docker compose start
```

| 现象 | 优先检查 |
| --- | --- |
| VAD 不可用 | `settings.json` 必须指向 `/app/assets/silero_vad_v6.onnx`，不能保留 Mac/宿主路径 |
| 模型连接拒绝 | 对应容器日志、模型下载是否完成、端口冲突；本文 host 网络使用 `127.0.0.1` |
| 后处理 401 / 403 | 两端处理令牌是否一致，是否误用了另一套 bridge 网络示例 |
| 有文字无声音 / TTS 格式错误 | HTTP TTS 的音色、采样率、`response_format=pcm` 和 Content-Type |
| 音乐目录不可用 | `docker compose exec core ls /music`，MCP 填写容器路径，检查磁盘权限 |
| REX 规划器不可用 | 本例应是 `planner=llm`；启用 REX 前必须有完整模型、适配器及 Linux 运行时 |
| 纪要影响聊天速度 | 先暂停纪要任务；LLM 单槽只限制并发，不保证实时聊天优先或抢占 |
| 语音响应慢 | 分别测 ASR、LLM、TTS 耗时与内存；降低模型大小/线程竞争后再测 |

需要更新时先记录两个源码提交、模型 SHA256、镜像摘要和当前镜像 ID，再备份。
构建新镜像使用新标签，不覆盖旧标签；客户端有变化时重新构建并安装完整产物。
重复第 3 节的 core/processing 构建步骤，用新标签更新 Compose，保留 `.env` 和 data。

做一致性备份前先停止相关容器，随后备份整个 data 目录和私有配置：

```bash
cd "$HOME/aihub-deploy"
docker compose stop
tar -czf "backups/runtime-$(date +%Y%m%d-%H%M%S).tar.gz" data .env compose.yaml
docker compose start
```

备份含历史、凭证和录音，不上传公共仓库。回滚时停服务、换回旧镜像/配置；需要恢复
data 快照时，先另存升级后新增的录音和历史。不要执行 `down -v` 来“修复”问题。

## 10. 验证范围与参考

本仓库已验证 core 的接口契约、独立客户端产物校验、录音后处理 HTTP 契约及音乐
会话传输。本文 Compose 配置和配置生成步骤在交付前做静态/本地检查；CPU 模型组合、
中文语音质量、225H 的资源占用与 ESP32 端到端效果需要在目标机器按第 6/8 节验收。
完成后记录机器内存、镜像摘要、模型版本、首字/首音延迟及 ASR 实时率，再决定是否
换更大模型或引入 Intel 加速。

- [Intel 225H 官方规格](https://www.intel.com/content/www/us/en/products/sku/241749/intel-core-ultra-5-processor-225h-18m-cache-up-to-4-90-ghz/specifications.html)
- [Docker Linux host 网络](https://docs.docker.com/engine/network/drivers/host/)
- [llama.cpp 官方容器](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md)
- [Qwen 官方 GGUF](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF)
- [Speaches 安装](https://speaches.ai/installation/)、[配置](https://speaches.ai/configuration/)、[语音合成](https://speaches.ai/usage/text-to-speech/)
- [Speaches 中文音色实现](https://github.com/speaches-ai/speaches/blob/master/src/speaches/executors/kokoro.py)、[PCM 响应实现](https://github.com/speaches-ai/speaches/blob/master/src/speaches/routers/speech.py)
- [Silero VAD 文件来源](https://github.com/SYSTRAN/faster-whisper/tree/master/faster_whisper/assets)
- [AIHub HTTP 后处理配置](../../packages/processing/docs/http-processing.md)
