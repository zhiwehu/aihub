#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
export PYTHONPATH="$ROOT/packages/common/src:$ROOT/packages/tools/src:$ROOT/packages/processing/src:$ROOT/packages/server/src"
result=0
(cd "$ROOT" && "$PY" -m pytest tests -q) || result=1
for package in common processing tools server; do
  (cd "$ROOT/packages/$package" && "$PY" -m pytest tests -q) || result=1
done
for file in "$ROOT"/apps/admin-web/public/*.js; do node --check "$file" || result=1; done
node --test "$ROOT"/apps/admin-web/tests/*.mjs || result=1
exit "$result"
