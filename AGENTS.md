# AIHub core rules

This repository consolidates common, models/processing, tools, server and admin web.
Python import names and CLI entry points remain compatible. Client Web and firmware
remain independent repositories. Do not import aihub_models from aihub_server;
server uses HTTP. Tools cannot import server, common is a leaf. Keep runtime data,
weights, credentials and virtual environments out of Git. Preserve reminder UUID
namespaces. Do not modify the frozen miaoban-voicehub source or the old six-repo
runtime during migration. See docs/migration.md for source commit mapping.

Use scripts/test.sh with the isolated environment. The pre-existing wake-phrase
failure remains documented; do not change production behavior just to mask it.
Commit one logical change and repository at a time. Never force-push old history.
