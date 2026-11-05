#!/bin/sh
exec "$(cd "$(dirname "$0")" && pwd)/scripts/start_workspace.sh" "$@"
