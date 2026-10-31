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

## 启动

```sh
pip install aihub-server
aihub-server --data ./data --device-host <局域网IP> --device-port 8766
```

仅本机控制台时省略 `--device-host`。设备接入需要设备令牌：

```sh
aihub-server --data ./data --print-device-token
```

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
