#!/usr/bin/env python3
"""Runner-level delivery check: facts only, no judgment.  check_part.py <path/to/part.json>

A part.json is accepted in either shape the solver produces:
  (a) a components list (non-empty, unique ids), or
  (b) a module delivery: a file the parent composes, named by "module" (or "entry" / "main" / "file"), with an
      optional "export" symbol.
Child references, if present, must point at existing part.json files. A child may be given as
  - a node id, flat ("cottages") or nested ("east-village/cottages"), resolved against the run's fractal/ root,
    the node's own directory and its parent's directory, or
  - a relative path to the child's part.json, or an object carrying "part"/"path" (a path) or "id"/"name" (a node id).
Prints "ok …" and exits 0, or a one-word reason and exits 1."""
import json, sys, os
from pathlib import Path
p = Path(sys.argv[1]).resolve(); here = p.parent
try:
    d = json.loads(p.read_text())
except Exception as e:
    print(f"invalid_json: {e}"); sys.exit(1)
if isinstance(d, list): d = {'components': d}
if not isinstance(d, dict):
    print("invalid_shape"); sys.exit(1)

# the run's fractal/ root: nearest ancestor named "fractal" (node directories may be nested when ids contain "/")
root = next((a for a in here.parents if a.name == 'fractal'), here.parent)

comps = d.get('components')
mod = next((d[k] for k in ('module', 'entry', 'main', 'file') if isinstance(d.get(k), str) and d[k]), None)
exp = d.get('export') if isinstance(d.get('export'), str) and d.get('export') else None
if isinstance(comps, list) and comps:
    ids = [c.get('id') for c in comps if isinstance(c, dict)]
    if len(ids) != len(set(ids)):
        print("duplicate_ids"); sys.exit(1)
    shape = f"components={len(comps)}"
elif mod:
    if not (here / mod).exists():
        print(f"module_missing: {mod}"); sys.exit(1)
    shape = f"module={mod}:{exp or '?'}"
else:
    print("empty_components"); sys.exit(1)

def _paths_for(c):
    """Candidate part.json locations for one child reference."""
    if isinstance(c, dict):
        rel = next((c[k] for k in ('part', 'path') if isinstance(c.get(k), str)), None)
        if rel: return [here / rel]
        c = next((c[k] for k in ('id', 'name', 'node') if isinstance(c.get(k), str)), None)
    if not isinstance(c, str) or not c: return []
    if c.endswith('.json') or c.startswith('.'):   # a relative path
        return [here / c]
    ids = [c, os.path.basename(c.rstrip('/'))]     # full id, and its last segment (a parent may name a nested child by its full id)
    out = []
    for i in ids:
        for base in (root, here, here.parent):
            out += [base / i / 'part.json', base / i]
    return out

def _child_ok(c):
    return any(q.exists() and (q.is_file() or (q / 'part.json').exists()) for q in _paths_for(c))

kids = d.get('children') or []
if not isinstance(kids, list):
    print("invalid_children"); sys.exit(1)
missing = [c for c in kids if not _child_ok(c)]
if missing:
    m = missing[0]; m = m.get('part') or m.get('path') or m.get('id') or m.get('name') if isinstance(m, dict) else m
    print(f"child_missing: {m}"); sys.exit(1)
print(f"ok {shape} children={len(kids)}")
