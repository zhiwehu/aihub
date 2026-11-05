# HTTP post-recording processing

On Linux install the base package (not `[local]`). Select HTTP explicitly:

```sh
export AIHUB_MINUTES_PROVIDER=http
export AIHUB_MINUTES_URL=http://127.0.0.1:1234/v1
export AIHUB_MINUTES_MODEL=your-actual-llm-id
export AIHUB_MINUTES_KEY_ENV=VOICE_LLM_KEY
export AIHUB_MINUTES_TIMEOUT=240
export AIHUB_MEDIA_ASR_PROVIDER=http
export AIHUB_MEDIA_ASR_URL=http://127.0.0.1:8000/v1
export AIHUB_MEDIA_ASR_MODEL=your-actual-asr-id
export AIHUB_MEDIA_ASR_KEY_ENV=VOICE_ASR_KEY
export AIHUB_MEDIA_ASR_TIMEOUT=240
python -m aihub_models serve --data /absolute/path/to/data
```

URLs are API base URLs including `/v1`; model IDs must match the serving backend.
API keys are read from the named environment variables, never included in URLs.
Both providers also support the legacy `VOICEHUB_` prefix. CLI model overrides
win over environment model IDs. HTTP mode never falls back to MLX.

Minutes use non-streaming `POST chat/completions` with `messages`, `max_tokens`
and `stream=false`; responses need `choices[0].message.content` as text. Configure
non-thinking generation in the backend when needed. Keep the existing templates,
chunk extraction, evidence, job persistence and exports. ASR sends multipart WAV
(mono PCM16, 16 kHz) and `model` to `POST audio/transcriptions`, expecting `text`.
Network, HTTP and malformed responses fail the job; failed ASR retries do not
silently replace a transcript with missing lines. Redirects are rejected to keep
credentials at the configured endpoint. Requests have finite timeouts and bounded
responses. Cancellation closes the request; external inference may still need
backend-specific cancellation support.

The minutes semaphore bounds only this process. Configure scheduling/concurrency
in the model service when real-time chat shares the model; a process-local lock
cannot coordinate server chat and background inference. No external process is
started or stopped by these providers.

macOS defaults remain local. To roll back, stop the processing service, remove
the HTTP provider environment overrides and restart with the previous configuration.
This opt-in change does not migrate or rewrite existing recordings/configuration.
