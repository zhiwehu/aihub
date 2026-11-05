# Client separation and Linux HTTP deployment

Approved scope: 2026-11-05, keep the six repositories. Requirements:
[SPEC-client-linux.md](SPEC-client-linux.md). No repository consolidation.

## Capability map and execution order

| ID | Responsibility | Depends on |
|---|---|---|
| processing-http | HTTP minutes and post-recording ASR, preserve Mac engines | common |
| linux-runtime | explicit HTTP configuration, owned-process lifecycle, deployment | processing-http |
| client-identity | authenticated stable client identity and record ownership | existing server authentication |
| client-web | independent static chat/recording client, scoped APIs | client-identity |
| admin-records | management-only UI and source filters/detail links | client-identity, client-web |

Work in independently tested increments, one repository per commit. Preserve data,
existing imports, ESP32 protocol and macOS defaults. External models are never
managed as owned workers. Do not modify the known wake-phrase baseline failure.

## Verification

Run each affected repository's full suite with the workspace Python and explicit
sibling PYTHONPATH, plus static JavaScript checks and browser verification for UI.
Use local HTTP test servers for provider contracts, errors and cancellation.
Actual Intel performance, real microphone and ESP32 checks require hardware and
must be reported separately. Back up configuration/data before runtime cutover;
keep new paths opt-in until validated. Never write credentials to source files.
