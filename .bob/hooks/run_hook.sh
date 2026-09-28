#!/bin/sh
# IBM Bob lifecycle hook entry point: sh .bob/hooks/run_hook.sh <session_start|prompt_guard|write_guard|mcp_audit>
# Runs from the workspace root. Uses the project venv if present.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PRAMAAN_PYTHON:-}"
[ -z "$PY" ] && [ -x "$ROOT/src/.venv/bin/python" ] && PY="$ROOT/src/.venv/bin/python"
[ -z "$PY" ] && PY="$(command -v python3 || command -v python)"
cd "$ROOT/src" && exec "$PY" -m pramaan.bob_hooks "$1"
