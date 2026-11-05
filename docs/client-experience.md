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
first-response synthesis. A bounded model call (1.2 seconds / 72 tokens) may select only a literal
substring of the current request and a validated wording variant. Server-owned
phrases render the first feedback; model prose, invented facts, questions and
capability claims cannot be sent as preparation feedback. Invalid JSON or an
ungrounded focus falls back to wording that quotes the actual request. Interrupting input or speech does not cancel
Operations. Explicit cancellation remains a separate action.

A notification becomes consumed before its first PCM chunk is sent. Interrupting
that playback records delivery=interrupted, and it is not automatically replayed,
including after reconnect. Work/results remain stored. A result interrupted before
any audio begins stays pending and can be announced when the session is quiet.
Server restart never automatically re-executes side-effecting tool work.

Validation (2026-11-05): server 330 passed + 28 subtests, with only the documented
pre-existing wake-phrase failure; tools 90 passed + 15 subtests; admin 14 Node tests;
artifact integrity 1 test; independent client 10 Node tests. Real browser validated
connection, calendar tool history, chat/recording menu switching and desktop/mobile
layout. Full hardware microphone interruption still needs the user's live test.


## Conversation corrections from runtime logs (2026-11-05)

15:39 weather/news feedback invented questions/facts before tool results. Preparation
feedback now uses the structured selection contract above, covered by exact logged
counterexamples. Finished results are spoken fully as supplied, without random
lead-ins, default 120-character truncation or web-only continuation messages.

16:12 calendar conversation exposed three further issues: interrupted-state text
was injected into model history; keyword-only tool discussion triggered calendar
work; and stop-speaking requests left a backlog of announcements. State suffixes
are now kept out of model input/output, ordinary conversation rejects unexecuted
action claims, tool-feedback discussion does not authorize a calendar call, and
explicit today/tomorrow date-range queries use deterministic boundaries. Specific
weekdays/dates still follow slot extraction. Placeholder model questions are not
spoken literally.

“不要说了”/“不用说了” silences the current notification batch in that session,
including work still running, while preserving execution and stored results. The
muted delivery state survives subsequent operation updates and server restarts;
new tasks and other sessions remain unaffected. Ordinary speech interruption
continues to stop only the current playback. No existing reminder IDs are changed.


## Natural preparation feedback and news fallback

Preparation feedback now uses short, intent-specific conversational wording such
as “我查一下今天的天气。” and “我看看最近的新闻。”. It never quotes a whole
question or emits model-generated facts. The bounded structured selector still
controls only a validated wording variant and literal focus; server-owned phrases
remain the boundary against hallucinated pre-tool answers.

The test deployment was configured for Rex but had no Rex runtime, base model or
adapters. Basic latest-news requests now route directly to the configured news
source and count. Other core requests fall back to the configured language model
when Rex fails, retaining bounded routing input, schema validation and explicit
llm_fallback provenance. If both planners fail, tool-planning emits a failed event
so the operation cannot be displayed as completed.

Local music diagnosis: the configured Mac directory is not mounted into Docker,
and the current MusicPlayer requires /usr/bin/afplay. Mounting the library alone
cannot make a Linux container output to Mac speakers; playback destination must
be chosen before changing that path. No music files or playback configuration
were modified by this diagnosis.

Deployed smoke verification used the current model for weather/news/calendar first
feedback and confirmed short, unquoted preparation wording. The configured RSS
news tool completed successfully with Rex deliberately unavailable. No user
operation, recording or playback was created by the smoke check.

Client-owned music playback is now implemented; see docs/client-music.md.
