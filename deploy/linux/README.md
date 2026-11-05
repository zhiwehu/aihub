# Linux with external HTTP models

Clone the core repository at `/opt/aihub` (or adapt the paths below). No sibling
source repositories are required. Install browser/firmware release artifacts
explicitly when needed. Use a fresh Linux environment, never copy the Mac `.venv`.
Install Python 3.11+, ffmpeg, libsndfile and lsof with your distribution's package
manager, then install only the base models package:

```sh
cd /opt/aihub
python3 -m venv .venv
.venv/bin/pip install -e ./packages/common -e ./packages/tools -e ./packages/processing -e ./packages/server
```

Supply a trusted Silero VAD ONNX model. Configure real endpoint/model IDs; the
following creates a NEW settings file and refuses to overwrite an existing one:

```sh
.venv/bin/python deploy/linux/configure.py \
  --output /var/lib/aihub/settings.json --vad-model /opt/aihub/assets/silero.onnx \
  --asr-url http://127.0.0.1:8000/v1 --asr-model ACTUAL_ASR_ID \
  --llm-url http://127.0.0.1:1234/v1 --llm-model ACTUAL_LLM_ID \
  --tts-url http://127.0.0.1:8000/v1 --tts-model ACTUAL_TTS_ID \
  --tts-voice ACTUAL_VOICE --tts-sample-rate 24000
```

These settings explicitly use HTTP, planner=llm and disable local music (afplay
is macOS only). The backend expects LLM SSE `delta.content`, ASR multipart WAV with
JSON `text`, and TTS raw mono s16le PCM at the configured sample rate, not WAV/MP3.
Configure non-thinking output in the LLM service. Use a thin adapter if your
backend differs. Backend concurrency/scheduling must reserve capacity for chat
when minutes jobs share the LLM; AIHub's process-local semaphore is insufficient.

Copy `runtime.env.example` to `/etc/aihub/runtime.env`, substitute actual IDs and
a random shared processing token (`python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`).
Protect the env file with mode 600 and appropriate service-user ownership. Add
`VOICE_ASR_KEY`, `VOICE_LLM_KEY`, `VOICE_TTS_KEY` there if required; no credentials
belong in Git. See packages/processing/docs/http-processing.md for provider configuration.

Create service user `aihub`, give it ownership of `/var/lib/aihub`, and install the
two `.service` examples under `/etc/systemd/system/`. Adjust all paths first.
Use `systemctl daemon-reload` and `systemctl enable --now aihub-processing aihub-server`.
Inspect `journalctl -u aihub-server -u aihub-processing`. External LLM/ASR/TTS units
are managed separately, with no dependencies that would stop them with AIHub.
Do not use the workspace launcher and systemd simultaneously.

Alternatively export the runtime variables and run `./start.sh --background
--data /var/lib/aihub --device-host none`. Its stop command signals only validated
owned workers and launcher processes, never listeners found by scanning ports.
Pre-change PID files without identity metadata are deliberately not trusted;
inspect and stop those legacy processes manually before cutover.

The admin console remains loopback only. For remote administration use an SSH
forward. Browser microphone use requires localhost or HTTPS; opening a LAN HTTP
port is insufficient. Add torch/speechbrain only if speaker recognition is needed.

## Backup, rollout, rollback

Before switching stop AIHub cleanly, back up the entire data directory (including
SQLite journal companions, settings, auth, recordings and jobs) with mode/ownership
preserved, and record the six Git commits. Never run old/new services against the
same data concurrently. Generate settings in a fresh directory and review them
before copying to the intended runtime location. Do not overwrite Mac settings.

To roll back stop both AIHub units, restore the previous package commits and
runtime environment/settings; preserve recordings made since cutover separately
before restoring a data snapshot. Restart the previous entry point. Provider
selection does not migrate recording formats.

## Target-machine acceptance (not yet measured)

Verify real microphone → ASR → LLM → TTS and recording pause/resume/stop on target
hardware; verify minutes and retranscription with long recordings. Record input
length, first-text/first-audio latency, ASR duration and peak memory. Test provider
outages/recovery, cancellation and that stopping AIHub leaves external model PIDs
alive. No Intel 225H performance claim is made by loopback contract tests.
