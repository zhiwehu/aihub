# Six repositories to three

Date: 2026-11-05. Migration is isolated under `three-repo/`; the running six-repo
Docker deployment and its data remain unchanged until an explicit cutover.

## Source history

`source-map.json` pins every source commit, subtree import commit, client history
split commit and target directory. Common, models, tools, server and Web were
imported with **non-squashed git subtree merges**. Original commits remain ancestors
of core main. Client history was extracted from `clients/web-demo` in a temporary
clone using `git subtree split`; its derived commits retain authorship/messages,
and the full original server history is also preserved in core. Firmware is a
normal clone retaining its original history and existing remote.

After import, server deployment/scripts/docs moved to root directories and its
client source was removed from the current core tree. Historical source copies
remain in Git history for provenance, not as runtime dependencies.

| Original | Current |
|---|---|
| aihub-common | packages/common |
| aihub-models | packages/processing (import name aihub_models retained) |
| aihub-tools | packages/tools |
| aihub-server | packages/server |
| aihub-server/deploy, scripts, docs | deploy, scripts, docs |
| aihub-web | apps/admin-web |
| aihub-server/clients/web-demo | separate aihub-client-web |
| aihub-firmware | separate aihub-firmware |

Package-level historical documentation may describe the former layout. Root
README/deploy docs are authoritative for installation, artifacts and entry points.
No model weights, runtime data, old virtual environment or credentials were copied
into Git. No source repository is deleted, archived, force-pushed or redirected.

## Compatibility and process boundaries

Package names, CLI commands, HTTP/WebSocket routes, credentials and recording
formats stay stable. Server calls processing/inference over HTTP; tools receive
runtime objects from server; common imports no siblings. Optional Mac MLX workers
remain in processing. Linux base installation does not import/install those extras.
Admin Web belongs to core. Browser Web is a versioned explicit artifact, not a
Python dependency or a relative sibling source mount. Firmware remains an optional
artifact input with the existing browser event contract.

## Rollout / rollback

1. Pin all three final commits, build client release and core image, verify tests
   and isolated startup. Use separate data and ports for validation.
2. Before production cutover, stop active recording work, stop only old AIHub
   services, and back up the live runtime directory including SQLite companions,
   recordings, credentials, settings, jobs, and deployment env files. Keep the old
   image and all six old commits (the current deployment has an earlier backup).
3. Build/install client artifact and optional firmware artifact, then configure
   explicit data paths, model URLs/keys and unused/desired ports. Docker's core
   image/container/project names differ from the old deployment to avoid accidental
   replacement during validation. Select one deployment owner before cutover.
4. Start core and processing, leaving external model services owned by their
   existing deployment. Verify old/new history, browser credentials, recordings,
   minutes, provisioning and cancellation before routing normal clients.
5. On failure stop new services, preserve newly generated records, and restart the
   old image/entry point with its existing configuration. No schema conversion is
   introduced by consolidation. Do not run both versions against one data directory.

Moving source code is not proof of real microphone, ESP32 or Intel performance.
Hardware acceptance from the preceding feature work remains a separate gate.
