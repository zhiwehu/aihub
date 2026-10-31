# aihub-server

AIHub 的实时语音服务端：WebSocket / MQTT 协议网关、会话状态机、录音采集、配置与
对话存储、以及本地管理控制台 API。

**这个进程不加载任何模型。** 推理和媒体后处理都在 `aihub-models`，工具能力在同进程的
`aihub-tools`，共享原语在 `aihub-common`。

## 依赖方向

```
aihub-web ──HTTP/WS──┐
                     ├──> aihub-server ──HTTP──> aihub-models
aihub-firmware ──WS──┘           │
                                 └──> aihub-tools（同进程）──> aihub-common
                                        aihub-server ─────────> aihub-common
```

服务端**不 import** `aihub_models`，只通过 HTTP；但它和 `aihub_tools` 同进程。

## 目录

```text
src/aihub_server/
├── __main__.py / app.py      入口与应用组装
├── context.py?               见下
├── audio.py                  VAD（Silero）、分段器、Opus/PCM 编解码
├── input.py                  单连接的音频输入与录音切段
├── session.py                会话状态机（含录音模式）
├── pipeline.py               ASR/LLM/TTS 的 HTTP 适配器（不含模型）
├── models_client.py          到 aihub-models 的客户端（job + 纪要代理）
├── minutes_proxy.py          纪要 API 反向代理
├── services.py               模型 worker 进程的启动、记账与回收
├── recording.py / recording_api.py   录音落盘与 HTTP
├── store.py / config.py      会话存储与配置快照
├── connections.py / provisioning.py  监听器启停与局域网准备
├── mqtt_*.py                 MQTT + UDP 传输（可选）
├── device_mcp.py             设备端 MCP 通道
├── clients.py / device_backups.py / firmware_release.py   客户端目录、备份、镜像校验
└── *_api.py                  管理端点
```

## 关键设计

**模型只在另一个进程里。** `pipeline.py` 只剩三条路径：`builtin`（本机受管 worker）、
`http`（远端兼容接口）、`macos`（系统 `say`）。进程内 MLX 加载已随拆分删除——这条分支
在服务端本来就不可达，`config.py` 一直把 `provider='mlx'` 归一化成 `builtin`。

**`Runtime` 取代了杂物袋对象。** 原来 `app.py` 往一个 `LocalModels` 实例上挂了十几个
属性当依赖注入容器，工具层通过 `pipeline.local` 取用，依赖完全隐形。现在是显式的
`Runtime`，工具层读 `pipeline.runtime`，契约写在 `aihub_tools.context` 的 Protocol 里。

**后处理是 job，不是调用。** 降噪、重分轨、会议纪要都提交到 `aihub-models` 的服务：

```sh
export AIHUB_MODELS_URL=http://127.0.0.1:8790
export AIHUB_MODELS_TOKEN=<serve 启动时打印的令牌>
```

没配置时相关端点返回 503 并说明原因，不会静默挂起。

**网页客户端不在这个包里。** 服务端从 `AIHUB_WEB_ROOT`（默认 `<data>/web`）提供构建产物；
没有构建时首页显示一行说明。

## 快速开始

本仓库是运行入口。六个仓库是平级目录，虚拟环境放在它们的父目录里：

```sh
cd ~/ai/aihub
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python \
  -e ./aihub-common -e ./aihub-tools -e "./aihub-models[local]" -e ./aihub-server \
  pytest
```

`[local]` 装上 MLX 推理（`mlx-lm`、`mlx-audio`）。**声纹不在里面**：发言人间隔需要
`aihub-models[speaker]`（torch + speechbrain，体积很大），不装时录音照常工作，
只是没有说话人标签，页面会提示 `recording.speaker_unavailable`。

### 首次准备模型

模型权重不进仓库，只接受已缓存的本地副本：

**VAD** 是另一件事：它必须内联在音频流里，所以留在服务端。默认查找
`faster_whisper` 包自带的 `silero_vad_v6.onnx`；也可以显式指定：

```sh
export AIHUB_VAD_MODEL=/absolute/path/silero_vad.onnx
```

没有 VAD 时文字对话仍可用，语音会明确报错。

```sh
.venv/bin/hf download mlx-community/Qwen3-ASR-0.6B-8bit
.venv/bin/hf download mlx-community/Qwen3-4B-Instruct-2507-4bit
.venv/bin/hf download mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit
```

### 一键启动

工作区根目录的 `start.sh` 包好了一切（脚本本体在
[`scripts/start_workspace.sh`](scripts/start_workspace.sh)，受版本管理）：

