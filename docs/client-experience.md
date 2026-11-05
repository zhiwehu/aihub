# Web client and background delivery

The admin connection page guides first-time users through generating a connection
code and opening the configured independent client. Manual device credentials are
under advanced settings. AIHUB_CLIENT_PUBLIC_URL can override the full entry URL;
AIHUB_CLIENT_PUBLIC_PORT defaults to the configured client listener port.

The independent client has #chat and #recordings routes. Both share the same live
connection; switching menus does not end a recording or cancel a tool. Chat shows
user/assistant messages, streamed replies, per-request tool state, arguments and
duration. Task progress and results attach to the original assistant reply, including after
speech stops; there is no separate trailing task list. Connection/disconnection
controls have their own #connection page and do not occupy the chat.
Recording controls, saved audio, transcript and meeting minutes have their own page.

Authenticated client API additions:
- GET /client/v1/sessions/{sid}/tool-calls: persisted tool evidence and active turn;
  the existing session ownership check applies before reading evidence.
- GET /client/v1/operations: allowlisted task fields for sessions owned by the
  credential. Temporary progress notices and other clients' tasks are excluded.

ToolNotice transfers work to the existing application-owned Operations queue before
first-response synthesis. A separate model call generates a contextual first
sentence, bounded to 1.2 seconds / 72 tokens; timeout or invalid output falls back
to a sentence naming the request. Interrupting input or speech does not cancel
Operations. Explicit cancellation remains a separate action.

A notification becomes consumed before its first PCM chunk is sent. Interrupting
that playback records delivery=interrupted, and it is not automatically replayed,
including after reconnect. Work/results remain stored. A result interrupted before
any audio begins stays pending and can be announced when the session is quiet.
Server restart never automatically re-executes side-effecting tool work.

Validation (2026-11-05): server 312 passed + 18 subtests, with only the documented
pre-existing wake-phrase failure; tools 79 passed + 12 subtests; admin 14 Node tests;
artifact integrity 1 test; independent client 8 Node tests. Real browser validated
connection, calendar tool history, chat/recording menu switching and desktop/mobile
layout. Full hardware microphone interruption still needs the user's live test.
