#!/bin/bash
# test_runner_offline.sh [RCWM_ROOT] : runs rcwm.sh end to end with a fake codex (tests/fake-codex, no model, no
# network) in a throw-away workspace and checks the runner's contract: private codex home with only our skill, the
# paper's model/effort passed to codex, a root that cuts two children, children delivered in parallel, the parent
# resumed for "whole again", trace events, conditions.json, and trace_report. Needs a runtime root (setup_runtime.sh).
set -uo pipefail
CODE="$(cd "$(dirname "$0")/.." && pwd)"
RT="${1:-${RCWM_ROOT:-$CODE/runtime}}"
[ -x "$RT/.venv/bin/python" ] && [ -x "$RT/.render-tools/node/bin/node" ] || { echo "no runtime at $RT (run setup/setup_runtime.sh)"; exit 1; }
WS="$(mktemp -d "${TMPDIR:-/tmp}/rcwm-offline.XXXXXX")"
fail() { echo "FAIL: $*"; echo "workspace kept: $WS"; exit 1; }
"$CODE/tools/new_workspace.sh" "$WS" "$RT" >/dev/null || fail "new_workspace"
# a fake codex login so the private home can be built without touching ~/.codex
FAKEHOME="$WS/.fake-user-codex"; mkdir -p "$FAKEHOME/skills/some-other-skill"; echo '{"fake":true}' > "$FAKEHOME/auth.json"; echo "# not ours" > "$FAKEHOME/skills/some-other-skill/SKILL.md"
export PATH="$CODE/tests/fake-codex:$PATH" CODEX_HOME="$FAKEHOME" RCWM_ROOT="$WS"
"$RT/.venv/bin/python" -c "from PIL import Image; Image.new('RGB',(320,200),(90,140,200)).save('$WS/ref.png')"
( cd "$CODE" && ./rcwm.sh "$WS/ref.png" offline 4 3 > "$WS/rcwm.log" 2>&1 ) || fail "rcwm.sh exited non-zero: $(tail -3 "$WS/rcwm.log")"
R="$WS/runs/offline"
[ -f "$R/fractal/scene/part.json" ] || fail "root did not deliver"
[ -f "$R/fractal/house-a/part.json" ] && [ -f "$R/fractal/house-b/part.json" ] || fail "children did not deliver"
[ -f "$R/conditions.json" ] || fail "no conditions.json"
grep -q '"model": "gpt-6-astra"' "$R/conditions.json" && grep -q '"reasoning_effort": "high"' "$R/conditions.json" || fail "conditions.json lacks the paper's model/effort"
grep -q '"instruction_sha256"' "$R/conditions.json" || fail "conditions.json lacks the instruction hash"
[ "$(ls "$WS/.codex-home/skills")" = "worldgen-techniques" ] || fail "private home skills: $(ls "$WS/.codex-home/skills")"
[ "$(cat "$WS/.codex-home/config.toml")" = "$(printf 'model = "gpt-6-astra"\nmodel_reasoning_effort = "high"')" ] || fail "private config is not the two paper lines"
EV="$R/trace/events.jsonl"
for e in session_start session_end child_call child_return stop; do grep -q "\"event\":\"$e\"" "$EV" || fail "trace lacks $e"; done
grep -q '"event":"session_start".*"model":"gpt-6-astra","reasoning":"high"' "$EV" || fail "trace does not record model/effort"
[ "$(grep -c '"event":"child_call"' "$EV")" = 2 ] || fail "expected 2 child calls"
[ "$(grep -c '"node_id":"scene".*"event":"session_end"' "$EV")" = 2 ] || fail "root should have 2 sessions (cut, then whole again)"
grep -q '"stop_reason":"completed"' "$EV" || fail "no completed status"
python3 "$CODE/runner/trace_report.py" "$R" | grep -q "max depth: 1; nodes: 3" || fail "trace_report tree"
"$RT/.venv/bin/python" "$CODE/runner/check_part.py" "$R/fractal/scene/part.json" | grep -q "^ok" || fail "check_part"
echo "offline runner test ok ($R)"; rm -rf "$WS"
