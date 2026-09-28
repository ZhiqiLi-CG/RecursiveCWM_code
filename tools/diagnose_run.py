#!/usr/bin/env python3
"""Read public result/status files, recursion trace and raw log locations."""
import json
from pathlib import Path
import subprocess
import sys
CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE/'runner'))
from delivery import check_run, InvalidDelivery
run=Path(sys.argv[1]).resolve()
if not (run/'fractal').is_dir():sys.exit('not a run directory')
print('Run:',run)
if (run/'result.json').exists():
    result=json.loads((run/'result.json').read_text())
    print('Recorded status:',result.get('status'),'exit:',result.get('exit_code'))
    try:print('Validated final:',check_run(run))
    except (InvalidDelivery,OSError) as error:print('Not a validated complete delivery:',error)
else:print('Legacy run: no v2 result.json; file presence alone does not prove completion.')
if (run/'trace/events.jsonl').exists():
    subprocess.run([sys.executable,str(CODE/'runner/trace_report.py'),str(run)],check=False)
for task in sorted((run/'fractal').rglob('task.md')):
    node=task.parent;state=node/'result.json';log=node/'logs/codex.log'
    if not log.exists():log=node/'codex-run.log'
    print('\nNode:',node.relative_to(run/'fractal'))
    if state.exists():
        d=json.loads(state.read_text());print(' status:',d.get('status'),'error:',d.get('error'))
    print(' log:',log)
    if (node/'outputs/validation.json').exists():print(' validation:',node/'outputs/validation.json')
