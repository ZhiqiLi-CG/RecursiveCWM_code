import json
import os
from pathlib import Path
import subprocess
import sys
from PIL import Image

if '--version' in sys.argv:
    print('codex-cli 0.154.0'); sys.exit(0)
assert 'model="gpt-6-astra"' in sys.argv and 'model_reasoning_effort="high"' in sys.argv
nd=Path(os.environ['RCWM_NODE_DIR']);node=os.environ['RCWM_NODE_ID'];parent=os.environ['RCWM_PARENT_ID']
mode=os.environ.get('RCWM_TEST_MODE','success')
if mode=='wait':
    import time
    (nd/'work').mkdir(exist_ok=True)
    (nd/'work/waiting').touch()
    time.sleep(60)
print('session id: 00000000-0000-4000-8000-'+ ('000000000001' if node=='scene' else ('000000000002' if node=='house-a' else '000000000003')),flush=True)
run=next(p.parent for p in nd.parents if p.name=='fractal')
if not (run/'camera-contract.json').exists(): (run/'camera-contract.json').write_text('{"type":"test-camera"}')
if mode=='executor_failure' and node=='house-a':
    (nd/'part.json').write_text('{"status":"complete"}')
    print('simulated executor failure',flush=True);sys.exit(7)
if node=='scene' and not (nd/'work/requested').exists():
    (nd/'work').mkdir(exist_ok=True);(nd/'work/requested').touch()
    for kid in ['house-a','house-b']:
        child=nd.parent/kid;child.mkdir(exist_ok=True)
        (child/'target.png').write_bytes((nd/'target.png').read_bytes())
        (child/'view.json').write_text('{}');(child/'brief.md').write_text('test child')
    (nd/'children.json').write_text('["house-a","house-b"]')
else:
    kids=['house-a','house-b'] if node=='scene' else []
    (nd/'children.json').write_text('[]')
    module=nd/'component.js'
    if not module.exists(): module.write_text('export function build() { return {}; }\n')
    (nd/'account.md').write_text('Fixture: four views inspected; local work complete.\n')
    if node=='scene': (nd/'index.html').write_text('<html>fixture</html>')
    (nd/'work').mkdir(exist_ok=True)
    with Image.open(nd/'target.png') as image: size=image.size
    for name in ['draft','000','090','180','270']:
        Image.new('RGB',size,(70,90,110)).save(nd/'work'/f'{name}.png')
    cmd=[sys.executable,str(Path(os.environ['RCWM_CODE'])/'tools/publish_delivery.py'),str(nd),
         '--module','component.js','--export','build','--parent',parent,'--children',*kids,
         '--final','work/draft.png','--compass',*[f'work/{a}.png' for a in ['000','090','180','270']]]
    subprocess.run(cmd,check=True)
    repair='PACKAGING-ONLY REPAIR:' in sys.argv[-1]
    if (mode=='invalid_manifest' or (mode=='repair_manifest' and not repair)) and node=='house-a':
        p=nd/'part.json';d=json.loads(p.read_text());d['entrypoint']=d.pop('module');p.write_text(json.dumps(d))
    if mode=='bad_image' and node=='house-a': (nd/'outputs/final.png').write_bytes(b'not a PNG')
print('tokens used\n1,234')
