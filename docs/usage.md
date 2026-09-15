# Complete operating guide

[Project front page](../README.md) · [Code structure](code-structure.md)

Commands below run from the repository root unless a command changes directory.
The original section numbers are retained so the cross-references still apply.

## Contents

2. [Requirements](#2-requirements)
3. [Install](#3-install)
4. [Run one scene](#4-run-one-scene)
5. [What a run produces](#5-what-a-run-produces)
6. [Options: depth, instruction, private codex home](#6-options)
7. [Several scenes in parallel, isolated](#7-several-scenes-in-parallel-isolated)
8. [Resume after an interruption](#8-resume-after-an-interruption)
9. [Inspect a run: call tree, score, interactive 3D view, high-resolution and novel-view renders](#9-inspect-a-run)
10. [Reproduce the paper's tables and figures](#10-reproduce-the-papers-tables-and-figures)
11. [Baselines and ablations](#11-baselines-and-ablations)
12. [The paper's runs in numbers](#12-the-papers-runs-in-numbers)
13. [The paper's conditions: what the code enforces, what you must check](#13-the-papers-conditions)
14. [Tests](#14-tests)
15. [Troubleshooting](#15-troubleshooting)
16. [Citation and license](#16-citation-and-license)

## 2. Requirements

- Linux x86_64 (arm64 also works for the runtime; the paper ran on Ubuntu). macOS is untested.
- CPython 3.12.x (a system `python3` with `venv`, or conda/mamba), `curl`, `tar`, `git`. Network access for the install
  and for the model. The install never touches the Python environment you are in (see §3).
- The OpenAI **Codex CLI**, logged in. Install: `npm install -g @openai/codex` (any Node ≥ 18 on PATH, or the one the setup script installs), then `codex login`. The runner calls `codex exec` once per node and parses its `session id:` and `tokens used` lines; the paper used codex-cli 0.153.0 (0.154 verified compatible).
- Model access: an account that can run `gpt-6-astra`. The runner asks for that model at reasoning effort `high` on
  every call (the paper's setting); nothing in `~/.codex/config.toml` needs editing. Another model has to be requested
  explicitly with `RCWM_MODEL` (§6); any model codex can run works mechanically, results depend on the model's eyes.
- Disk: a runtime is about 1 GB (Node + Chromium + Python packages; +1.5 GB with the metrics packages). A run writes 5–130 MB.
- No GPU is needed. Rendering is headless Chromium (software WebGL); metrics run on CPU.

## 3. Install

```bash
git clone https://github.com/ZhiqiLi-CG/RecursiveCWM_code.git
cd RecursiveCWM_code
bash setup/setup_runtime.sh /path/to/rcwm-runtime            # solver runtime only (~1 GB, a few minutes)
bash setup/setup_runtime.sh /path/to/rcwm-runtime --metrics  # ... plus the metrics/figure packages (torch CPU etc.)
export RCWM_ROOT=/path/to/rcwm-runtime
```

The script creates the layout in [docs/environment.md](environment.md): a private Python environment (Pillow,
numpy), Node.js 22 downloaded from nodejs.org (or `--node-from /path/to/node` to reuse one), three.js 0.160.1 and
Playwright 1.62.1 with headless Chromium, then renders a test cube and checks the screenshot. It is idempotent; rerun it
after a failure.

**Python compatibility.** Both the runtime and `--metrics` require CPython 3.12.x; the NumPy pin requires
3.12+, and the pinned torch/torchvision pair supports through 3.12. See [the compatibility and recovery guide](environment.md#python-compatibility).

**Python environments.** Nothing is installed into the environment you are in, and nothing needs to be activated later:
every script calls `$RCWM_ROOT/.venv/bin/python` by path.

| you use | do this | what you get |
|---|---|---|
| a system Python | `bash setup/setup_runtime.sh /path/to/rcwm-runtime` | a venv at `$RCWM_ROOT/.venv` made from `python3.12` when available, otherwise `python3` (`--python /path/to/python3.12` to choose the interpreter) |
| conda / mamba / micromamba | `bash setup/setup_runtime.sh /path/to/rcwm-runtime --conda rcwm` | a private venv at `$RCWM_ROOT/.venv`, created using Python from conda env `rcwm` (created with `python=3.12` if missing); packages already in the conda env are excluded |

`--conda` supplies an interpreter for the private venv, even when a conda `base` environment is active.
`--metrics` installs the torch/opencv/scipy/scikit-image/lpips/open_clip pins and their dependencies into that venv.
`RCWM_CONDA=/path/to/conda` names the binary when it is not on PATH. Setup isolates Python/pip from inherited
package paths and pip configuration. If an old venv has conflicting packages, rerun with `--recreate-venv`
(and `--metrics` for evaluation); the old venv is backed up and rebuilt. Old direct conda links migrate
automatically. See [dependency recovery](environment.md#dependency-conflicts-and-recovery).
Chromium's browser files go to `$PLAYWRIGHT_BROWSERS_PATH` (default `~/.cache/ms-playwright`); set that variable before
the script and before every launch if you want them elsewhere.

If the smoke test says Chromium cannot launch, the machine lacks Chromium's shared libraries; run once with root:
```bash
cd /path/to/rcwm-runtime/.render-tools && sudo npx playwright install-deps chromium
```

Omit the path to build the runtime at `<repo>/runtime` (git-ignored); then `RCWM_ROOT` need not be set.

## 4. Run one scene

```bash
export RCWM_ROOT=/path/to/rcwm-runtime
./rcwm.sh experiments/pilot-scenes/shop-row.png shop-row
```

What happens: the reference is copied to `$RCWM_ROOT/runs/shop-row/fractal/scene/target.png`, the root node's brief is
written, and `runner/solve_recursive.sh` starts the root session. Each node runs `codex exec` with the instruction, and
either delivers (`part.json` + `account.md` + its render) or writes `children.json`; the runner launches the children in
parallel as new invocations of itself, waits, then resumes the parent's session ("whole again") with the list of
delivered children. Up to `max-depth` levels and `max-cycles` whole→children→whole rounds per node. The script blocks
until the root delivers, then prints the call tree and the paths of the delivered program and render.

By default codex runs from a private home (`$RCWM_ROOT/.codex-home`) that holds only a two-line `config.toml` (the
paper's model and reasoning effort), a copy of your login file (`auth.json`, mode 600; never share or commit it) and this
repo's `worldgen-techniques` skill, so nothing else in your `~/.codex` (other skills, memories, `AGENTS.md`, config
options) is visible to the run. This is the paper's condition; §13 lists it in full. `RCWM_CLEAN_CODEX_HOME=0 ./rcwm.sh …` uses your normal home instead: every skill installed on the machine
becomes visible to the solver, and this repo's skill is not, unless you copied it into `~/.codex/skills/` yourself.

Expect one to two hours and 0.5–11 M tokens per scene (see the table in §12); the runner prints nothing while codex
works, so watch progress in another shell:

```bash
tail -f $RCWM_ROOT/runs/shop-row/fractal/scene/codex-run.log        # the root session
tail -f $RCWM_ROOT/runs/shop-row/trace/events.jsonl                 # every session start/end, child call/return
python3 runner/trace_report.py $RCWM_ROOT/runs/shop-row              # the call tree so far
```

Run it under `nohup … &` or in `tmux` for long scenes; the run survives a closed terminal only if the shell does.
A run name that already exists is refused (pick another, or resume it, §8).

## 5. What a run produces

```
$RCWM_ROOT/runs/<run-name>/
  conditions.json               what this run was launched with (instruction hash, depth, cycles, model, effort, codex home, versions)
  camera-contract.json          the camera the root locked for the reference frame (written by the solver)
  trace/events.jsonl            the runner's trace (one JSON per line; ground truth of the construction order)
  trace/tree.json, recursion_report.md     the call tree (runner/trace_report.py)
  fractal/scene/                the root node
    target.png                  the reference image (a child's target.png is its magnified crop)
    view.json, brief.md         the window in the parent's frame and the parent's brief (root: whole image)
    task.md                     the instruction as given to this node
    codex-run.log, .sid         the session transcript and session id (used to resume)
    children.json(.prev)        the children this node asked for
    part.json                   the delivered program: {"module": "component.js", "export": "build", "children": [...]} or a components list
    account.md                  the node's own account of what it did
    final.png (or the name part.json declares)   the render at the reference camera
    index.html, *.js            the node's viewer and modules (children are imported from ../<child>/)
  fractal/<child>/…             the same layout for every child, one directory per node
```

`part.json` is checked by `runner/check_part.py` for facts only (a module that exists, unique ids, children that exist).
The trace's `stop_reason` is `visual_stop` (the node judged the level done), `no_artifact` or `invalid_artifact`.

## 6. Options

| what | how |
|---|---|
| depth and cycles | `./rcwm.sh ref.png name 4 3` (positional: max depth, max cycles per node; defaults 4 and 3, the paper's values). `RCWM_MAXD` / `RCWM_MAXCYC` when calling the runner directly |
| your own instruction | `RCWM_PROMPT=/path/to/instruction.md` (placeholders `__NODE__`, `__CHAIN__`, `__DEPTH__` are substituted; the trace records the file's hash) |
| codex home | private by default (see §4); `RCWM_CLEAN_CODEX_HOME=0` for the machine's own. To build a private home yourself: `tools/make_codex_home.sh $RCWM_ROOT` and launch with `CODEX_HOME=$RCWM_ROOT/.codex-home` |
| model / reasoning effort | `RCWM_MODEL` / `RCWM_REASONING` (default `gpt-6-astra` / `high`, the paper's). The runner passes both to every codex call, so `~/.codex/config.toml` cannot change them |
| custom model provider | `RCWM_CODEX_CONFIG=/path/config.toml` puts that file in the private home instead of the two-line paper config (for an API endpoint of your own; keep `model`/`model_reasoning_effort` out of it or in agreement) |
| Chromium location | `PLAYWRIGHT_BROWSERS_PATH` (the runner makes it writable for codex) |
| the runner alone | `RCWM_ROOT=… bash runner/solve_recursive.sh runs/<name> scene - 0 <name>` after preparing `runs/<name>/fractal/scene/{target.png,view.json,brief.md}` the way `rcwm.sh` does |

## 7. Several scenes in parallel, isolated

Build the runtime once, then give every scene its own workspace whose `.venv` and `.render-tools` are symlinks to it:

```bash
export RCWM_RUNTIME=/path/to/rcwm-runtime
for s in city-full school-block shop-row; do
  ws=/work/rcwm/$s
  tools/new_workspace.sh $ws $RCWM_RUNTIME
  ( RCWM_ROOT=$ws nohup ./rcwm.sh experiments/pilot-scenes/$s.png $s > $ws/rcwm.log 2>&1 & )
  sleep 15
done
```

Each workspace has its own `runs/` and its own private `.codex-home`, so sessions of different scenes never see each other's
files or history; the root of a run is `$ws/runs/<name>`. Ten scenes in parallel each spawn up to a few dozen codex
sessions over time; the limiting resources are the model's rate/quota and disk (check `df` before a batch: a full disk
makes every session fail silently with ENOSPC).

## 8. Resume after an interruption

If the machine, the shell or the model's quota stopped a run, resume it in place. Nothing that was delivered is redone:

```bash
RCWM_ROOT=/work/rcwm/shop-row tools/resume_run.sh shop-row
```

The root runner is re-invoked with the same instruction (`RCWM_PROMPT` / `RCWM_MAXD` / `RCWM_MAXCYC` must
match the original launch; the defaults match `rcwm.sh`'s defaults). Every node continues its own codex session by its
`.sid`. A node that had asked for children of which some never delivered relaunches only those (trace event
`recover_children`) instead of waking the parent with an incomplete set. If the run used a private codex home, it is
reused and its login file refreshed from `~/.codex/auth.json` first (so log in again before resuming after a quota or
credential problem); a run started with `RCWM_CLEAN_CODEX_HOME=0` keeps using the machine's home. The same works for the runner call in §6 by hand.

## 9. Inspect a run

**Call tree.** `python3 runner/trace_report.py $RCWM_ROOT/runs/<name>` prints and writes `trace/recursion_report.md`
(every `solve(node)` with depth, sessions, tokens and stop reason) and `trace/tree.json`.

**What went wrong?** `tools/diagnose_run.sh $RCWM_ROOT/runs/<name>` reads only the run's own files: tree shape and cost,
every node's delivery and how many renders it made (a node with none worked blind), the stop reasons, and the failure
signatures in the session logs (Chromium not launching, sandbox denials, full disk, quota, dropped connections). Paste
its output when asking for help.

**Score.** With the metrics packages installed (`--metrics`), one JSON line with the chosen final render, PSNR / SSIM /
edge-F1 / LPIPS / CLIP against the reference, nodes, depth, nodes per level, delivered parts, tokens and wall time:

```bash
RCWM_REFS=experiments/pilot-scenes $RCWM_ROOT/.venv/bin/python tools/score_run.py shop-row $RCWM_ROOT/runs/shop-row
```

`RCWM_REFS` is the directory holding `<scene>.png` (default `experiments/pilot-scenes`). The line is also written to
`runs/<name>/trace/score.json`, and appended to `$RCWM_SCORES` if set. The first call downloads the LPIPS and CLIP weights.

**Open the world in 3D (drag to orbit).** The delivered program is a scene, not a picture; view it interactively:

```bash
tools/view.sh $RCWM_ROOT/runs/shop-row            # prints  http://127.0.0.1:8000/runs/shop-row/fractal/scene/index.html
```

Open that URL in a browser: drag to orbit, right-drag (or shift-drag) to pan, wheel to zoom, `R` returns to the
delivered camera, `H` hides the hint; add `?clean=1` to hide the viewer's own overlays (view tabs, badges, pins). The
server serves the workspace read-only and injects orbit controls into the page on the fly, so it works for every
delivered viewer without changing its files (the delivered `index.html` itself renders a fixed camera). A second
argument sets the port. On a remote machine, forward the port first, then open the same URL locally:

```bash
ssh -L 8000:127.0.0.1:8000 <server>               # on your laptop; then tools/view.sh … on the server
```

Child nodes that ship their own `index.html` open the same way (`/runs/<name>/fractal/<node>/index.html`); most
children deliver modules that are rendered through the root's viewer. Without the tool, any static server on the
workspace root (`python3 -m http.server`) shows the delivered page at its fixed camera.

**High-resolution and novel-view renders.** Re-render the delivered program at 4× the reference frame and from five
cameras it was never shown from (±35° azimuth, a high orbit, two close-ups):

```bash
tools/render_views.sh $RCWM_ROOT/runs/shop-row 4
# -> runs/shop-row/fractal/scene/final-hires.png and fractal/scene/novel-views/view-{L35,R35,orbit,close1,close2}.png
```

The harnesses (`tools/hires_render.mjs`, `tools/novel_views.mjs`, `tools/teaser_render.mjs`) hook the served
`three.module.js` to reach the viewer's renderer, scene and camera, so they work on any delivered viewer without wiring.
Arguments: workspace root, page path under it, output, and optionally scale, a JavaScript "ready" expression (default:
`window.ready` and the common variants; a viewer without one is captured after a timeout, `RCWM_READY_TIMEOUT_MS`) and
`WxH`. `teaser_render.mjs` hides every screen-space overlay and, with a name regex, chosen scene objects (for example
location pins), writing only the WebGL canvas.

## 10. Reproduce the paper's tables and figures

The scripts read runs through `experiments/pickers.py` (one rule per method for "which image is the method's final
render") and are configured by environment variables so they contain no machine paths:

| variable | meaning |
|---|---|
| `RCWM_ROOT` | runtime/workspace root that holds `runs/` |
| `RCWM_REFS` | directory with the ten reference images `<scene>.png` (see `experiments/pilot-scenes/REFERENCES.md` to rebuild the five WorldClaw crops; the exact files are in the paper repository) |
| `RCWM_OURS_CHAIN` | where our run of each scene is, with `{scene}` substituted: e.g. `'/work/rcwm/{scene}/runs/{scene}'` (absolute pattern = one workspace per scene). Default: `runs/pilot/{scene}-recursive-r1` |
| `RCWM_OURS_OVERRIDE` | `scene=/path/render.png,…` forces the render used for a scene's figure (we used the 4× renders) |
| `RCWM_SEIG`, `RCWM_SEIG_RUN`, `RCWM_VIGA`, `RCWM_VIGA_TESTID`, `RCWM_I2T_ISO`, `RCWM_I2T_ISO_ALL=1` | where the baselines' outputs are (see `baselines/external/README.md`) |
| `RCWM_METRICS_CSV` | the CSV the metrics are accumulated in (default `$RCWM_ROOT/runs/pilot/metrics/all-methods-full.csv`) |
| `RCWM_PAPER` / `RCWM_NO_PAPER=1` | paper checkout whose `sections/04_experiments.tex` receives the table, or write the table next to the CSV only |

```bash
PY=$RCWM_ROOT/.venv/bin/python
$PY experiments/refresh_metrics.py                      # metrics of every (scene, method) → $RCWM_METRICS_CSV
RCWM_NO_PAPER=1 python3 experiments/main_table.py       # Table 1 (LaTeX + markdown next to the CSV)
$PY experiments/make_case_figures.py OUT --full city-full,medieval-village \
   --ours snow-village,island-harbor,japan-island,school-block,police-corner,park-lake,shop-row,valley-village
                                                        # Figs. 3-4 (reference | ours | baselines, progressive detail windows)
                                                        # and Figs. 5-8 (reference vs ours); RCWM_CASE_CANW=2000 for 4× renders,
                                                        # RCWM_CASE_FIX='scene=idx:fx,fy,ws;…' pins detail windows by hand
$PY experiments/make_novel_views.py OUT/novel-views-grid.png   # Fig. 9: one row per scene, reference camera + five novel views
                                                        # (reads fractal/scene/novel-views/ written by tools/render_views.sh)
python3 experiments/variant_table.py                    # ablation table (Table 2/3) from runs/pilot/<scene>-<variant>-r1
```

`experiments/eval_metrics.py reference.png render.png` computes one pair's metrics (JSON); metrics missing a library
come out `null`. Scores are recorded only; nothing in the pipeline reads them.

## 11. Baselines and ablations

**Ablation (structural controls).** Same runner, different instruction and depth cap:

```bash
experiments/run_matrix.sh "school-block medieval-village" "flat localglobal globallocal twolevel recursive" 1 4
```

`flat` = `baselines/variants/flat-zoom.md` at depth 0; `localglobal` at depth 1; `globallocal` at depth 0;
`twolevel` = the main instruction with `RCWM_MAXD=1`; `recursive` = the main instruction at depth 4. Runs land in
`$RCWM_ROOT/runs/pilot/<scene>-<variant>-r1`, rows in `runs/pilot/results.csv`; the last argument limits concurrent
codex processes (it counts every `codex exec` on the machine). References come from `$RCWM_REFS/<scene>.png` (default `experiments/pilot-scenes/`).

**External baselines.** `baselines/external/README.md` describes the three (SEIG reproduction, VIGA with the official
runner and a codex shim, img2threejs in an isolated directory per scene) and their launch scripts; each needs its own
checkout (`RCWM_SEIG`, `RCWM_VIGA` + `BLENDER`, `$RCWM_ROOT/vendor/img2threejs` + `RCWM_I2T_ISO`). Every method receives
the reference image unmodified.

## 12. The paper's runs in numbers

The ten runs behind the paper's main table (Table 1), scored with `tools/score_run.py`. Use them to know what to expect
from a scene of a given size:

| scene | nodes | max depth | nodes per level | PSNR↑ | SSIM↑ | Edge F1↑ | LPIPS↓ | CLIP↑ | tokens (M) | wall (min) |
|---|---|---|---|---|---|---|---|---|---|---|
| city-full | 24 | 4 | 1/4/12/6/1 | 18.2 | 0.66 | 0.94 | 0.158 | 0.95 | 2.4 | 69 |
| snow-village | 83 | 4 | 1/3/10/27/42 | 17.9 | 0.73 | 0.84 | 0.237 | 0.83 | 9.2 | 79 |
| island-harbor | 57 | 4 | 1/3/11/22/20 | 17.4 | 0.74 | 0.90 | 0.186 | 0.93 | 10.9 | 121 |
| medieval-village | 24 | 4 | 1/2/6/11/4 | 18.7 | 0.71 | 0.89 | 0.200 | 0.93 | 3.2 | 77 |
| japan-island | 29 | 3 | 1/4/10/14 | 19.3 | 0.73 | 0.87 | 0.201 | 0.96 | 3.9 | 79 |
| school-block | 12 | 3 | 1/3/6/2 | 16.4 | 0.56 | 0.97 | 0.171 | 0.94 | 1.1 | 65 |
| police-corner | 7 | 2 | 1/3/3 | 16.6 | 0.44 | 0.97 | 0.159 | 0.91 | 0.5 | 31 |
| park-lake | 12 | 3 | 1/3/6/2 | 23.3 | 0.83 | 0.99 | 0.075 | 0.95 | 1.1 | 55 |
| shop-row | 9 | 2 | 1/3/5 | 17.4 | 0.65 | 0.96 | 0.120 | 0.96 | 0.8 | 54 |
| valley-village | 21 | 3 | 1/3/9/8 | 14.1 | 0.38 | 0.48 | 0.583 | 0.87 | 3.2 | 86 |

Depth 0 is the root, so "max depth 4" is five levels. Tokens are summed over every session of the run; wall time is
first to last trace event. The delivered programs and full traces of medieval-village and city-full can be explored node
by node on the project page.

## 13. The paper's conditions

Following §3 and §4 as written reproduces the paper's condition. What the code enforces, and what only you can check:

| condition | paper | enforced by |
|---|---|---|
| instruction | `solver/solver-template.md`, sha256 `8f194d22f285…` | default `RCWM_PROMPT`; hash printed at launch, recorded in `conditions.json` and in every trace event |
| recursion limits | depth ≤ 4, ≤ 3 cycles per node | defaults of `rcwm.sh` |
| executor | `gpt-6-astra`, reasoning effort `high` | passed to every `codex exec` (`-c model`, `-c model_reasoning_effort`) whatever `~/.codex/config.toml` says; recorded in `conditions.json` and each `session_start` event |
| what codex can see | only this repo's `worldgen-techniques` skill (English); no other skills, memories, `AGENTS.md` or config options | private codex home, built at launch (default). `rcwm.sh` prints `codex home: private (…); skills: worldgen-techniques` |
| sandbox | workspace-write, network on, Chromium cache writable | the runner's `codex exec` flags |
| root brief and environment note | identical text | `rcwm.sh` |
| runtime | Node 22.14, three 0.160.1, Playwright 1.62.1 with Chromium; Python 3.12 with Pillow 12.3, numpy 2.5 | `setup/setup_runtime.sh` pins them; versions recorded in `conditions.json` |
| codex CLI | 0.153.0 (0.154 verified compatible) | **you**: `rcwm.sh` prints a note for any other version; the runner parses codex's `session id` and `tokens used` lines |
| model access | an account that can run `gpt-6-astra` | **you**: `codex login`; a different model must be requested explicitly with `RCWM_MODEL` |
| reference image | unmodified, at the size given (figure furniture kept) | **you**: pass the file as is |
| isolation | one workspace per scene, nothing else in it | **you**: `tools/new_workspace.sh` per scene (§7); do not put other material under `$RCWM_ROOT` |

Anything you change on purpose (`RCWM_MODEL`, `RCWM_REASONING`, `RCWM_PROMPT`, `RCWM_CLEAN_CODEX_HOME=0`,
`RCWM_CODEX_CONFIG`) is written to `runs/<name>/conditions.json`, so a run always carries the record of how it differs.
`tests/test_runner_offline.sh` checks the enforced rows with a fake codex (§14).

## 14. Tests

```bash
bash tests/test_runner_offline.sh $RCWM_ROOT          # the whole launch with a fake codex (no model, no network): private home,
                                                      # paper model/effort passed, root cuts two children, children delivered,
                                                      # parent resumed, trace, conditions.json, trace_report, check_part
$RCWM_ROOT/.venv/bin/python -m pytest tests/         # crop-homography geometry (needs the --metrics packages for pytest)
$RCWM_ROOT/.render-tools/node/bin/node setup/smoke_test.mjs $RCWM_ROOT   # the render path (three.js in headless Chromium + Pillow)
```

## 15. Troubleshooting

- **`codex CLI not found` / `RCWM_ROOT … is not a runtime root`.** Install and log in to codex; run `setup/setup_runtime.sh`.
- **A node loops asking for children at the deepest level.** The runner appends a max-depth note to the instruction at
  `RCWM_MAXD`; if you lowered the cap after a launch, resume with the same cap.
- **`hit your usage limit` in a `codex-run.log`.** The model's quota ran out: sessions end without delivering. Wait or
  log in with another account, then `tools/resume_run.sh <name>` (it copies the fresh `auth.json` into the private home).
- **Every session fails at once.** Check `df`: a full disk (ENOSPC) kills renders and codex silently.
- **Chromium does not launch.** `sudo npx playwright install-deps chromium` in `$RCWM_ROOT/.render-tools`; keep
  `PLAYWRIGHT_BROWSERS_PATH` identical at setup and launch.
- **The render harness reports `hookMissing`.** The viewer does not import `three.module.js` through the served root
  (bundled or CDN three); render with the viewer's own controls, or point the page's import at `/.render-tools/node_modules/three/build/three.module.js`.
- **The harness waits three minutes before capturing.** The viewer sets no `window.ready` flag; pass your own ready
  expression as the fourth argument, or lower `RCWM_READY_TIMEOUT_MS`.
- **`pickers.ours` warns "no recognised final render name".** The node delivered but named its render unusually; look in
  `fractal/scene/`, then pass it with `RCWM_OURS_OVERRIDE=scene=/path.png` or add the name to `part.json`'s `evidence.final_render`.
- **The solver behaves differently on another machine.** Compare `runs/<name>/conditions.json` with the table in §13:
  the instruction hash, model, effort, codex home and versions are all there. `codex home: … the machine's own` means the
  run was started with `RCWM_CLEAN_CODEX_HOME=0` and sees that machine's skills.

## 16. Citation and license

```bibtex
@article{li2026rcwm,
  title   = {Recursive Code World Models: Building Complex Worlds through Recursive Scene Programs},
  author  = {Li, Zhiqi and Liao, Yuxuan and Zhu, Bo},
  journal = {arXiv preprint arXiv:2609.11499},
  year    = {2026}
}
```

MIT License (see `LICENSE`). The city reference images are from the CC0 "Isometric city" sprite pack by JanaChumi
(OpenGameArt); `medieval-village.png` is a crop of Fig. 9 of the WorldClaw paper, used only as an input image; the other
four WorldClaw-derived references are not redistributed (`experiments/pilot-scenes/REFERENCES.md`).
