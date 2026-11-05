# Client experience and background tool delivery

Approved 2026-11-05 (user clarified and requested continuation).

1. Beginner connection guide: two steps, optional readable name, copyable connection
   code, correct configured client URL; existing authentication/isolation unchanged.
   Manual hardware identity/token entry belongs under a closed advanced section.
2. Independent client: distinct conversation and recording routes/menus. Chat uses
   conventional user/assistant bubbles, bottom composer, streaming replies and
   per-turn tool progress/history. Recording controls/history/minutes are separate.
3. Slow tools: immediate contextual acknowledgement, then app-owned background work.
   Audio interruption must not cancel queued/running work. Result audio can be
   interrupted; once playback has begun it must not be queued again. Explicit task
   cancellation remains separate from interrupting speech.

Reuse Operations and existing tool events. Extend scoped client APIs only for the
current client's own evidence/tasks; no administrator API or credential access.
Generate short context-specific acknowledgement through the existing model with a
bounded wait and contextual fallback; never wait for tool completion first.

Order: finish guide increment -> specify/prove backend interruption behavior ->
add scoped tool/task history -> build client pages/progress -> regression/browser
verification -> build and update only the three-repository test deployment.

Checks: current core suites (retain known wake failure), meaningful queue/delivery
regressions, client Node tests, real browser page/menu/connection/tool evidence.
Existing user data remains intact; no automatic replay of side-effecting tasks.
