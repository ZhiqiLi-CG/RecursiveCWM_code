#!/bin/bash
# setup_runtime.sh [RCWM_ROOT] [--metrics] [--python <interpreter>] [--conda <env-name>] [--node-from <dir>] [--recreate-venv]
# Builds the runtime root the solver needs (docs/environment.md) on a Linux x86_64 machine. Nothing is installed into
# the Python environment you are in: packages always go into a private venv, including with --conda.
#   $RCWM_ROOT/.venv                    CPython 3.12 with Pillow + numpy   (+ metrics packages with --metrics)
#                                       created from --python (or python3.12 / python3); --conda <name> supplies Python
#                                       from a conda env (created with python=3.12 if missing). --recreate-venv backs up and rebuilds it.
#   $RCWM_ROOT/.render-tools/node       Node.js 22 (downloaded from nodejs.org, or symlinked with --node-from)
#   $RCWM_ROOT/.render-tools/node_modules/{three,playwright}   three.js 0.160.1 + Playwright 1.62.1
#   headless Chromium for Playwright    in $PLAYWRIGHT_BROWSERS_PATH (default ~/.cache/ms-playwright)
#   $RCWM_ROOT/runs                     one directory per run
# Re-running reuses tools and reinstalls pinned packages. Needs: CPython 3.12 (with venv), curl, tar, network.
set -euo pipefail
CODE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${CODE}/runtime"; METRICS=0; NODE_FROM=""; CONDA_ENV=""; RECREATE_VENV=0
PYTHON_VERSION="$(cat "$CODE/.python-version")"
PY="${PYTHON:-$(command -v "python$PYTHON_VERSION" || command -v python3 || true)}"
while [ $# -gt 0 ]; do
  case "$1" in
    --metrics) METRICS=1 ;;
    --recreate-venv) RECREATE_VENV=1 ;;
    --python) PY="$2"; shift ;;
    --conda) CONDA_ENV="$2"; shift ;;
    --node-from) NODE_FROM="$2"; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) ROOT="$1" ;;
  esac; shift
done
ROOT="$(mkdir -p "$ROOT" && cd "$ROOT" && pwd)"
NODE_VERSION="${RCWM_NODE_VERSION:-22.14.0}"
echo "runtime root: $ROOT"

# Check before creating or rebuilding a venv. Do not use assert: PYTHONOPTIMIZE disables it.
check_python() {
  "$1" -I - "$PYTHON_VERSION" <<'P'
import sys
required = tuple(map(int, sys.argv[1].split(".")))
if sys.implementation.name != "cpython" or sys.version_info[:2] != required:
    print(
        f"CPython {sys.argv[1]}.x required by the pinned runtime and metrics packages; "
        f"got {sys.implementation.name} {sys.version.split()[0]} at {sys.executable}.\n"
        f"Use --python /path/to/python{sys.argv[1]} or --conda <new-env-name>.\n"
        "If the runtime already has a .venv, use --recreate-venv or choose a new runtime directory; "
        "--python only selects the interpreter when creating a new venv.",
        file=sys.stderr,
    )
    sys.exit(1)
P
}

# 1. Conda supplies only the interpreter. A venv keeps its installed packages out of this project.
if [ -n "$CONDA_ENV" ]; then
  CONDA="${RCWM_CONDA:-$(command -v conda || command -v mamba || command -v micromamba || true)}"
  [ -n "$CONDA" ] || { echo "--conda needs conda, mamba or micromamba on PATH (or RCWM_CONDA=/path/to/it)"; exit 1; }
  if ! "$CONDA" run -n "$CONDA_ENV" python -I --version >/dev/null 2>&1; then
    echo "creating conda env $CONDA_ENV (python=$PYTHON_VERSION) ..."
    "$CONDA" create -y -q --no-default-packages -n "$CONDA_ENV" "python=$PYTHON_VERSION" >/dev/null
  fi
  PREFIX="$("$CONDA" run -n "$CONDA_ENV" python -I -c 'import sys; print(sys.prefix)' | tail -1)"
  PY="$PREFIX/bin/python"
  [ -x "$PY" ] || { echo "conda env $CONDA_ENV has no bin/python at $PREFIX"; exit 1; }
  check_python "$PY"
  echo "python:  using conda env $CONDA_ENV ($PREFIX) as the venv interpreter"
fi
# Migrate the old setup's direct conda link without modifying the conda environment.
if [ -L "$ROOT/.venv" ] && [ -d "$ROOT/.venv/conda-meta" ]; then
  if [ -z "$CONDA_ENV" ]; then
    PY="$(cd "$ROOT/.venv" && pwd -P)/bin/python"
  fi
  RECREATE_VENV=1
