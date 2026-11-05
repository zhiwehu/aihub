# Control plane only: aihub-server + the static console.
#
# Model inference is NOT in this image. MLX needs Apple Silicon macOS, which a
# container cannot provide; ASR/LLM/TTS run natively on the host and are reached
# over HTTP with provider=http (see model-host.sh). aihub-models is therefore
# not installed here on purpose.
FROM python:3.13-slim

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Installed as local paths: these packages are not on PyPI, and passing all
# three together keeps pip from trying to resolve aihub-common/aihub-tools
# from the index.
COPY pkgs/ /app/pkgs/
# No [rex] extra on purpose: the local planner loads the vendored runtime in
# <data>/rex-runtime, which is a macOS pip tree (tokenizers.abi3.so is Mach-O).
# In a Linux container it fails with "invalid ELF header", so the planner runs as
# planner=llm against the model tier over HTTP instead.
RUN pip install --index-url "$PIP_INDEX_URL" \
        /app/pkgs/aihub-common /app/pkgs/aihub-tools /app/pkgs/aihub-server \
 && rm -rf /app/pkgs

COPY web/ /app/web/
COPY client-web/ /app/client-web/
COPY assets/ /app/assets/

ENV AIHUB_WEB_ROOT=/app/web \
    AIHUB_CLIENT_ROOT=/app/client-web \
    VOICE_VAD_MODEL=/app/assets/silero_vad_v6.onnx

EXPOSE 8765 8768

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/status',timeout=2).status==200 else 1)"]

ENTRYPOINT ["python", "-m", "aihub_server"]
# --host 0.0.0.0: the server defaults to loopback, which no published port can reach.
CMD ["--data", "/data", "--port", "8765", "--host", "0.0.0.0"]
