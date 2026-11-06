# Session-owned client music playback

User chose output on the requesting web client or voice device (2026-11-05).
Server reads only the configured, read-only music library. Tools receive a
session-scoped music callback; no server import from tools, no host afplay.

Use existing audio.start/chunk/end transport with purpose=music and a fresh
playback turn ID, 16 kHz mono PCM. Legacy gateways already encode this to Opus and
the device's tts start/stop protocol. No unauthenticated file URLs or new public
file-reading endpoint. Add music.state plus music.control (pause/resume/stop),
bound to the existing authenticated socket/session.

A music stream waits for conversation/notification audio to finish. Speech,
new input and recording pause it; resumption is explicit. Disconnect terminates
its decoder. A dedicated decoder subprocess uses existing PyAV and bounded
pipes, avoiding afplay/ffmpeg executable dependencies. Paths never enter events
or model results; symlinks outside the configured library stay rejected.

Verify library isolation, pause/resume offsets, cancellation/decoder cleanup,
PCM validity and legacy encoding. Web adds a compact now-playing control inside
chat. Deploy with only the configured music directory mounted read-only; retain
all unrelated config/data and never alter the frozen source repositories.

Implementation and verification: docs/client-music.md.

2026-11-06 optimization: directly route explicit music controls, implement ordered
next/random selection, shorten control replies, and acknowledge web volume changes
on the requesting socket. Resume music after a successful volume adjustment.
These are routing and execution corrections; no REX fine-tuning is required.