fi
if [ "$RECREATE_VENV" = 1 ] || [ ! -x "$ROOT/.venv/bin/python" ]; then
  [ -n "$PY" ] && command -v "$PY" >/dev/null 2>&1 || { echo "CPython $PYTHON_VERSION is needed: pass --python /path/to/python$PYTHON_VERSION or --conda <env>" >&2; exit 1; }
  check_python "$PY"
  # Resolve the base interpreter before moving an existing venv that --python may point into.
  PY="$("$PY" -I -c 'import sys; print(sys._base_executable)')"
  check_python "$PY"
  if [ -e "$ROOT/.venv" ] || [ -L "$ROOT/.venv" ]; then
    BACKUP="$(mktemp -d "$ROOT/.venv-backup.XXXXXX")"
    mv "$ROOT/.venv" "$BACKUP/.venv"
    echo "python:  previous .venv saved at $BACKUP/.venv"
  fi
  "$PY" -I -m venv "$ROOT/.venv"
fi
check_python "$ROOT/.venv/bin/python"
# Ignore inherited Python paths and pip settings such as --user, --target, or --no-deps.
# Keep packages and their dependencies inside this venv even on shared research machines.
runtime_pip() {
  PIP_CONFIG_FILE=/dev/null "$ROOT/.venv/bin/python" -I -m pip --isolated "$@"
}
runtime_pip install --quiet --upgrade pip
REQUIREMENTS="$CODE/setup/requirements-runtime.txt"
if [ "$METRICS" = 1 ]; then
  REQUIREMENTS="$CODE/setup/requirements-metrics.txt"
fi
runtime_pip install --quiet -r "$REQUIREMENTS"
if ! runtime_pip check; then
  echo "Runtime dependencies are inconsistent. Rerun setup with --recreate-venv (and --metrics for evaluation)." >&2
  echo "This backs up the old .venv and installs into a clean one; runs and render tools are kept." >&2
  exit 1
fi
"$ROOT/.venv/bin/python" -I - "$METRICS" <<'P'
import importlib, sys
modules = ["PIL", "numpy"]
if sys.argv[1] == "1":
    modules += ["torch", "torchvision", "cv2", "scipy", "skimage", "lpips", "open_clip", "pytest"]
for name in modules:
    importlib.import_module(name)
print("python imports: " + ", ".join(modules))
P
echo "python:  $("$ROOT/.venv/bin/python" -I --version)  (metrics packages: $([ "$METRICS" = 1 ] && echo yes || echo no))"

# 2. Node.js
mkdir -p "$ROOT/.render-tools"
if [ ! -x "$ROOT/.render-tools/node/bin/node" ]; then
  if [ -n "$NODE_FROM" ]; then
    [ -x "$NODE_FROM/bin/node" ] || { echo "--node-from $NODE_FROM has no bin/node"; exit 1; }
    ln -sfn "$NODE_FROM" "$ROOT/.render-tools/node"
  else
    ARCH=$(uname -m); case "$ARCH" in x86_64) NA=x64 ;; aarch64|arm64) NA=arm64 ;; *) echo "unsupported arch $ARCH"; exit 1 ;; esac
    TB="node-v${NODE_VERSION}-linux-${NA}.tar.xz"
    echo "downloading Node.js $NODE_VERSION ..."
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/${TB}" -o "$ROOT/.render-tools/$TB"
    mkdir -p "$ROOT/.render-tools/node"
    tar -xJf "$ROOT/.render-tools/$TB" -C "$ROOT/.render-tools/node" --strip-components=1
    rm -f "$ROOT/.render-tools/$TB"
  fi
fi
export PATH="$ROOT/.render-tools/node/bin:$PATH"
echo "node:    $(node --version)"

# 3. three.js + Playwright (exact versions the paper's runs used)
cd "$ROOT/.render-tools"
[ -f package.json ] || cat > package.json <<'J'
{"name":"rcwm-render-tools","private":true,"version":"1.0.0","dependencies":{"playwright":"1.62.1","three":"0.160.1"}}
J
if [ ! -f node_modules/three/build/three.module.js ] || [ ! -f node_modules/playwright/index.mjs ]; then
  npm install --no-audit --no-fund --loglevel=error
fi
echo "three:   $(node -p "require('./node_modules/three/package.json').version")"
echo "playwright: $(node -p "require('./node_modules/playwright/package.json').version")"

# 4. headless Chromium
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
if ! ls -d "$PLAYWRIGHT_BROWSERS_PATH"/chromium-* >/dev/null 2>&1; then
  npx --no-install playwright install chromium
fi
echo "chromium: $(ls -d "$PLAYWRIGHT_BROWSERS_PATH"/chromium-* | head -1)"
# Shared libraries Chromium needs (libnss3, libatk, libgbm, ...): if the smoke test below fails to launch the browser,
# run once with root:  sudo npx playwright install-deps chromium      (in $ROOT/.render-tools)

# 5. run layout + smoke test
mkdir -p "$ROOT/runs"
node "$CODE/setup/smoke_test.mjs" "$ROOT"
echo
echo "done. Use it with:   export RCWM_ROOT=$ROOT"
[ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [ "$PLAYWRIGHT_BROWSERS_PATH" != "$HOME/.cache/ms-playwright" ] && echo "                     export PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH"
exit 0