```sh
./start.sh                 # 全部启动：后处理服务 + 服务端 + asr/llm/tts
./start.sh --background    # 同上，后台常驻
./start.sh --tts qwen      # 语音合成切到本机 Qwen3-TTS（只需一次，写进配置）
./start.sh --tts system    # 切回 macOS 自带的 say
./start.sh --no-models     # 只起服务端，不加载模型（只想看界面时用）
./start.sh --status
./start.sh --stop
./start.sh --restart
```

**默认的 TTS 是 macOS `say`**（`tts.provider = 'macos'`），不需要任何模型，所以新数据
目录首次启动时听到的是 Tingting。想要本机的 Qwen3-TTS 就加一次 `--tts qwen`：它通过
配置接口把 `provider` 改成 `builtin`、写进 `settings.json`，之后每次都生效。

**默认就是全部启动。** 只对 `provider=builtin` 的模型发起启动——TTS 默认是 macOS
`say`（`system`），不会去等它，所以不会白等到超时。

它会：检查 venv、探测局域网 IP、生成并复用后处理服务令牌、启动后处理服务和
服务端、拉起受管模型 worker、打印设备 OTA 地址。端口被旧后端占用时直接给出停止
命令，不会让你对着 `service_port_in_use` 猜。

### 手动启动


```sh
export AIHUB_WEB_ROOT="$HOME/ai/aihub/aihub-web/public"
export AIHUB_MODELS_TOKEN="$(uuidgen)"        # 只在需要纪要/降噪时用
.venv/bin/python -m aihub_server \
  --data "$HOME/ai/aihub-data" --port 8765 \
  --device-host <你的局域网IP> --device-port 8766
```

`--data` 指向的目录不存在时会自动生成默认 `settings.json`：ASR/LLM 用本地 Qwen，
TTS 默认是 macOS `say`（Tingting，不加载模型，最快能出声）。

### 拉起模型 worker

```sh
for kind in asr llm tts; do
  curl -s -X POST "http://127.0.0.1:8765/api/services/$kind/start"
done
curl -s http://127.0.0.1:8765/api/services
```

`state` 从 `starting` 变 `running` 即就绪（ASR 实测约 10 秒，LLM 冷启动更久）。
也可以点控制台「模型与语音」里的按钮。

### 可选：后处理服务

纪要、降噪、重分轨需要它：

```sh
.venv/bin/python -m aihub_models serve \
  --data "$HOME/ai/aihub-data" --asr-model mlx-community/Qwen3-ASR-0.6B-8bit
```

服务端和它必须共用同一个 `AIHUB_MODELS_TOKEN`；没配时相关端点返回 503。

### 端口

| 端口 | 用途 |
|---|---|
| 8765 | 管理控制台 |
| 8766 | 设备 WebSocket（需 `--device-host`） |
| 8781 / 8782 / 8767 | ASR / LLM / TTS worker（由 supervisor 启动） |
| 8790 | 后处理服务（可选） |

模型 worker 的端口是固定的，**同时运行旧后端会冲突**（旧系统占着 8781/8782/8767）。

### 设备令牌

```sh
.venv/bin/python -m aihub_server --data "$HOME/ai/aihub-data" --print-device-token
```

令牌存在 `<data>/auth.json`，不进仓库。设备需要把 OTA 地址指向新服务端的
`http://<局域网IP>:8766/xiaozhi/ota/<令牌>/`。

## 测试

```sh
PYTHONPATH=src python -m pytest tests -q
```

测试不加载模型：模型 worker 用 `tests/fake_model_worker.py`，媒体后处理用桩。

## 迁移说明

从单体仓库 `miaoban-voicehub` 的 `realtime_backend/voicehub/` 迁出，**不带旧提交历史**。
迁出过程中的主要改动：

1. `models.py` → `pipeline.py`，删掉 `LocalModels` 和不可达的 mlx 分支。
2. `self.local`（依赖注入杂物袋）→ 显式 `Runtime`；工具层改读 `pipeline.runtime`。
3. 会议纪要 → 代理到 `aihub-models`，外部路径不变，网页客户端不用改。
4. `rediarize` / `clean_wav` 的进程内调用 → `aihub-models` 的 job。
5. 静态文件不再随包分发。
6. `DeviceMCPError` 改为从 `aihub_tools.errors` 导入，全系统只有一个类型。
7. 子进程环境白名单加回 `PYTHONPATH`，否则 src 布局下 worker 起不来（这个失败只在运行期暴露）。

### 已知失败用例

| 用例 | 状态 |
|---|---|
| `test_wake_phrase_alone_activates_without_creating_empty_reply` | 拆分前就存在，与本轮无关 |

其余 259 项通过（含 18 个子测试）。

原创代码 MIT（见 [LICENSE](LICENSE)）。
