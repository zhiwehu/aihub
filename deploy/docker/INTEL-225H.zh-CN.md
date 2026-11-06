# Intel Core Ultra 5 225H：离线包 Docker 部署

更新：2026-11-06。Ubuntu 24.04、Debian 12/13，x86_64。
目标机只要 Docker；镜像、Compose 和脚本都在离线包里。模型用机器上已有的 LLM/ASR/TTS
HTTP 服务，本文不装模型。

| 容器 | 作用 | 端口 |
| --- | --- | --- |
| core | 管理端、网页客户端接口、ESP32 网关 | 127.0.0.1:8765 / 0.0.0.0:8768 / LAN IP:8766 |
| processing | 后处理、转写、纪要 | 127.0.0.1:8790 |

网页客户端页面不在本机部署，由 `aihub-client-web` 构建后另行托管；服务端只提供 8768
的接口。

## 1. 构建离线包（构建机）

在已有 `aihub` 仓库、装了 Docker 的机器上：

```bash
cd ~/aihub-src/aihub
./scripts/install.sh            # 首次，建 .venv
./deploy/docker/build-bundle.sh
```

产物：`dist/aihub-225h-<tag>.tar.gz`。默认按 `linux/amd64` 构建，Mac 上会自动交叉构建。
包里有：两个镜像、`compose.yaml`、`.env.example`、`install.sh`、这份说明。

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

`.env` 需要改的只有模型地址：

```bash
ASR_URL=http://127.0.0.1:8781/v1
ASR_MODEL=你的ASR模型ID
LLM_URL=http://127.0.0.1:8782/v1
LLM_MODEL=你的LLM模型ID
```

- 这两项给后处理容器用；管理台里的 ASR/LLM 也填同一组值。
- `AIHUB_MODELS_TOKEN` 由 `install.sh` 自动生成，`AIHUB_DEPLOY=.` 不用改。
- 网页客户端页面部署好后，把它的 origin 填到 `CLIENT_ORIGINS`（多个用逗号分隔）；
  信任整个局域网时直接填 `*`（仍然需要连接码）。页面完整地址填到 `CLIENT_PUBLIC_URL`。

`install.sh` 会导入镜像、创建 `data/`、启动两个容器。

## 3. 管理台

管理端只在回环，从本机或 SSH 转发访问：

```bash
ssh -N -L 8765:127.0.0.1:8765 root@192.168.1.50
```

打开 `http://127.0.0.1:8765`，管理员令牌：

```bash
cd /root/aihub-225h
docker compose exec core python -m aihub_server --data /data --print-admin-token
```

首次配置：

1. 「模型」页把 ASR/LLM/TTS 切到 HTTP API，填地址、模型 ID、TTS 音色和采样率。
2. 「连接」页把设备监听 IPv4 选成本机局域网地址，保存后启动设备监听（8766）。
3. 「客户端接入」生成连接码，给网页客户端用。

## 4. 网页客户端

页面在 [`aihub-client-web`](https://github.com/zhiwehu/aihub-client-web) 构建，
放到任意静态主机（保持 `/demo/assets/` 路径）。把页面 origin 写进 `.env` 的
`CLIENT_ORIGINS`、页面地址写进 `CLIENT_PUBLIC_URL`，再执行：

```bash
cd /root/aihub-225h
docker compose up -d --force-recreate core
```

客户端页面里填：

- 服务地址：`http://192.168.1.50:8768`
- 连接码：第 3 步生成的

页面用 localhost 打开才能用麦克风；局域网 HTTP 页面需要 HTTPS。

## 5. ESP32

管理台「连接」页启动设备监听后，设备连：

```text
ws://192.168.1.50:8766/xiaozhi/v1/
```

地址以管理台显示为准，设备按配网/OTA 下发的地址拨号。OTA 用设备凭证，不是管理令牌。

需要网页 USB 刷机时，把 `aihub-firmware/flash` 只读挂到 core 的 `/firmware`，并在
`compose.yaml` 的 core 服务里加 `AIHUB_FIRMWARE_ROOT: /firmware`。

## 6. 升级与备份

升级：解压新包到同一目录（覆盖 Compose 和镜像），再执行 `./install.sh`。`.env` 和
`data/` 不会被覆盖。

```bash
tar xzf aihub-225h-<新tag>.tar.gz -C /root/aihub-225h
cd /root/aihub-225h && ./install.sh
docker image prune
```

备份（含凭证和录音，不要外传）：

```bash
cd /root/aihub-225h
docker compose stop
tar -czf "backups/runtime-$(date +%Y%m%d-%H%M%S).tar.gz" data .env model-keys.env compose.yaml
docker compose start
```

日志：

```bash
docker compose logs --since=10m --tail=150 core processing
```

## 7. 参考

- [Intel 225H 规格](https://www.intel.com/content/www/us/en/products/sku/241749/intel-core-ultra-5-processor-225h-18m-cache-up-to-4-90-ghz/specifications.html)
- [Docker host 网络](https://docs.docker.com/engine/network/drivers/host/)
- [AIHub HTTP 后处理配置](https://github.com/zhiwehu/aihub/blob/main/packages/processing/docs/http-processing.md)
