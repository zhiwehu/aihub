# aihub-models

AIHub 的模型运行时：ASR / LLM / TTS 推理、声纹与重分轨、降噪、会议纪要，以及把长任务
排成异步 job 的服务。

**这里不 import 服务端代码**，两个方向的边界都是 HTTP。

## 目录

```text
src/aihub_models/
├── local.py          LocalModels：MLX 加载 + 单 GPU 工作线程
├── worker.py         单个模型的 loopback 进程（asr / llm / tts）
├── tts_qwen.py       Qwen3-TTS 常驻服务（:8767）
├── speaker.py        SpeechBrain ECAPA 声纹提取
├── diarize.py        会后重分轨（聚类 + 可选重新 ASR）
├── cleanup.py        ffmpeg 降噪
├── records.py        只读访问服务端的录音目录
├── media_jobs.py     异步 job：clean / diarize
├── service.py        job 服务 + 纪要 API 的 aiohttp 应用
└── minutes/          会议纪要：推理、抽取、渲染、存储、API
```

## 与服务端的边界

服务端负责**采集**、WAV 落盘、fsync、VAD 和设备协议；这里负责**推理**和**后处理**。
两边共享一个数据目录，但只有本仓库会读 `recordings/` 下的成品文件。

| 服务端做 | 这里做 |
|---|---|
| 麦克风音频流、VAD、分句 | 语音识别 |
| 写 `<id>.wav`、维护文件头、2 秒 fsync | 降噪、重分轨、纪要 |
| 设备 / WebSocket / OTA | 模型加载与显存管理 |
| 启动和停止 worker 进程（supervisor） | worker 进程本体 |

worker 的**生命周期**在服务端：`ServiceManager` 生成 token、记录 pid、绑定端口，然后
`python -m aihub_models worker ...`。本仓库只提供进程体和它的 HTTP 契约，不自己托管自己。

## 命令行

```sh
# 单个模型进程（通常由服务端 supervisor 启动）
python -m aihub_models worker --kind asr --model <模型ID> --port 8781 --service-id <hex>

# Qwen3-TTS 常驻服务
python -m aihub_models tts --port 8767

# 后处理 job 服务（含会议纪要），默认 8790
python -m aihub_models serve --data <data目录> --print-token

# 离线重分轨 / 降噪
python -m aihub_models diarize --data <data目录> --id <32hex> --mode asr --asr-model <模型ID>
python -m aihub_models clean --source in.wav --destination out.wav --profile mild
```

## HTTP 契约

### 模型 worker（每个模型一个进程）

统一 `Authorization: Bearer <worker token>`。

| 端点 | 请求 | 响应 |
|---|---|---|
| `GET /health` | — | `{service_id, model, ready, error, active, sample_rate}` |
| `POST /v1/audio/transcriptions` | multipart：`model`、`file`（16k 单声道 s16le WAV，≤30 s）、可选 `language: zh\|en` | `{text}` |
| `POST /v1/chat/completions` | `{model, messages, max_tokens, stream:true}` | SSE，`choices[].delta.content` |
| `POST /v1/audio/speech` | `{model, input, voice, response_format:"pcm"}` | `audio/pcm` 流 + `X-Audio-Sample-Rate` |

模型 ID 与语音都在启动时固定；不匹配一律拒绝，不做静默降级。

### 后处理服务

```http
POST /v1/media/jobs   {"kind":"clean","recording_id":"<32hex>","options":{"profile":"mild"}}
POST /v1/media/jobs   {"kind":"diarize","recording_id":"<32hex>","options":{"mode":"text","speakers":0}}
GET  /v1/media/jobs?recording_id=<32hex>
GET  /v1/media/jobs/{job_id}
POST /v1/media/jobs/{job_id}/cancel
```

job 状态：`queued | running | done | failed | cancelled | interrupted`。进程重启时未完成的
任务标为 `interrupted`，可重新提交。

会议纪要沿用自己的一套路由（有模板、证据和版本）：

```http
GET/POST      /v1/meeting-templates
PATCH/DELETE  /v1/meeting-templates/{template_id}
GET/POST      /v1/recordings/{id}/minutes
GET/PATCH/DELETE /v1/recordings/{id}/minutes/{job_id}
GET           /v1/recordings/{id}/minutes/{job_id}/export?format=md|txt
```

## 数据布局

`--data` 指向服务端的数据根目录：

```text
<data>/
├── recordings/        服务端写，这里读（降噪结果也写回这里）
├── media-jobs/        本服务的 job 状态
├── meeting_minutes/   纪要 job 与自定义模板
└── speaker-cache/     声纹模型缓存
```

所有路径都对着 `recordings/` 做校验，job 不可能被要求处理任意文件。

## 刻意没有放进来

| 内容 | 原因 |
|---|---|
| `speech_only`（裁剪到人声） | 需要与实时音频流内联的 Silero VAD，属服务端 |
| 录音采集、WAV 写盘、fsync | 实时流，过 RPC 会引入丢数据风险 |
| VAD 检测本身 | 延迟敏感，必须在音频流里 |
| 会话状态机 | 与服务端绑定 |
| worker 进程的启停与 pid 记账 | 服务端的数据目录与控制台按钮 |

## 安装

```sh
pip install aihub-models              # 只有 HTTP 客户端 / 后处理时
pip install "aihub-models[local]"     # 本地 MLX 推理
pip install "aihub-models[speaker]"   # 声纹（torch + speechbrain）
brew install ffmpeg                   # 降噪
```

模型权重不入库。首次使用前用官方 Hugging Face CLI 下载，本包只接受**已缓存**的模型，
不会偷偷联网下载。

## 测试

```sh
PYTHONPATH=src python -m pytest tests -q
```

测试不需要下载任何模型：语音相关的用例用假的 embedding 引擎，降噪用例在没装 ffmpeg 时自动跳过。

## 历史

从单体仓库 `miaoban-voicehub` 的 `voicehub/` 迁出，**不带旧提交历史**。迁出时做了三处
结构改动，行为保持不变：

1. `LocalModels` 从 `models.py` 拆到 `local.py`。
2. worker 的 ASR 调用不再构造服务端的 `Pipeline` + `ConfigFile`，直接走 MLX。
3. `rediarize` 不再自己拼配置和 `ServiceManager`，改为接收一个 `transcribe` 可调用对象。

原创代码 MIT（见 [LICENSE](LICENSE)）。
