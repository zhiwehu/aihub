# Intel Core Ultra 5 225H：Ubuntu / Debian Docker 部署

更新：2026-11-06。适用于 Ubuntu 24.04、Debian 12/13 的 x86_64 主机。
这是按当前代码和上游接口核对过的部署步骤，尚未在 225H 真机上完成端到端测试，
不包含实时率、首音延迟或 GPU/NPU 加速的实测承诺。

## 1. 选择部署方案

本文只部署两个 AIHub 容器，直接连接目标机器上已经运行的 LLM、ASR、TTS HTTP 服务。
不下载大模型，不安装新的模型服务，也不改变、启动或停止原有模型服务。

| 服务 | 内容 | 本机地址 |
| --- | --- | --- |
| core | AIHub 管理端、网页客户端入口、可选 ESP32 网关 | 8765 / 8768 / 8766 |
| processing | 录音后处理、转写、会议纪要；调用现有 ASR/LLM | 127.0.0.1:8790 |

部署前确认现有三个服务的 API 基础地址（含 `/v1`）、实际模型 ID、认证方式，以及
TTS 的音色和 PCM 采样率。不要仅凭端口推断模型或接口兼容性。本文的
8781 / 8782 / 8767 只是示例，必须替换成目标机器正在使用的地址。
AIHub 所需资源应在原模型服务之外预留，并根据录音长度和并发验收。

AIHub 镜像在目标 x86_64 主机上构建，不使用 Mac `.venv`、MLX 本地启动脚本或 macOS
`say`。模型是否使用 Intel CPU、GPU 或 NPU，保持目标机器现有服务的配置。

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

这里只装后处理的基础依赖：降噪使用镜像内的 ffmpeg；说话人重分轨需要额外的
torch/speechbrain，本例不安装，其他后处理功能不受影响。
每次重新执行 `prepare-context.sh` 都会重建上下文，因此更新时也要重新执行上述后处理
上下文和构建命令。首次构建需要能访问 Python 包源和 Debian 软件源。

## 4. 填写现有模型服务参数

创建私有 `.env`，初始化命令拒绝覆盖已有文件。下面不安装任何模型；先创建文件，
再把 `REPLACE_WITH_...` 和示例地址替换成现有服务的实际参数。URL 不带认证信息，
只填写包括 `/v1` 的 API 基础地址，不填写完整的 `chat/completions` 等路径。
本例 `.env` 的值使用普通文本，不加引号、不使用变量展开；API Key 单独保存。

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

`TTS_SAMPLE_RATE` 也要按原服务的真实 PCM 输出修改。创建私有 API Key 文件，
填写原服务要求的 Key；没有认证的服务可保留空值。不要重新生成或轮换原服务的 Key。
下面使用 `x` 模式，防止覆盖已有文件：

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

当前 AIHub 使用 `Authorization: Bearer <Key>`，如原服务使用其他协议，需使用已有
兼容网关或适配器。Key 文件遵循 Compose `env_file` 语法，含特殊字符时注意正确引用。
以下从刚编辑的 `.env` 生成首次配置，拒绝未替换的占位符，也拒绝覆盖已有
`settings.json`；不读取或打印 Key：

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

以下仅对刚生成的配置做容器路径转换：

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

`planner=llm` 是这个新部署的起步配置，不会自动迁移现有 REX 模型和适配器。
如果需要继续使用 REX，应另行迁移基础模型、适配器并安装匹配架构的 Linux 运行时，
验证工具规划后再切换；不要只把规划器开关改成 `rex`。已有
`build-rex-runtime.sh` 依赖原始运行时版本清单，不是全新 Linux 安装的一键入口。

## 5. 创建 Linux 专用 Compose

将以下内容保存为 `$HOME/aihub-deploy/compose.yaml`。这是本文独立方案，
**不同时运行仓库原有的 `deploy/docker/compose.yaml` 或 `start.sh`**。

