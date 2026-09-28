"""Portable v2 delivery validation and atomic status/log utilities (no model calls)."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

VERSION = 2
OUTPUTS = {
    'final': 'outputs/final.png', 'comparison': 'outputs/comparison.png',
    'overlay': 'outputs/overlay.png',
    'compass': [f'outputs/compass/{angle:03d}.png' for angle in (0, 90, 180, 270)],
}
ID = re.compile(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\Z')

class InvalidDelivery(ValueError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, indent=2, ensure_ascii=False); f.write('\n')
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def append_event(path, event):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(event, separators=(',', ':'), ensure_ascii=False) + '\n')
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)

def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise InvalidDelivery(f'Cannot read JSON: {path}: {type(e).__name__}') from e

def node_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise InvalidDelivery('node ID must use letters, digits, underscores, hyphens and optional / segments')
    return value

def file_at(base, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise InvalidDelivery(f'Expected a node-relative path without ..: {relative!r}')
    path = base / relative
    if not path.resolve().is_relative_to(base.resolve()) or not path.is_file():
        raise InvalidDelivery(f'Missing file or escaping path: {relative}')
    return path

def location(part):
    part = Path(part).absolute()
    root = next((p for p in part.parent.parents if p.name == 'fractal'), None)
    if root is None:
        raise InvalidDelivery('part.json must be under <run>/fractal/<node-id>/')
    return root, part.parent.relative_to(root).as_posix()

def image_size(path):
    try:
        from PIL import Image
        with Image.open(path) as image:
            if image.format != 'PNG': raise ValueError('not PNG')
            size = image.size; image.verify()
        with Image.open(path) as image: image.load()
        return size
    except (OSError, ValueError, ImportError, SyntaxError) as e:
        raise InvalidDelivery(f'Invalid PNG or Pillow unavailable: {path.name}') from e

def validate(part, *, seals=False, seen=None, owner=None):
    """Validate the entire dependency tree. No repair or write side effects."""
    part = Path(part).absolute(); base = part.parent
    root, identity = location(part)
    if not base.resolve().is_relative_to(root.resolve()):
        raise InvalidDelivery('node path escapes fractal/')
    node_id(identity)
    seen = set() if seen is None else seen
    if identity in seen: raise InvalidDelivery(f'Cycle or multiply-owned child: {identity}')
    seen.add(identity)
    d = read_json(part)
    if not isinstance(d, dict): raise InvalidDelivery('part.json must be an object')
    required = {'schema_version','node_id','parent_id','module','export','children','account','outputs'}
    missing = required - d.keys()
    if missing:
        aliases = sorted(set(d) & {'entrypoint','component','entry','file','main'})
        raise InvalidDelivery(f'Missing required fields: {sorted(missing)}. Use module, not aliases {aliases}.')
    extras = set(d) - required - {'viewer','metadata'}
    if extras: raise InvalidDelivery(f'Unknown fields: {sorted(extras)}; put extra information under metadata')
    if type(d['schema_version']) is not int or d['schema_version'] != VERSION: raise InvalidDelivery('schema_version must be 2')
    if d['node_id'] != identity: raise InvalidDelivery(f'node_id must be {identity}')
    if identity == 'scene':
        if d['parent_id'] is not None: raise InvalidDelivery('scene parent_id must be null')
    else:
        node_id(d['parent_id'])
        if d['parent_id'] == identity: raise InvalidDelivery('node cannot be its own parent')
    if owner is not None and d['parent_id'] != owner:
        raise InvalidDelivery(f'{identity}: parent_id must be {owner}')
    module = file_at(base, d['module'])
    if module.suffix not in ('.js', '.mjs'): raise InvalidDelivery('module must name a .js or .mjs file')
    if not isinstance(d['export'], str) or not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*', d['export']):
        raise InvalidDelivery('export must be an explicit JavaScript export identifier')
    if d['account'] != 'account.md' or not file_at(base, 'account.md').read_text().strip():
        raise InvalidDelivery('account.md must exist and be nonempty')
    if d['outputs'] != OUTPUTS: raise InvalidDelivery('outputs must use the canonical paths from docs/output-contract.md')
    if identity == 'scene' and d.get('viewer') != 'index.html':
        raise InvalidDelivery('scene viewer must be index.html')
    if 'viewer' in d:
        if d['viewer'] != 'index.html': raise InvalidDelivery('viewer must be index.html')
        file_at(base, d['viewer'])
    if 'metadata' in d and not isinstance(d['metadata'], dict): raise InvalidDelivery('metadata must be an object')
    dimensions = image_size(file_at(base, 'target.png'))
    files = ['part.json', d['module'], 'account.md', 'target.png', 'view.json', 'brief.md', 'manifest.json']
    if 'viewer' in d: files.append(d['viewer'])
    sizes = {}
    for key in ('final','comparison','overlay'):
        rel = OUTPUTS[key]; size = image_size(file_at(base, rel)); sizes[rel] = list(size)
        expected = (dimensions[0]*2, dimensions[1]) if key == 'comparison' else dimensions
        if size != expected: raise InvalidDelivery(f'{rel}: expected {expected}, got {size}')
        files.append(rel)
    compass_size = None
    for rel in OUTPUTS['compass']:
        size = image_size(file_at(base, rel)); sizes[rel] = list(size)
        if compass_size and size != compass_size: raise InvalidDelivery('compass views must have equal dimensions')
        compass_size = size; files.append(rel)
    camera = root.parent / 'camera-contract.json'
    if not isinstance(read_json(camera), dict): raise InvalidDelivery('camera-contract.json must be an object')
    if not isinstance(read_json(file_at(base, 'view.json')), dict): raise InvalidDelivery('view.json must be an object')
    provenance = read_json(file_at(base, 'manifest.json'))
    if not isinstance(provenance, dict): raise InvalidDelivery('manifest.json must be an object')
    if 'parent_id' in provenance and provenance['parent_id'] != d['parent_id']:
        raise InvalidDelivery('parent_id disagrees with runner-owned manifest.json')
    # Hash implementation files too, so editing a delivered child/helper invalidates the seal.
    for folder in (base, base/'src'):
        candidates = folder.glob('*') if folder == base else folder.rglob('*')
        for path in candidates:
            if path.is_file() and (folder != base or path.suffix in ('.js','.mjs','.cjs','.html','.css') or (path.suffix=='.json' and path.name not in ('children.json','result.json'))):
                rel = path.relative_to(base).as_posix(); file_at(base, rel); files.append(rel)
    hashes = {rel: sha(file_at(base, rel)) for rel in sorted(set(files))}
    kids = d['children']
    if not isinstance(kids, list) or any(not isinstance(k, str) for k in kids) or len(kids) != len(set(kids)):
        raise InvalidDelivery('children must be unique run-scoped node IDs')
    child_hashes = {}
    for kid in kids:
        node_id(kid)
        child = root/kid/'part.json'
        validate(child, seals=seals, seen=seen, owner=identity)
        child_hashes[kid] = sha(child)
    report = dict(schema_version=VERSION, node_id=identity, valid=True,
                  scope='packaging-and-dependency-integrity', checked_at=now(),
                  hashes=hashes, camera_sha256=sha(camera), children=child_hashes, dimensions=sizes)
    if seals:
        old = read_json(base/'outputs/validation.json')
        if not isinstance(old, dict): raise InvalidDelivery('validation.json must be an object')
        if old.get('valid') is not True or any(old.get(k) != report[k] for k in ('hashes','camera_sha256','children')):
            raise InvalidDelivery(f'{identity}: stale or missing validation seal; validate the current delivery again')
        result = read_json(base/'result.json')
        if not isinstance(result, dict): raise InvalidDelivery('result.json must be an object')
        if result.get('status') != 'completed' or result.get('delivery_sha256') != sha(part):
            raise InvalidDelivery(f'{identity}: runner has not accepted this delivery')
    return report

def check_run(run):
    run = Path(run)
    result = read_json(run/'result.json')
    if not isinstance(result, dict): raise InvalidDelivery('result.json must be an object')
    expected = 'fractal/scene/outputs/final.png'
    if result.get('schema_version') != VERSION or result.get('status') != 'completed' or result.get('final') != expected:
        raise InvalidDelivery('run is not completed under output contract v2')
    validate(run/'fractal/scene/part.json', seals=True)
    return run/expected

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('path', type=Path); p.add_argument('--run', action='store_true')
    args = p.parse_args()
    try:
        if args.run: print(check_run(args.path))
        else: print(json.dumps(validate(args.path), indent=2))
    except (InvalidDelivery, OSError) as e:
        p.exit(1, f'invalid_delivery: {e}\n')

if __name__ == '__main__': main()
