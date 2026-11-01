# Docker 部署（控制面）

把 **控制面**（`aihub-server` + 静态控制台）放进容器，**模型层留在宿主原生跑**，
两边通过 OpenAI 兼容的 HTTP 接口相连：

```
┌──────────────────────────── 容器 ────────────────────────────┐
│  aihub-server  :8765 控制台   :8766 喵伴设备入口              │
│      （--host 0.0.0.0 / --device-bind 0.0.0.0）              │
│  ↓ provider=http                                             │
└───────────────┼──────────────────────────────────────────────┘
                │  host.docker.internal
┌───────────────┼────────────── 宿主（macOS）──────────────────┐
│  asr worker  :8781   llm worker :8782   tts worker :8767     │
│  aihub-models serve :8790（降噪 / 重分轨 / 纪要）             │
└──────────────────────────────────────────────────────────────┘
```

## 为什么模型不容器化

`aihub-models` 的本地推理走 **MLX**（`mlx-lm` / `mlx-audio`），只能跑在 Apple
Silicon macOS 上；Docker Desktop 是 Linux 虚拟机，容器里没有 Metal 也没有 MLX
运行时 —— 宿主机是 M 系列 Mac 也救不了。默认 TTS 还依赖 `/usr/bin/say`。

所以这个镜像**故意不装 `aihub-models`**：模型继续在宿主上以原生进程运行，容器只负责
协议网关、会话、录音和网页控制台。

## 前置条件

- macOS + Docker Desktop（模型层必须原生跑）
- 工作区已按 `~/ai/aihub` 布局，`.venv` 可用，`data/settings.json` 已生成
  （没生成过就先跑一次 `./start.sh` 再停掉）
- `ffmpeg`（宿主，`brew install ffmpeg`）

## 启动

```sh
cd ~/ai/aihub/aihub-server/deploy/docker

# 1. 宿主侧模型层：起 8790 + asr/llm/tts worker，生成 env/models.env（含令牌）
./model-host.sh start

# 2. 把 settings.json 的三路 provider 切到 http，指向 host.docker.internal
./configure.sh

# 3. 组镜像上下文（从兄弟仓库收集源码 + 网页 + VAD 模型）并构建
./prepare-context.sh
docker build -t aihub-server:local context
docker compose up -d
```

控制台：<http://127.0.0.1:8765>

> `docker compose up -d --build` 也能一步到位；如果构建时碰到 buildx 写
> `~/.docker` 被限制（沙箱/CI 环境），就退回上面的 `docker build` 两步走。

## 验证

```sh
./verify.sh
```

它用 `say` 合成一句话，然后在**容器内**跑服务端自己的 `Pipeline` 代码，走真实的三条
链路（ASR multipart → LLM SSE → TTS PCM），实测输出形如：

```
  ASR  → '你好，我是小宝。今天天气不错。'
  LLM  → '你好，我是小宝，一个温暖又贴心的语音伙伴……'
  TTS  → 53760 bytes PCM @16k (1.68s)
```

## 日常操作

```sh
./model-host.sh status          # 模型层四个端口
docker compose ps               # 容器
docker compose logs -f          # 容器日志
docker compose down             # 只停容器，模型层不受影响
./model-host.sh stop            # 停模型层
```

## 喵伴 / 设备接入（8766）

容器发布 `8766:8766`，服务端用 `--device-bind 0.0.0.0` 在容器内监听；**对外宣告的地址**
不来自命令行，而来自 `data/connections.json`（原生模式写入过，例如
`192.168.2.122:8766`），所以设备拿到的还是局域网地址：

- OTA 响应里的 `ws://` 地址由**请求的 Host 头**推导，设备访问
  `http://<局域网IP>:8766/xiaozhi/ota/<令牌>/` 就会被告知 `<局域网IP>:8766`，过 NAT 不影响；
- 控制台「设备连接信息」下载里的地址取自 `connections.json`。

如果换了局域网 IP，在控制台里改设备连接地址即可（会写回 `connections.json`）。

一个例外：控制台的**固件配网**流程（`POST /api/clients/echoear-s3/prepare`）依赖枚举
本机网卡，容器里没有局域网网卡，会返回「请先让这台电脑连接可供喵伴使用的局域网」。
已经配好网、走 OTA 的设备不受影响。

## 关于登录（默认不需要）

原生模式控制台是「本机免登录」：`local_admin()` 要求对端是 loopback。容器化后请求从
docker 网关进来（`172.x`），peer 不再是 loopback，按原逻辑每次都要管理员令牌。

这里换了个等价做法：**容器把 8765 只发布到 `127.0.0.1`**（和原生 `start.sh` 绑
127.0.0.1 的暴露范围完全一致），再用 `--local-console` 让服务端把管理 API 的调用方
当作本机用户。控制台不再要求登录。

代价和约束：

- 8765 只能本机访问，局域网里的其他设备打不开控制台（原生模式本来也不行）；
- `--local-console` **只在 8765 绑定 loopback 时才安全**。如果你把端口改成
  `"8765:8765"` 暴露给局域网，必须同时去掉 `--local-console`，否则等于把管理员权限
  开放给整个局域网；
- 喵伴走的 8766 不受影响，仍然是设备令牌鉴权；`--local-console` 只作用于控制台 app。

如果确实需要局域网访问控制台，去掉 `--local-console` 并用管理员令牌登录：

```sh
.venv/bin/python -m aihub_server --data data --print-admin-token
```

## 已知限制

| 限制 | 说明 |
|---|---|
| 固件配网（首次联网）不支持 | `prepare` 要枚举本机网卡选局域网，容器里看不到宿主网卡；已配网的设备走 OTA 正常 |
| 8766 占用 | 端口发布在宿主，若别的服务（例如那个 `python -m http.server`）也占了 8766，需要先让位 |
| 模型仍在宿主 | 这是 MLX 的硬约束，不是本方案的取舍 |
| 模型名必须与 worker 一致 | worker 会校验请求里的 `model` 是否等于自己加载的那个；改 `settings.json` 的模型后要同步重启模型层 |
| 只支持 macOS 宿主 | 模型层要 MLX 和 `say` |
| 恢复原生模式 | `./configure.sh --restore` 把 provider 切回 `builtin`/`macos`，然后 `./model-host.sh stop` + `./start.sh` |

## 文件说明

| 文件 | 作用 |
|---|---|
| `prepare-context.sh` | 从 `aihub-common` / `aihub-tools` / `aihub-server` / `aihub-web` 收集源码、网页和 Silero VAD ONNX 到 `context/`（2–3 MB，避免把 `.venv` 和 `data/` 送给 daemon） |
| `Dockerfile` | `python:3.13-slim` + 三个本地包 + 网页 + VAD 模型 |
| `compose.yaml` | 端口 8765、挂载 `data/`、`env_file` 令牌 |
| `model-host.sh` | 宿主侧启动/停止模型层，生成 `env/models.env` |
| `configure.sh` | 备份并改写 `settings.json` 的 provider（`--restore` 可回滚） |
| `verify.sh` | 端到端验证 |

`context/` 与 `env/` 是生成物，已在 `.gitignore` 里；`env/models.env` 含 bearer
令牌，权限 600。
