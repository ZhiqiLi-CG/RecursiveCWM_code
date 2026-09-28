#!/bin/bash
# Stable entry point; use the runtime Python (Pillow validates canonical PNG outputs).
set -euo pipefail
CODE="${RCWM_CODE:-$(cd "$(dirname "$0")/.." && pwd)}"
ROOT="${RCWM_ROOT:-$CODE/runtime}"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
exec "$PY" "$CODE/runner/run_node.py" "$@"
