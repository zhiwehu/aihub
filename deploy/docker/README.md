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

## 音乐 / 文件整理目录

这两个工具吃的是本机目录，容器默认看不到。做法是**把宿主目录挂到容器内完全相同的
绝对路径**，这样 `settings.json` 里存的路径两种模式都成立，不需要来回改配置：

```yaml
- "${AIHUB_MUSIC_DIR}:/${AIHUB_MUSIC_DIR}:ro"    # 只读：只列目录和播放
- "${AIHUB_FILES_DIR}:/${AIHUB_FILES_DIR}"       # 读写：整理要移动文件
```

这两个变量由 `configure.sh` 写进 `deploy/docker/.env`（compose 会自动读取）：

1. 优先用环境变量 `AIHUB_MUSIC_DIR` / `AIHUB_FILES_DIR`；
2. 否则取 `settings.json` 里的 `tools.music_directory` / `tools.file_directory`；
3. 都没设时退回到 `data/docker-mounts/{music,files}`（自动创建的空目录），保证挂载不会失败。

所以正常流程是：先在网页里把目录设成宿主路径（例如 `/Users/huzhiwei/Downloads`），再跑
`./configure.sh`，然后 `docker compose up -d`。改了目录后重跑 `./configure.sh` 即可。

容器内实测（`docker run` 挂载后直接调用工具）：

```
文件整理 scan : 448 个文件（图片 118 · 文档 190 · 视频 47 · 压缩包 28 · 音频 3 …）
音乐 search   : Alan Walker 曲目正常列出
只读挂载      : 往音乐目录写文件被拒绝
```

注意：

- 文件整理目录是**读写**挂载，容器因此能移动你 `Downloads` 里的文件——这本来就是它的
  工作，但意味着这个容器对那个目录有写权限。
- 音乐目录是只读挂载，播放只是读取文件。
- 目录不在 Docker Desktop 的文件共享白名单里会挂载失败；`/Users` 默认是共享的。

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

## 设备地址（喵伴连哪个 IP）

容器只能看到自己的 `eth0`，所以网页「配网」按钮枚举网卡时会拿到 `172.x` —— 早期版本就是
把这个地址写进了设备的 NVS，导致喵伴连不上。现在：

- 容器里 `interfaces()` 直接返回空，但「配网」会用服务端宣告的地址（下面的
  `AIHUB_DEVICE_HOST`）继续走完流程——它正是设备要拨的地址；
- 只有连宣告地址都没有时，才会提示「服务端运行在容器里，看不到宿主的局域网网卡」；
- `configure.sh` 在宿主上探测局域网地址（`ipconfig getifaddr en0/en1/en2/en16`，只接受私有
  地址），写进 `.env` 的 `AIHUB_DEVICE_HOST`，同时修正 `data/connections.json`；
- compose 把它作为 `--device-host` 传给服务端（监听仍然是 `--device-bind 0.0.0.0`）。

**换了网络之后**：重跑 `./configure.sh`，然后用 USB 向导重新刷一次连接配置——设备 NVS 里存
的是上一次刷进去的地址，不重刷不会自己更新。

## 固件刷写助手（USB 配网）

控制台的 USB 向导不是网页自带的，它直接 `import('/firmware/echoear-installer.js')`
——模块来自 `aihub-firmware`。容器里没有这个目录，所以 compose 把
`aihub-firmware/flash` 只读挂到 `/firmware`，并设置 `AIHUB_FIRMWARE_ROOT=/firmware`
（和原生 `start.sh` 里的设置对应）。目录很小（约 400 KB）。

不设置时的表现就是控制台提示「USB 连接与配网助手没有加载」。要换目录用环境变量：

```sh
AIHUB_FIRMWARE_DIR=/path/to/aihub-firmware/flash docker compose up -d
```

## Rex 规划器

Rex 是纯 PyTorch 分类器，容器里能跑；卡住的是它加载的运行时目录：

```
<data>/rex-runtime/tokenizers/tokenizers.abi3.so: Mach-O 64-bit ... arm64
容器 import → ImportError: invalid ELF header
```

`build-rex-runtime.sh` 会照着这棵树的**版本清单**（transformers 4.48.3、tokenizers
0.21.4、datasets 2.21.0 …共 42 个包）在容器里装一套 Linux 版，放到
`<data>/rex-runtime-linux`，并强制用 CPU 版 torch、删掉 PyPI 顺带拖进来的 CUDA 目录。

```sh
./build-rex-runtime.sh          # 首次，约 1.4 GB，几分钟
./build-rex-runtime.sh --force  # 重建
```

compose 里通过 `AIHUB_REX_RUNTIME=/data/rex-runtime-linux` 指过去，规划器 worker 会在
`import torch` 之前把这个目录插到 `sys.path`（`lora.py` 在 `load()` 之前就 import torch，
所以顺序很重要）。镜像本身仍然只有 ~395 MB。

## 已知限制

| 限制 | 说明 |
|---|---|
| 固件配网（首次联网）不支持 | `prepare` 要枚举本机网卡选局域网，容器里看不到宿主网卡；已配网的设备走 OTA 正常 |
| Rex 需要独立的 Linux 运行时 | `<data>/rex-runtime` 是 macOS 的 pip 目录（`tokenizers.abi3.so` 是 Mach-O），容器里报 `invalid ELF header`。用 `build-rex-runtime.sh` 生成 `<data>/rex-runtime-linux`（≈1.4 GB，不进镜像），compose 通过 `AIHUB_REX_RUNTIME` 指过去，`planner=rex` 照用 |
| 外网工具偏慢 | 实测容器到部分国际站点的 TLS 握手约 6.1 s（宿主 0.55 s），而天气工具预算只有 6 s，可能超时；新闻同理。模型调用走 `host.docker.internal`，不受影响 |
| 文件工具只能看挂载目录 | 服务端跑在容器里，`file_directory` / `music_directory` 解析的是容器路径；要整理宿主目录得 `-v` 挂载并把配置改成容器内路径 |
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

### Independent browser client

Re-run `prepare-context.sh` and rebuild after upgrading: it copies the client as
an explicit static artifact at `/app/client-web`, selected by `AIHUB_CLIENT_ROOT`.
Compose publishes port 8768 on host loopback separately from the administrator
console; `/demo/` uses dedicated client credentials created in the console. Its
listener has no `/api/` management routes and never inherits `--local-console`.
For remote browsers use HTTPS and reverse-proxy only client routes to port 8768.
Do not expose the administrator listener. On Intel Linux with already deployed
model services use `deploy/linux/README.md`; `model-host.sh` is the optional
Mac-owned worker path, not an external model lifecycle manager.

`model-host.sh stop` now requires a matching process identity record written at
startup. It never reclaims a port by killing its listener. Legacy PID files alone
are insufficient; inspect those older worker processes and stop them explicitly
before switching launchers. The external HTTP Linux path does not use this script.
