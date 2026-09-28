#!/bin/bash
# Recursive Code World Models — single entry point.
#   rcwm.sh <reference.png> <run-name> [max-depth=4] [max-cycles=3]
# One reference image in; one executable Three.js scene program out, built by the
# recursive solver (whole -> parts -> whole again at every level; depth chosen by the model).
#
# Needs: codex CLI logged in; a runtime root (env RCWM_ROOT, default <repo>/runtime) built by
# setup/setup_runtime.sh (.venv with Pillow/numpy, .render-tools with node+three+playwright).
# Env: RCWM_PROMPT=<file>      a different instruction file (default solver/solver-template.md)
#      RCWM_MODEL / RCWM_REASONING   executor (default gpt-6-astra / high, the paper's; passed to every codex call)
#      RCWM_CLEAN_CODEX_HOME=0 use the machine's own codex home (~/.codex: its skills, memories, AGENTS.md) instead of the
#                              default private home under $RCWM_ROOT/.codex-home (two-line config + login + only this repo's skill)
#      RCWM_CODEX_CONFIG=<file> config.toml to put in the private home instead of the two-line one (custom model provider)
set -uo pipefail
REF="${1:?usage: rcwm.sh <reference.png> <run-name> [max-depth=4] [max-cycles=3]}"
NAME="${2:?usage: rcwm.sh <reference.png> <run-name> [max-depth=4] [max-cycles=3]}"
[ "$(basename -- "$NAME")" = "$NAME" ] && [[ "$NAME" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "invalid run name"; exit 2; }
export RCWM_MAXD="${3:-4}" RCWM_MAXCYC="${4:-3}"
export RCWM_CODE="$(cd "$(dirname "$0")" && pwd)"
export RCWM_ROOT="${RCWM_ROOT:-$RCWM_CODE/runtime}"
export RCWM_PROMPT="${RCWM_PROMPT:-$RCWM_CODE/solver/solver-template.md}"
[ -d "$RCWM_ROOT" ] || { echo "RCWM_ROOT=$RCWM_ROOT does not exist; build it with setup/setup_runtime.sh (see docs/environment.md)"; exit 1; }
[ -x "$RCWM_ROOT/.render-tools/node/bin/node" ] && [ -x "$RCWM_ROOT/.venv/bin/python" ] || { echo "RCWM_ROOT=$RCWM_ROOT is not a runtime root (no .render-tools/node or .venv); run setup/setup_runtime.sh $RCWM_ROOT"; exit 1; }
[ -f "$RCWM_PROMPT" ] || { echo "instruction file not found: $RCWM_PROMPT"; exit 1; }
command -v codex >/dev/null || { echo "codex CLI not found (npm install -g @openai/codex; then codex login)"; exit 1; }
export RCWM_MODEL="${RCWM_MODEL:-gpt-6-astra}" RCWM_REASONING="${RCWM_REASONING:-high}"   # the paper's executor; the runner passes both explicitly
# Default: run codex from a private home that carries only a two-line config (the paper's model and reasoning
# effort), its login and this repo's worldgen-techniques skill — none of the skills, memories, AGENTS.md or
# config options installed on the machine (the paper's condition). RCWM_CLEAN_CODEX_HOME=0 keeps the machine's own
# home; RCWM_CODEX_CONFIG=<file> copies that config.toml instead (for a custom model provider).
if [ "${RCWM_CLEAN_CODEX_HOME:-1}" != "0" ]; then
  SRC="${CODEX_HOME:-$HOME/.codex}"; CH="$RCWM_ROOT/.codex-home"
  mkdir -p "$CH/skills" && chmod 700 "$CH"
  if [ -n "${RCWM_CODEX_CONFIG:-}" ]; then cp "$RCWM_CODEX_CONFIG" "$CH/config.toml"
  else printf 'model = "%s"\nmodel_reasoning_effort = "%s"\n' "$RCWM_MODEL" "$RCWM_REASONING" > "$CH/config.toml"; fi
  [ -f "$SRC/auth.json" ] && cp "$SRC/auth.json" "$CH/" && chmod 600 "$CH/auth.json"
  [ -f "$CH/auth.json" ] || { echo "no codex login found at $SRC/auth.json (run 'codex login' first)"; exit 1; }
  rm -rf "$CH/skills/worldgen-techniques" && mkdir -p "$CH/skills/worldgen-techniques"
  cp "$RCWM_CODE/skills/worldgen-techniques/SKILL.md" "$CH/skills/worldgen-techniques/SKILL.md"
  export CODEX_HOME="$CH"
  HOME_NOTE="private ($CH); skills: $(ls "$CH/skills" | tr '\n' ' ')"
else
  HOME_NOTE="${CODEX_HOME:-$HOME/.codex} (the machine's own; its skills are visible to the run)"
fi
CODEX_VER=$(codex --version 2>/dev/null | grep -o '[0-9][0-9.]*' | head -1)
case "$CODEX_VER" in 0.153*|0.154*) ;; *) echo "note: codex CLI $CODEX_VER; the paper used 0.153 (0.154 verified compatible); the runner parses its 'session id' and 'tokens used' lines";; esac
CH="runs/$NAME"; D="$RCWM_ROOT/$CH/fractal/scene"
[ -e "$D/target.png" ] && { echo "run exists: $RCWM_ROOT/$CH (pick another name, or rerun the runner to resume)"; exit 1; }
mkdir -p "$D" "$RCWM_ROOT/$CH/trace" "$RCWM_ROOT/$CH/logs"
exec > >(tee -a "$RCWM_ROOT/$CH/logs/run.log") 2>&1
cp "$REF" "$D/target.png"
echo '{"note":"root chooses its own framing"}' > "$D/view.json"
cat > "$D/brief.md" <<B
Rebuild everything visible in target.png as a parameterized Three.js scene program
(first solve and calibrate a camera; verify the full-frame overlay by eye before locking it).
Rendering environment: $RCWM_CODE/docs/environment.md (RCWM_ROOT=$RCWM_ROOT).
B
# The conditions of this run, next to its trace; compare with the paper's (README, "The paper's conditions").
NODEBIN="$RCWM_ROOT/.render-tools/node/bin/node"
python3 - "$RCWM_ROOT/$CH/conditions.json" <<J
import json,sys,subprocess,hashlib,os
def v(cmd):
    try: return subprocess.run(cmd,capture_output=True,text=True,timeout=20).stdout.strip()
    except Exception: return None
