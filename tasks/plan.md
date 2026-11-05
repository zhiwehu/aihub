# Three-repository migration

Approved 2026-11-05. Keep current live deployment while preparing a proven replacement.

- [x] Record clean source tips and preserve histories via non-squashed subtrees.
- [x] Split browser-client history and retain independent firmware history.
- [x] Consolidate packages/admin; move deployment/scripts to core root.
- [x] Install independent environment; preserve import and process boundaries.
- [x] Export client artifacts with protocol/hash manifest and explicit installation.
- [x] Remove old sibling source assumptions from startup and Docker packaging.
- [x] Test packages, client/admin/firmware, standalone native start/stop and Docker.
- [x] Document source mapping, deployment inputs, test limits, cutover and rollback.
- [ ] Push verified target repositories and check clean/synchronized status.
- [ ] Production cutover after current user testing; existing data/ingress stay on old deployment until then.
