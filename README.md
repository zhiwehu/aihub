# aihub-common

AIHub 各服务共用的一小组无业务原语。**依赖图的叶子节点**：本包不 import 任何兄弟包。

| 模块 | 内容 | 谁在用 |
|---|---|---|
| `pcm.py` | `to_pcm16`：浮点/字节音频 → 16 kHz 单声道 s16le | server `input.py` `models.py`；models `diarize.py` |
| `speech_text.py` | `spoken_text`：去掉 UI emoji，避免语音引擎念出可访问性名称 | server `models.py`；models `tts_qwen.py` |
| `stamp.py` | `stamp_ms` / `stamp_text`：录音时间戳的双向转换 | server `recording.py` `session.py`；models `diarize.py` |
| `speaker.py` | `SpeakerTracker`：匿名说话人在线聚类；`normalize`、`SpeakerUnavailable` | server 录音期实时分轨；models 会后重分轨 |
| `errors.py` | `ProviderError`：模型提供方的统一错误码 | 两侧 |

`speaker.py` 只含**不含模型**的那一半：输入是 192 维声纹向量，输出是「说话人N」标签。
加载 SpeechBrain ECAPA 的那一半在 `aihub-models`（需要 torch），因为它必须跟着模型走。


## 为什么单独成库

这几处代码原本都在 `voicehub/` 里，但被服务和模型两边同时引用。拆分时如果不抽出来，
只能两边各复制一份——复制必然漂移。约 300 行的包换掉两条分叉，是成本最低的解法。

环境变量读写 `AIHUB_` 前缀，同时兼容拆分前的 `VOICEHUB_` 前缀（`AIHUB_` 优先）。

## 安装

```sh
pip install aihub-common
# 需要把 24 kHz / 48 kHz 音频重采样到 16 kHz 时：
pip install "aihub-common[resample]"
```

`numpy` 是硬依赖；`av` 只在 `source_rate != 16000` 时才被 import。

## 测试

```sh
PYTHONPATH=src python -m pytest tests -q
```

## 边界

**放进来**：纯函数，无状态、无网络、无模型、无文件 I/O。

**不要放进来**：

- VAD（`Silero`）、分段器（`Segmenter`）、编解码器（`AudioCodec`）——它们在 server 的音频流内联运行，延迟敏感，不是共享原语。
- 任何需要配置或数据目录的东西。
