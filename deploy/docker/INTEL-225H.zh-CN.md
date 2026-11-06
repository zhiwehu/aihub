# Intel Core Ultra 5 225H：离线包 Docker 部署

更新：2026-11-06。Ubuntu 24.04、Debian 12/13，x86_64。
目标机只要 Docker；镜像、Compose 和脚本都在离线包里。模型用机器上已有的
LLM/ASR/TTS HTTP 服务，本文不装模型。

| 容器 | 作用 | 端口 |
| --- | --- | --- |
| `core`（aihub-core） | 管理端、网页客户端接口、ESP32 网关 | 127.0.0.1:8765 / 0.0.0.0:8768 / LAN:8766 |
| `processing`（aihub-processing） | 后处理、转写、纪要 | 127.0.0.1:8790（host 网络） |
| `bridge`（可选） | AtomGradient 私有协议适配 | 127.0.0.1:18095 |

这份包和 macOS 上跑的是**同一套代码、同一批镜像、同一份 compose**；唯一的差别是
`.env` 里的模型地址，以及 Linux 上用 `compose.host.yaml` 把容器放到 host 网络。

## 1. 构建离线包（构建机）

在 `aihub` 仓库根目录、装了 Docker 的机器上：

```bash
./scripts/install.sh            # 首次，建 .venv
./deploy/docker/build-bundle.sh
```

产物：`dist/aihub-225h-<tag>.tar.gz`（默认 `linux/amd64`，Mac 上会自动交叉构建）。
包里有：两个镜像、`compose.yaml`、`compose.host.yaml`、`.env.example`、
`env.models.env.example`、`install.sh`、`bridge.py`、这份说明，以及（如果在
`deploy/docker/client-web/` 里装过客户端）`client-web/`。

## 2. 传到 225H 并启动

```bash
scp dist/aihub-225h-<tag>.tar.gz root@192.168.1.50:/root/
ssh root@192.168.1.50
mkdir -p /root/aihub-225h
tar xzf aihub-225h-<tag>.tar.gz -C /root/aihub-225h
cd /root/aihub-225h
nano .env
./install.sh
```

`.env` 需要改的是模型地址（其余路径由 `install.sh` 自动换成绝对路径）：

```bash
ASR_URL=http://127.0.0.1:8781/v1
ASR_MODEL=你的ASR模型ID
LLM_URL=http://127.0.0.1:8782/v1
LLM_MODEL=你的LLM模型ID
```

- 这两项给 `processing` 容器和纪要/转写用；管理台里的 ASR/LLM 也填同一组值。
- `AIHUB_MODELS_TOKEN` 由 `install.sh` 自动生成在 `env/models.env`（600 权限）。
- `AIHUB_CORE_IMAGE` / `AIHUB_PROCESSING_IMAGE` 已由包固定，不要改。
- `AIHUB_DEVICE_HOST` 填本机局域网地址（设备要拨的地址）。

`install.sh` 会导入镜像、创建 `data/ music/ files/ firmware/ env/`，然后用
`compose.yaml + compose.host.yaml` 启动。

## 3. 管理台

管理端只在回环，从本机或 SSH 转发访问：

```bash
ssh -N -L 8765:127.0.0.1:8765 root@192.168.1.50
```

打开 `http://127.0.0.1:8765`。首次配置：

1. 「模型」页把 ASR/LLM/TTS 切到 HTTP API，填地址、模型 ID、TTS 音色和采样率。
2. 「连接」页把设备监听 IPv4 选成本机局域网地址，保存后启动设备监听（8766）。
3. 「客户端接入」生成连接码，给网页客户端用。

管理员令牌（需要命令行时）：

```bash
docker compose -f compose.yaml -f compose.host.yaml exec core \
  python -m aihub_server --data /data --print-admin-token
```

## 4. 网页客户端

客户端页面在 [`aihub-client-web`](https://github.com/zhiwehu/aihub-client-web) 构建，
**不打进 core 镜像**。两种用法：

- 包里有 `client-web/`：`install.sh` 会把它挂进容器，直接访问
  `http://<服务器IP>:8768/demo/`；
- 没有的话，把构建机上装好的 artifact 拷过来：

```bash
# 构建机
.venv/bin/python scripts/install-client.py <client-release> \
  --destination deploy/docker/client-web

# 目标机（放到部署目录后重启 core）
scp -r deploy/docker/client-web root@192.168.1.50:/root/aihub-225h/
cd /root/aihub-225h && docker compose -f compose.yaml -f compose.host.yaml restart core
```

页面用 localhost 打开才能用麦克风；局域网 HTTP 页面需要 HTTPS 反代。

## 5. AtomGradient 私有协议（可选）

如果 TTS/ASR 走 AtomGradient 的 WS 流式协议，在 `.env` 里启用 bridge：

```bash
COMPOSE_PROFILES=bridge
ATOM_ASR_URL=http://127.0.0.1:18094/v1/asr
ATOM_TTS_HTTP_URL=http://127.0.0.1:18094/api/v1/tts
ATOM_TTS_WS_URL=ws://127.0.0.1:18093/api/v3/tts/bidirection
```

然后管理台里的 TTS 地址填 `http://127.0.0.1:18095/v1`（host 网络）。

## 6. ESP32

管理台「连接」页启动设备监听后，设备连：

```text
ws://192.168.1.50:8766/xiaozhi/v1/
```

地址以管理台显示为准，设备按配网/OTA 下发的地址拨号。OTA 用设备凭证，不是管理令牌。
需要网页 USB 刷机时，把固件 release 的 `flash/` 放进部署目录的 `firmware/`（已挂到
`/firmware`）。

## 7. 升级与备份

升级：解压新包到同一目录（覆盖 compose、脚本和镜像），再执行 `./install.sh`。
`.env`、`env/`、`data/` 不会被覆盖。

```bash
tar xzf aihub-225h-<新tag>.tar.gz -C /root/aihub-225h
cd /root/aihub-225h && ./install.sh
docker image prune
```

备份（含凭证和录音，不要外传）：

```bash
cd /root/aihub-225h
docker compose -f compose.yaml -f compose.host.yaml stop
tar -czf "backups/runtime-$(date +%Y%m%d-%H%M%S).tar.gz" data .env env compose.yaml
docker compose -f compose.yaml -f compose.host.yaml start
```

日志：

```bash
docker compose -f compose.yaml -f compose.host.yaml logs --since=10m --tail=150 core processing
```

## 8. 参考

- [Intel 225H 规格](https://www.intel.com/content/www/us/en/products/sku/241749/intel-core-ultra-5-processor-225h-18m-cache-up-to-4-90-ghz/specifications.html)
- [Docker host 网络](https://docs.docker.com/engine/network/drivers/host/)
- [AIHub HTTP 后处理配置](https://github.com/zhiwehu/aihub/blob/main/packages/processing/docs/http-processing.md)
