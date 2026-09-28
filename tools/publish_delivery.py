#!/usr/bin/env python3
"""Publish canonical node artifacts from explicitly selected images; no render guessing."""
import argparse
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runner'))
from delivery import OUTPUTS, atomic_json, file_at, image_size, location, node_id, validate

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('node', type=Path)
    p.add_argument('--module', required=True); p.add_argument('--export', required=True)
    p.add_argument('--parent', required=True, help='parent node ID; - for scene')
    p.add_argument('--children', nargs='*', default=[])
    p.add_argument('--final', required=True, help='node-relative PNG at exactly target dimensions')
    p.add_argument('--compass', nargs=4, required=True, metavar=('A000','A090','A180','A270'))
    p.add_argument('--viewer', help='index.html for scene')
    a = p.parse_args(); base = a.node.resolve(); root, identity = location(base/'part.json')
    node_id(identity)
    from PIL import Image
    target = file_at(base, 'target.png'); final = file_at(base, a.final)
    if image_size(final) != image_size(target): p.error('final must match target dimensions; no implicit resizing')
    views = [file_at(base, rel) for rel in a.compass]
    sizes = [image_size(path) for path in views]
    if len(set(sizes)) != 1: p.error('compass images must have matching dimensions')
    file_at(base, a.module); file_at(base, 'account.md')
    out = base/'outputs'
    for destination in [out, out/'compass', base/'part.json', *[base/r for r in [OUTPUTS['final'],OUTPUTS['comparison'],OUTPUTS['overlay'],*OUTPUTS['compass']]]]:
        if not destination.resolve().is_relative_to(base): p.error('output path escapes node through a symlink')
    (out/'compass').mkdir(parents=True, exist_ok=True)
    for source, relative in [(final, OUTPUTS['final']), *zip(views, OUTPUTS['compass'])]:
        destination = base/relative
        if source.resolve() != destination.resolve(): shutil.copyfile(source, destination)
    with Image.open(target) as image: left = image.convert('RGB')
    with Image.open(out/'final.png') as image: right = image.convert('RGB')
    pair = Image.new('RGB', (left.width*2, left.height)); pair.paste(left); pair.paste(right, (left.width,0))
    pair.save(out/'comparison.png'); Image.blend(left,right,0.5).save(out/'overlay.png')
    manifest = dict(schema_version=2,node_id=identity,parent_id=None if a.parent=='-' else a.parent,
                    module=a.module,export=a.export,children=a.children,account='account.md',outputs=OUTPUTS)
    if a.viewer or identity=='scene': manifest['viewer'] = a.viewer or 'index.html'
    atomic_json(base/'part.json', manifest)
    validate(base/'part.json')
    print(f'Published v2 delivery candidate: {base / "part.json"}. Runner acceptance is still required.')

if __name__ == '__main__':
    try: main()
    except (ValueError,OSError) as error: sys.exit(f'publish failed: {error}')
