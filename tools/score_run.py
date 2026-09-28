#!/usr/bin/env python3
"""score_run.py <scene-name> <run-dir> [label]
One JSON line per run: the final render (chosen by experiments/pickers.ours), the record-only metrics against the
reference image, the real recursion tree (nodes, depth, nodes per level), delivered parts, tokens and wall time.
  scene-name  the reference image is $RCWM_REFS/<scene-name>.png (default: experiments/pilot-scenes)
  run-dir     $RCWM_ROOT/runs/<run-name> of a finished (or stopped) run
Run it with the runtime's python ($RCWM_ROOT/.venv/bin/python, metrics packages installed) so eval_metrics.py
finds its libraries; metrics that lack a library come back null. Also writes <run-dir>/trace/score.json and, if
RCWM_SCORES is set, appends the line to that jsonl file."""
import sys, os, json, glob, collections, datetime, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(CODE, 'experiments'))
if len(sys.argv) < 3: raise SystemExit(__doc__)
scene, run = sys.argv[1], os.path.abspath(sys.argv[2].rstrip('/')); label = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(run)
refs = os.environ.get('RCWM_REFS', os.path.join(CODE, 'experiments', 'pilot-scenes')); ref = os.path.join(refs, scene + '.png')
os.environ['RCWM_OURS_CHAIN'] = run
try: import pickers
except ImportError as e: raise SystemExit(f'{e}: run this with the runtime python, $RCWM_ROOT/.venv/bin/python (setup/setup_runtime.sh --metrics)')
p, fin = pickers.ours(os.environ.get('RCWM_ROOT', os.path.dirname(os.path.dirname(run))), scene)
out = {'label': label, 'scene': scene, 'run': run, 'render': p, 'final': fin}
if p and fin and os.path.isfile(ref):
    r = subprocess.run([sys.executable, os.path.join(CODE, 'experiments', 'eval_metrics.py'), ref, p], capture_output=True, text=True, timeout=1800)
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
        out.update({k: (round(float(d[k]), 3) if d.get(k) is not None else None) for k in ('psnr', 'ssim', 'edge_f1', 'lpips', 'clip_sim')})
    except Exception: out['metrics_error'] = r.stderr[-300:]
elif not os.path.isfile(ref): out['metrics_error'] = f'no reference image {ref} (set RCWM_REFS)'
dep, ts = {}, []
ev = os.path.join(run, 'trace', 'events.jsonl')
if os.path.isfile(ev):
    for l in open(ev):
        try: e = json.loads(l.replace('"usage_total":}', '"usage_total":0}'))
        except Exception: continue
        ts.append(e['ts'])
        if e.get('event') == 'session_start': dep[e['node_id']] = e['depth']
c = collections.Counter(dep.values()); out['nodes'] = len(dep); out['depth'] = max(c) if c else 0; out['per_level'] = [c[i] for i in range(out['depth'] + 1)]
out['parts'] = len(glob.glob(os.path.join(run, 'fractal', '**', 'part.json'), recursive=True))
tok = 0
if os.path.isfile(os.path.join(run, 'result.json')) and os.path.isfile(ev):
    for line in open(ev):
        try:
            event=json.loads(line)
            if event.get('event')=='session_end': tok += event.get('usage_total') or 0
        except ValueError: pass
else:
    for f in glob.glob(os.path.join(run, 'fractal', '**', 'codex-run.log'), recursive=True):
        for text in open(f, errors='ignore').read().split('tokens used')[1:]:
            try: tok += int(text.strip().split()[0].replace(',', ''))
            except Exception: pass
out['tokens_M'] = round(tok / 1e6, 2)
if ts:
    t0 = datetime.datetime.fromisoformat(ts[0]); t1 = datetime.datetime.fromisoformat(ts[-1]); out['wall_min'] = int((t1 - t0).total_seconds() / 60)
line = json.dumps(out, ensure_ascii=False); print(line)
os.makedirs(os.path.join(run, 'trace'), exist_ok=True); open(os.path.join(run, 'trace', 'score.json'), 'w').write(line + '\n')
if os.environ.get('RCWM_SCORES'): open(os.environ['RCWM_SCORES'], 'a').write(line + '\n')
