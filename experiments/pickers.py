"""Shared final-render selection rules for all methods (figures and tables). Return (path or None, whether the method reached its own stopping state)."""
import glob, os, re, sys, json
from pathlib import Path
from PIL import Image
EXCL=('reference','mask','target','attribution','comparison','compare','sheet','pair','grid','audit','zone','inventory','contact',
      'overlay','native','rear','east','west','north','south','orbit','zoom','detail','calibration','check','review','replay',
      'alpha','occupancy','inspection','exploded','grazing','neutral','overhead')
VIGA=os.environ.get('RCWM_VIGA','')
SEIG=os.environ.get('RCWM_SEIG','')
def _img_ok(f):
    try:
        if os.path.getsize(f)<1000: return False
        Image.open(f).verify(); return True
    except Exception: return False
def _ok(f):
    b=os.path.basename(f).lower()
    if not _img_ok(f) or any(e in b for e in EXCL): return False
    if any(e in f.lower() for e in ('audit','inventory','evidence','material','mask')): return False  # Texture/evidence/audit directories are not final outputs.
    try: w,h=Image.open(f).size
    except Exception: return False
    return w>=400 and h>=300
def newest(pats, prefer=()):
    fs=[]
    for p in pats: fs+=glob.glob(p, recursive=True)
    fs=[f for f in fs if _ok(f)]
    if not fs: return None
    for key in prefer:
        c=[f for f in fs if key in os.path.basename(f).lower()]
        if c: return max(c,key=os.path.getmtime)
    return max(fs,key=os.path.getmtime)
# which run of ours to report per scene, e.g. RCWM_OURS_RUN='snow-village=r2,city-full=r1'; default r1 for every scene
OURS_RUN=dict(kv.split('=') for kv in os.environ.get('RCWM_OURS_RUN','').split(',') if '=' in kv)
OURS_CHAIN=os.environ.get('RCWM_OURS_CHAIN','')  # e.g. 'runs/v2-{scene}-recursive' for a batch launched with rcwm.sh; default = paper layout
def ours_chain(root,SC):
    if OURS_CHAIN:
        c=OURS_CHAIN.format(scene=SC); return c if c.startswith('/') else f'{root}/{c}'  # absolute patterns allow one runtime root per scene
    return f'{root}/runs/pilot/{SC}-recursive-{OURS_RUN.get(SC,"r1")}'
def ours(root,SC):
    d=f'{ours_chain(root,SC)}/fractal/scene'
    chain=ours_chain(root,SC)
    try:
        part=json.loads(Path(f'{d}/part.json').read_text()) if os.path.isfile(f'{d}/part.json') else {}
        conditions=json.loads(Path(f'{chain}/conditions.json').read_text()) if os.path.isfile(f'{chain}/conditions.json') else {}
        strict=os.path.isfile(f'{chain}/result.json') or (isinstance(part,dict) and 'schema_version' in part) or conditions.get('output_contract_version')==2
        if strict:
            sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runner'))
            from delivery import check_run
            return str(check_run(chain)),True
    except (ValueError,OSError,TypeError):
        return None,False

    for n in ['final.png','FINAL.png']:
        if os.path.isfile(f'{d}/{n}') and _img_ok(f'{d}/{n}'): return f'{d}/{n}',True
    delivered=os.path.isfile(f'{d}/part.json')
    if delivered:
        # Delivered but not named final.png: trust the final render declared in part.json first, then the latest full frame matching the reference dimensions whose name is not a comparison/side-view/audit.
        try: j=json.load(open(f'{d}/part.json'))
        except Exception: j={}
        ev=j.get('evidence') if isinstance(j.get('evidence'),dict) else {}
        for k in ('final_render','reference_view','render','main_render','final','front'):   # ledgers name the locked reference camera differently
            v=ev.get(k) or j.get(k)
            if isinstance(v,str) and os.path.isfile(f'{d}/{v}') and _img_ok(f'{d}/{v}'): return f'{d}/{v}',True
        # Also recognize common agent names for fixed-camera final renders (exact matches only; guessing may select orbit/directional views). Otherwise mark unfinished until visual review.
        for n in ('render-final.png','final-main.png','preview-final.png','final-render.png','final-fixed.png','render-fixed.png','main-final.png','final-view.png','final-front.png','renders/final-front.png','renders/final.png','evidence/final.png','review/final.png','render/final.png','final-reference.png'):
            if os.path.isfile(f'{d}/{n}') and _img_ok(f'{d}/{n}'): return f'{d}/{n}',True
        print(f'[pickers.ours] {SC}: delivered but no recognised final render name in {d} — check by eye',file=sys.stderr)
    # Unfinished: use the latest overall render (round/assembled/handoff), excluding side views/comparisons.
    return newest([f'{d}/round*[0-9].png',f'{d}/assembled*[0-9].png',f'{d}/handoff.png',f'{d}/blockout*.png']),False