采用 Linux host 网络，是因为当前后处理 CLI 监听 `127.0.0.1:8790`。
这里各容器共用宿主网络，`127.0.0.1` 可以互通，无需 `host.docker.internal`，
也不写 `ports:`。管理端和网页入口仍显式绑定回环地址。目标机器的现有模型即使只监听
宿主机 `127.0.0.1`，两个 AIHub 容器也可以访问，无需改变其监听设置。

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
      AIHUB_CLIENT_PUBLIC_PORT: "8768"
    volumes:
      - ${AIHUB_DEPLOY}/data:/data
      - ${AIHUB_DEPLOY}/music:/music:ro
    command: ["--data", "/data", "--host", "127.0.0.1", "--port", "8765",
              "--client-host", "127.0.0.1", "--client-port", "8768"]
```

core 与 processing 必须挂载**同一个** data 目录并使用同一个处理服务令牌。
两边读取 Key 的方式不同但来源相同：core 用 `settings.json` 里 `asr/llm/tts.key_env`
指向的变量，processing 用 `AIHUB_MINUTES_KEY_ENV` / `AIHUB_MEDIA_ASR_KEY_ENV`
指定的变量，这些变量都由 `model-keys.env` 提供。原服务不需要认证时，Key 留空即可，
请求不会带 `Authorization` 头。
不要把旧 AIHub 部署同时连接到这个 data 目录。`.env` 和 `model-keys.env` 均不上传
GitHub，不公开 `docker compose config` 的完整输出。修改实时语音模型设置后，重新连接
客户端；修改后处理使用的 ASR/LLM 地址或模型时，同时更新 `.env` 并重新创建 processing
容器。修改 Key 后重新创建两个 AIHub 容器。本文 Compose 不管理原有模型服务的生命周期。

## 6. 分步启动和验证

先确认原有 LLM、ASR、TTS 服务正在运行。用它们已有的健康检查和调用示例验证
地址、模型 ID、认证和音色，**不停止原有服务，也不要求释放其端口**。
AIHub 自己需要空闲的 8765、8768、8790，可选设备入口需要 8766。

需要核对的接口如下，基础 URL 和 Key 均使用第 4 节现有服务参数：

| 功能 | AIHub 发出的请求 | 必需响应 |
| --- | --- | --- |
| 实时 ASR、录音重转写 | `POST <ASR_URL>/audio/transcriptions`，multipart WAV + `model` | JSON `text` |
| 实时 LLM | `POST <LLM_URL>/chat/completions`，`stream=true` | SSE `choices[].delta.content` |
| 会议纪要 | 同一 LLM 接口，`stream=false` | `choices[0].message.content` |
| TTS | `POST <TTS_URL>/audio/speech`，`model/input/voice/response_format=pcm` | 单声道、16 位小端裸 PCM，采样率与设置一致 |

TTS 响应类型需为 `application/octet-stream`、`audio/pcm`、`audio/raw` 或 `audio/x-pcm`。
只有 WAV/MP3 输出或其他协议的服务不能直接当作这个接口使用。先确认已有兼容入口，
无需为此重新安装一套推理模型。若三项原服务都由同一网关提供，三个 URL 可以相同，
模型 ID、音色仍填写各自实际值。

```bash
ss -ltnp
cd "$HOME/aihub-deploy"
docker compose config --quiet
docker compose up -d processing core
docker compose ps
docker compose logs --tail=80 processing core
curl -f http://127.0.0.1:8765/api/status
```

core 健康检查成功只代表管理服务可用，不能替代模型接口验证。两个 AIHub 容器内的
URL 使用的是目标 Linux 主机的地址，而不是当前 Mac 的地址。不要运行 Mac 的
`model-host.sh`、`configure.sh` 来替换本步骤，也不要覆盖原模型服务配置。

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

需要网页 USB 刷机时，再把 `aihub-firmware` 的发布目录挂进 core，并告诉服务端
它在哪里。下面两段分别合并进 core 的 `environment` 和 `volumes`，路径换成这台
主机上 `flash/` 的绝对路径：

```yaml
      AIHUB_FIRMWARE_ROOT: /firmware
