#!/bin/bash
# Read-only standardized result/log diagnostic, with legacy transcript fallback.
set -euo pipefail
CODE="$(cd "$(dirname "$0")/.." && pwd)"
RUN="${1:?usage: diagnose_run.sh <run-directory>}"
PY="${RCWM_ROOT:-$CODE/runtime}/.venv/bin/python"
[ -x "$PY" ] || PY=python3
exec "$PY" "$CODE/tools/diagnose_run.py" "$RUN"
