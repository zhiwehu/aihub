#!/bin/bash
# Load the bundled images and start AIHub on this host.
set -eu
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo '需要 Docker。' >&2; exit 1; }
docker compose version >/dev/null || { echo '需要 Docker Compose 插件。' >&2; exit 1; }

[ -f .env ] || cp .env.example .env
if grep -q '^AIHUB_MODELS_TOKEN=REPLACE_WITH_RANDOM_TOKEN' .env; then
  token="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-43)"
  sed -i "s|^AIHUB_MODELS_TOKEN=.*|AIHUB_MODELS_TOKEN=$token|" .env
fi
if grep -q 'REPLACE_WITH_ACTUAL' .env; then
  echo '请先编辑 .env，把 ASR_URL/ASR_MODEL/LLM_URL/LLM_MODEL 改成实际值，再执行 ./install.sh。' >&2
  exit 1
fi

umask 077
mkdir -p data models music backups
[ -f model-keys.env ] || { : > model-keys.env; chmod 600 model-keys.env; }

docker load -i images/aihub-images.tar.gz
docker compose up -d
docker compose ps

echo
echo '管理端（本机或 SSH 转发）：http://127.0.0.1:8765'
echo '远程：ssh -N -L 8765:127.0.0.1:8765 用户名@<服务器IP>'
echo '管理员令牌：docker compose exec core python -m aihub_server --data /data --print-admin-token'
echo '网页客户端：http://<服务器IP>:8768/demo/（页面需另行部署）'
