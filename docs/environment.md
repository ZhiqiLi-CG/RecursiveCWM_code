# Runtime environment (RCWM_ROOT layout)

Every solver session is pointed at a runtime root (env `RCWM_ROOT`, default `<repo>/runtime`). It holds four things:

```
$RCWM_ROOT/
  .venv/bin/python                         # CPython 3.12.x with Pillow and numpy (side-by-sides, crops, diffs)
  .render-tools/node/bin/node              # Node.js 22
  .render-tools/node_modules/three/        # three.js 0.160.1 (build/three.module.js)
  .render-tools/node_modules/playwright/   # Playwright 1.62.1 with headless Chromium (renders, screenshots)
  runs/<run-name>/                         # one directory per run; the runner creates it
```

`setup/setup_runtime.sh <dir>` builds exactly this (plus a smoke render) without touching the Python environment you
are in: `.venv` is always a private venv. It is made from `python3.12` when available, otherwise
`python3` (`--python <interpreter>` to choose). With `--conda <env>`, conda supplies Python 3.12
(creating the named environment if missing); its installed packages are excluded from the venv. Add `--metrics` to also install the packages the
record-only metrics, tables and figures need (torch CPU, opencv, scikit-image, lpips, open_clip); those are never seen
by the solver. `--node-from <dir>` symlinks an existing Node.js installation instead of downloading one.

Headless Chromium lives in `$PLAYWRIGHT_BROWSERS_PATH` (default `~/.cache/ms-playwright`). The runner grants codex write
access to that directory (Playwright touches it), so set the variable before launching if you moved the browsers.

Shell setup a solver session uses:

```bash
cd $RCWM_ROOT
export PATH="$RCWM_ROOT/.render-tools/node/bin:$PATH"
# three:      $RCWM_ROOT/.render-tools/node_modules/three/build/three.module.js
# playwright: $RCWM_ROOT/.render-tools/node_modules/playwright  (Chromium in $PLAYWRIGHT_BROWSERS_PATH or ~/.cache/ms-playwright)
```

Recommended render size 1400×900. Each run keeps its own `camera-contract.json` at the run root.
Nothing else is required: the scene programs the solver writes import three.js directly and drive Playwright themselves.

## Python compatibility

The supported interpreter for both the runtime and `--metrics` is **CPython 3.12.x**.
[`.python-version`](../.python-version) is the setup script's source of truth for the version check,
default interpreter lookup, and new conda environments. Any 3.12 patch release is accepted.
The original package pins retain the paper's versions; SciPy is now explicitly pinned for the color metric:

| Package | Python constraint for the pinned release |
|---|---|
| [numpy 2.5.2](https://pypi.org/project/numpy/2.5.2/) | Requires Python >=3.12 |
| [Pillow 12.3.0](https://pypi.org/project/pillow/12.3.0/) | Requires Python >=3.10 |
| [torch 2.5.1 / torchvision 0.20.1](https://pypi.org/project/torchvision/0.20.1/) | The supported pair covers Python 3.9–3.12 |
| [scikit-image 0.26.0](https://pypi.org/project/scikit-image/0.26.0/) | Requires Python >=3.11 |
| Other metrics/test pins | Permit Python 3.12 |

The previous 3.10–3.12 claim was incompatible with the NumPy pin. Python 3.13+ is outside the
supported range of the pinned torch/torchvision pair. Use 3.12 for the base runtime too so that
adding `--metrics` later uses the same environment. Setup resolves runtime and metrics requirements
together and runs `pip check` before installing the rendering tools.

For a new venv, setup honors `--python`, then `PYTHON`; otherwise it tries `python3.12` on PATH,
then checks `python3`. With `--conda`, it creates a missing environment with Python 3.12 or validates
the existing one before using its interpreter to create the venv. An incompatible interpreter fails before packages are installed.

### Dependency conflicts and recovery

Setup uses Python's isolated mode and ignores pip configuration/environment overrides so that user-site
packages, `PYTHONPATH`, `PIP_TARGET`, `PIP_USER`, or `PIP_NO_DEPS` cannot redirect the install or skip dependencies.
The metrics requirements include the base runtime pins and explicitly require SciPy. All selected packages
are resolved together, followed by `pip check` and import checks before rendering setup.

Warnings about `cmapy`, `kaolin`, or `kappamodules` indicate other packages visible in the environment;
this repository does not depend on them. Use a private venv for this project. Only the headless OpenCV
distribution is installed here; adding `opencv-python` alongside it would put two packages in charge of `cv2`.

**Recovering from an earlier failed setup:** use `--recreate-venv` to back up the old `.venv` under
`$RCWM_ROOT/.venv-backup.XXXXXX/.venv`, create a fresh environment, and reinstall the selected dependencies:

```bash
bash setup/setup_runtime.sh "$RCWM_ROOT" --conda rcwm-py312 --recreate-venv --metrics
# Or use an installed Python 3.12:
bash setup/setup_runtime.sh "$RCWM_ROOT" --python /path/to/python3.12 --recreate-venv --metrics
```

Omit `--metrics` if you only need the solver. Existing runs and rendering tools are kept. The backup is for
recovery, not for execution at its moved path. Old `.venv` symlinks pointing directly to conda environments
are migrated automatically: the link is backed up, and the original conda environment is left intact.
Keep the source Python/conda environment installed, since the private venv uses its interpreter.

Without `--recreate-venv`, an existing private venv is reused and checked; `--python`/`--conda` select the
interpreter used to create a new one. An existing conda environment with the wrong Python version is
rejected; choose a new environment name. Setup does not change its Python version automatically.

## One runtime, many isolated workspaces

A workspace is any directory with this layout. `tools/new_workspace.sh <dir> <runtime>` creates one whose `.venv` and
`.render-tools` are symlinks to a runtime built once, with its own `runs/` and its own private `.codex-home` (the default
of `rcwm.sh`). Running each scene in its own workspace keeps sessions of different scenes from seeing each other's files;
the paper's final batch was run that way, one workspace per scene, all ten in parallel.

## What the paper's runs used

| piece | version |
|---|---|
| executor | `codex` CLI 0.153.0 (0.154 verified compatible), model `gpt-6-astra`, reasoning effort `high` |
| Python | 3.12.3; Pillow 12.3.0, numpy 2.5.2 |
| Node.js | 22.14.0; three 0.160.1; Playwright 1.62.1 (Chromium build 1234) |
| metrics only | torch 2.5.1 (CPU), opencv-python-headless 5.0, scikit-image 0.26, lpips 0.1.4, open_clip_torch 3.3 |
| OS | Linux x86_64 (Ubuntu, kernel 6.8) |