def seig(root,SC):
    run=os.environ.get('RCWM_SEIG_RUN','runs/pilot-{scene}').format(scene=SC); base=run if run.startswith('/') else f'{SEIG}/{run}'
    p=f'{base}/renders/commit_camera.png'
    if os.path.isfile(p) and _img_ok(p): return p,True
    return (newest([f'{base}/renders/commit_*.png']) or None),False
def _viga_best(base):
    if not os.path.isdir(base): return None,-1
    for r in sorted((int(x) for x in os.listdir(base) if x.isdigit()),reverse=True):
        # VIGA saves images by the Blender camera name: usually Camera.png, or another *.png if the agent renamed it.
        cands=[f for f in glob.glob(f'{base}/{r}/*.png') if _img_ok(f)]
        if not cands: continue
        cands.sort(key=lambda f:(os.path.basename(f)!='Camera.png', -os.path.getsize(f)))
        return cands[0],r
    return None,-1
def viga(root,SC):
    # Official run: pilot2-<SC> (this scene only, high); stopped means the official runner finished normally.
    tid=os.environ.get('RCWM_VIGA_TESTID','pilot2-{scene}').format(scene=SC)
    p,r2=_viga_best(f'{VIGA}/output/static_scene/{tid}/{SC}/renders')
    log=f'{VIGA}/runs/{tid}.log'; txt=open(log,errors='ignore').read() if os.path.isfile(log) else ''
    fin=bool(p) and 'Cleanup finished' in txt and 'Failed to get model response' not in txt
    # Fallback: highest round for this scene from older multi-scene launches (prefer the same launch name), enabled only for the default pilot2 batch.
    # Batches with an explicit RCWM_VIGA_TESTID (e.g. v2-{scene}) must use only their own outputs, without falling back to other launches.
    cands=[]
    for L in (glob.glob(f'{VIGA}/output/static_scene/*/{SC}/renders') if 'RCWM_VIGA_TESTID' not in os.environ else []):
        launch=L.split(os.sep)[-3]
        if launch.startswith('pilot2-'): continue
        q,r=_viga_best(L)
        if q: cands.append((launch==SC, r, q))
    old=max(cands) if cands else None
    # Use the official run when finished; otherwise replace the old result only if its round is at least as high and at least 5, avoiding replacement with a first-round draft.
    if p and (fin or r2>=max(5, old[1] if old else 0)): return p,fin
    if old: return old[2],False
    return (p,False) if p else (None,False)
ISO=os.environ.get('RCWM_I2T_ISO','')
def i2t(root,SC):
    # User decision (2026-09-09): accept only city-full r1 completed by the native workflow; use isolated-workspace reruns for the other nine scenes (two stages: native flow, then required completion after a quality-gate stop).
    if SC=='city-full' and os.environ.get('RCWM_I2T_ISO_ALL','0')!='1':  # paper batch: city-full is img2threejs's own native completion
        p=f'{root}/runs/pilot/city-full-img2threejs-r1/render-hires.png'
        return (p,True) if _img_ok(p) else (None,False)
    d=f'{ISO}/{SC}'
    done=os.path.isfile(f'{d}/stages.log') and 'ALL_DONE' in open(f'{d}/stages.log').read()
    for n in ('final-render.png','render-hires.png'):
        c=[f for f in glob.glob(f'{d}/**/{n}', recursive=True) if _img_ok(f) and 'img2threejs/' not in f.replace(d+'/','')]  # Final outputs under its own names, regardless of dimensions.
        if c: return max(c,key=os.path.getmtime),done
    return None,False