```

```yaml
      - /home/你的用户名/aihub-src/aihub-firmware/flash:/firmware:ro
```

保持只读。服务端只发布这些静态文件，不会接触设备；目录缺失时控制台隐藏刷机助手，
其余管理功能不受影响。改完重建一次 core 容器。

只对设备所在局域网放行该端口，且不要做公网端口转发。接入后按顺序验证问候、
天气/工具、播放音乐、暂停、继续、下一首和语音打断。协议自动测试通过不代表已经
验证这台 ESP32 的真实扬声器效果。远程网页用户建议通过 HTTPS 反向代理连接 8768，
管理入口继续私有；不要为了远程网页直接公开 8765。

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
| VAD 不可用 | `settings.json` 必须指向 `/app/assets/silero_vad_v6.onnx`，不能保留 Mac/宿主路径 |
| 模型连接拒绝 | 现有服务的地址、状态和认证；本文 host 网络可以访问宿主机 `127.0.0.1` |
| 后处理 401 / 403 | 两端处理令牌是否一致，是否误用了另一套 bridge 网络示例 |
| 有文字无声音 / TTS 格式错误 | HTTP TTS 的音色、采样率、`response_format=pcm` 和 Content-Type |
| 音乐目录不可用 | `docker compose exec core ls /music`，MCP 填写容器路径，检查磁盘权限 |
| REX 规划器不可用 | 本例应是 `planner=llm`；启用 REX 前必须有完整模型、适配器及 Linux 运行时 |
| 纪要影响聊天速度 | 先暂停纪要任务；沿用原模型服务的并发策略，AIHub 不保证跨服务抢占或优先级 |
| 语音响应慢 | 分别测 ASR、LLM、TTS 耗时与内存；检查原服务负载和资源竞争，不在本文另装推理服务 |

需要更新时先记录两个源码提交、现有模型服务参数、AIHub 镜像 ID，再备份。
构建新镜像使用新标签，不覆盖旧标签；客户端有变化时重新构建并安装完整产物。
重复第 3 节的 core/processing 构建步骤，用新标签更新 Compose，保留 `.env` 和 data。

做一致性备份前先停止相关容器，随后备份整个 data 目录和私有配置：

```bash
cd "$HOME/aihub-deploy"
docker compose stop
tar -czf "backups/runtime-$(date +%Y%m%d-%H%M%S).tar.gz" data .env model-keys.env compose.yaml
docker compose start
```

以上 stop/start 只作用于 core 和 processing，不影响原有 LLM、ASR、TTS。
备份含历史、凭证和录音，不上传公共仓库。回滚时停服务、换回旧镜像/配置；需要恢复
data 快照时，先另存升级后新增的录音和历史。不要执行 `down -v` 来“修复”问题。

## 10. 验证范围与参考

本仓库已验证 core 的接口契约、独立客户端产物校验、录音后处理 HTTP 契约及音乐
会话传输。本文 Compose 配置和配置生成步骤在交付前做静态/本地检查；原有服务的接口兼容性、
中文语音质量、225H 的资源占用与 ESP32 端到端效果需要在目标机器按第 6/8 节验收。
完成后记录机器内存、镜像摘要、模型版本、首字/首音延迟及 ASR 实时率，结合原有模型服务的负载定位耗时。

- [Intel 225H 官方规格](https://www.intel.com/content/www/us/en/products/sku/241749/intel-core-ultra-5-processor-225h-18m-cache-up-to-4-90-ghz/specifications.html)
- [Docker Linux host 网络](https://docs.docker.com/engine/network/drivers/host/)
- [Silero VAD 文件来源](https://github.com/SYSTRAN/faster-whisper/tree/master/faster_whisper/assets)
- [AIHub HTTP 后处理配置](../../packages/processing/docs/http-processing.md)
