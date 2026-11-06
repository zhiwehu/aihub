#!/bin/bash
# Load the bundled images and start AIHub on a Linux host (host networking).
set -eu
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo '需要 Docker。' >&2; exit 1; }
docker compose version >/dev/null || { echo '需要 Docker Compose 插件。' >&2; exit 1; }

[ -f .env ] || cp .env.example .env
mkdir -p data models music files firmware backups client-web env

umask 077
[ -f env/models.env ] || cp env.models.env.example env/models.env

# Replace the documentation placeholders with paths that exist on this host.
python3 - <<'PY'
from pathlib import Path
env = Path('.env')
text = env.read_text()
replacements = {
    '/absolute/path/to/data': Path('data').resolve(),
    '/absolute/path/to/client-web': Path('client-web').resolve(),
    '/absolute/path/to/music': Path('music').resolve(),
    '/absolute/path/to/files': Path('files').resolve(),
    '/absolute/path/to/aihub-firmware/flash': Path('firmware').resolve(),
}
for placeholder, real in replacements.items():
    text = text.replace(placeholder, str(real))
env.write_text(text)
PY

if grep -q '^AIHUB_MODELS_TOKEN=REPLACE_WITH_SHARED_PROCESSING_TOKEN' env/models.env; then
  token="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-43)"
  sed -i "s|^AIHUB_MODELS_TOKEN=.*|AIHUB_MODELS_TOKEN=$token|" env/models.env
fi
chmod 600 env/models.env

if grep -q 'REPLACE_WITH_ACTUAL' .env; then
  echo '请先编辑 .env，把 ASR_URL/ASR_MODEL/LLM_URL/LLM_MODEL 改成实际值，再执行 ./install.sh。' >&2
  exit 1
fi

docker load -i images/aihub-images.tar.gz
docker compose -f compose.yaml -f compose.host.yaml up -d
docker compose -f compose.yaml -f compose.host.yaml ps

echo
echo '管理端（本机或 SSH 转发）：http://127.0.0.1:8765'
echo '远程：ssh -N -L 8765:127.0.0.1:8765 用户名@<服务器IP>'
echo '管理员令牌：docker compose exec core python -m aihub_server --data /data --print-admin-token'
echo '网页客户端：http://<服务器IP>:8768/demo/'
if [ ! -f client-web/index.html ]; then
  echo
  echo '提示: 还没有客户端页面。在构建机执行'
  echo '  .venv/bin/python scripts/install-client.py <client-release> --destination <此目录>/client-web'
  echo '或把已安装的 client-web 目录拷到本目录，然后 docker compose restart core。'
fi
