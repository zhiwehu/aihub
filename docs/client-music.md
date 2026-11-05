# Local music on the requesting client

The music library stays on the server. Audio plays on the web client or voice
device that requested it; no host speaker, afplay process, public audio URL or
cross-session player is involved. The authenticated pipeline exposes only a
ClientMusicControl.call interface to the tool layer.

## Transport and controls

Existing audio.start/chunk/end messages carry 16 kHz mono s16 PCM, with a fresh
playback turn ID and optional purpose=music. WebSocket/Xiaozhi/MQTT adapters keep
their existing PCM/Opus framing. Device playback-ready accepts either the current
reply turn or the current music stream, never an unrelated ID. Existing firmware
needs no new media parser. Device speaker quality follows its existing voice
codec; physical hardware remains a separate acceptance test.

music.state contains state (queued/playing/paused/stopped/failed), title, track_id
and approximate position. No filesystem paths are exposed. The existing
socket accepts music.control with pause/resume/stop; every control is scoped to
that socket's session. The web player adds independent music volume.

Music waits for acknowledgement/result speech to finish. A new conversation,
barge-in, another result announcement or recording pauses it. Resuming requires
an explicit voice command or button. A disconnected client terminates its decoder
and does not resume automatically. Paused device sessions stay alive for resume.
Corrupt audio produces a safe failure event and audible notification when the
session has an operation queue; it never reports that sound was heard.

A bounded decoder subprocess uses the existing PyAV dependency, not a desktop
player executable. Pause/resume seek to the server's sent PCM position. Pipes are
bounded, reads time out, and cancellation during startup still reaps the child.
Only configured library files are selected; outside symlinks and foreign IDs are
rejected. Library access is revalidated before decoding and after config changes.

## Deployment

Bind only the administrator-selected music directory, read-only, at its configured
absolute path. Docker Compose uses AIHUB_MUSIC_DIR for this mapping. The isolated
local test container now mounts the user's existing library read-only; music
settings, recordings, calendars, credentials and model services are preserved.
No firmware source or frozen repository was modified.

The admin console scans the library but playback controls belong to clients.
The standalone stdio music tool permits search; playback outside a bound session
returns music_session_required, preventing accidental host-speaker fallback.

## Verification

Core regression: common 54, processing 63, tools 90 + 15 subtests; server 330 +
28 subtests with the one documented pre-existing wake-phrase failure unchanged.
Root artifact integrity 1 and admin Node 14 passed. Client Node 10 passed.
Music-specific checks cover real resampling/seeking, isolation, pause/resume,
corrupt input, cancellation during spawn, cleanup and a real legacy ready/Opus
transport exchange. Browser playback of an existing library track reached playing;
pause, resume, volume and stop worked without console errors. After stop there
were zero decoder processes. The temporary test credential was revoked.