def pkg(name):
    try: return json.load(open("$RCWM_ROOT/.render-tools/node_modules/"+name+"/package.json"))["version"]
    except Exception: return None
d={"output_contract_version":2,"output_contract_sha256":hashlib.sha256(open("$RCWM_CODE/docs/output-contract.md","rb").read()).hexdigest(),"run":"$RCWM_ROOT/$CH","reference":"$REF","instruction":"$RCWM_PROMPT",
   "instruction_sha256":hashlib.sha256(open("$RCWM_PROMPT","rb").read()).hexdigest()[:12],
   "max_depth":int("$RCWM_MAXD"),"max_cycles":int("$RCWM_MAXCYC"),"model":"$RCWM_MODEL","reasoning_effort":"$RCWM_REASONING",
   "codex_cli":"$CODEX_VER","codex_home":"$HOME_NOTE",
   "node":v(["$NODEBIN","--version"]),"three":pkg("three"),"playwright":pkg("playwright"),
   "python":v(["$RCWM_ROOT/.venv/bin/python","--version"]),"code_commit":v(["git","-C","$RCWM_CODE","rev-parse","--short","HEAD"])}
json.dump(d,open(sys.argv[1],"w"),indent=1)
print("conditions:", ", ".join(f"{k}={d[k]}" for k in ("instruction_sha256","max_depth","max_cycles","model","reasoning_effort","codex_cli","node","three","playwright")))
J
echo "codex home: $HOME_NOTE"
echo "run:      $RCWM_ROOT/$CH"
echo "solver:   $RCWM_PROMPT  (max depth $RCWM_MAXD, max cycles/node $RCWM_MAXCYC)"
echo "trace:    $RCWM_ROOT/$CH/trace/events.jsonl"
bash "$RCWM_CODE/runner/solve_recursive.sh" "$CH" scene - 0 "$NAME"
RUN_STATUS=$?
echo
python3 "$RCWM_CODE/runner/trace_report.py" "$RCWM_ROOT/$CH" 2>/dev/null | tail -3
if [ "$RUN_STATUS" -eq 0 ] && "$RCWM_ROOT/.venv/bin/python" "$RCWM_CODE/runner/delivery.py" "$RCWM_ROOT/$CH" --run; then
  echo "delivered: $D/part.json"
  echo "result: $RCWM_ROOT/$CH/result.json"
  exit 0
fi
echo "run failed — see $RCWM_ROOT/$CH/result.json and $D/logs/codex.log"
exit 1
