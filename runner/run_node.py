#!/usr/bin/env python3
"""Recursive node execution with v2 results, per-session logs and failure propagation."""
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid
from delivery import (VERSION, InvalidDelivery, append_event, atomic_json, check_run,
                      file_at, node_id, now, read_json, sha, validate)

CODE = Path(__file__).resolve().parents[1]

class StopRun(Exception):
    def __init__(self, status, message, exit_code=1):
        self.status, self.message, self.exit_code = status, message, exit_code

class Runner:
    def __init__(self, chain, node, parent, depth, run_id):
        self.workspace = Path(os.environ.get('RCWM_ROOT', CODE/'runtime')).resolve()
        self.run = (self.workspace/chain).resolve()
        if not self.run.is_relative_to(self.workspace): raise ValueError('chain escapes workspace')
        self.node = node_id(node); self.parent = None if parent == '-' else node_id(parent)
        if (node == 'scene') != (self.parent is None): raise ValueError('only scene may be root')
        self.depth = int(depth); self.run_id = run_id; self.cycle = 1
        self.nd = self.run/'fractal'/self.node
        if not self.nd.resolve().is_relative_to((self.run/'fractal').resolve()): raise ValueError('node escapes fractal')
        self.logs = self.nd/'logs'; (self.logs/'sessions').mkdir(parents=True, exist_ok=True)
        self.max_depth = int(os.environ.get('RCWM_MAXD','4')); self.max_cycles = int(os.environ.get('RCWM_MAXCYC','3'))
        self.repairs = int(os.environ.get('RCWM_PACKAGING_REPAIRS','1'))
        if self.max_depth < 0 or self.max_cycles < 1 or not 0 <= self.repairs <= 3: raise ValueError('invalid runtime limits')
        self.prompt = Path(os.environ.get('RCWM_PROMPT', CODE/'solver/solver-template.md'))
        self.contract = CODE/'docs/output-contract.md'
        self.invocation = uuid.uuid4().hex
        self.started = now(); self.processes = []; self.signum = 0; self.state = {}
        self.lock = (self.logs/'.runner.lock').open('a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        provenance=self.nd/'manifest.json'
        if provenance.exists():
            owner=read_json(provenance)
            if 'parent_id' in owner and owner['parent_id'] != self.parent:
                self.lock.close()
                raise ValueError('node already owned by another parent')
        self.model = os.environ.get('RCWM_MODEL','gpt-6-astra')
        self.effort = os.environ.get('RCWM_REASONING','high')

    def event(self, kind, **extra):
        camera = self.run/'camera-contract.json'
        item = dict(schema_version=VERSION,run_id=self.run_id,node_id=self.node,
                    parent_id=self.parent or '-',depth=self.depth,cycle=self.cycle,event=kind,
                    ts=now(),invocation_id=self.invocation,solver_hash=sha(self.prompt)[:12],
                    contract_hash=sha(self.contract)[:12],camera_hash=sha(camera)[:12] if camera.exists() else 'none',
                    parent_snapshot='none',**extra)
        append_event(self.logs/'events.jsonl', item)
        append_event(self.run/'trace/events.jsonl', item)

    def status(self, status, **extra):
        self.state.update(schema_version=VERSION,node_id=self.node,parent_id=self.parent,
                          run_id=self.run_id,status=status,cycle=self.cycle,updated_at=now(),pid=os.getpid(),
                          invocation_id=self.invocation,**extra)
        if status != 'completed': self.state.pop('delivery_sha256',None)
        atomic_json(self.nd/'result.json', self.state)
        if self.node == 'scene':
            result = dict(self.state,part='fractal/scene/part.json',
                          final='fractal/scene/outputs/final.png' if status=='completed' else None,
                          viewer='fractal/scene/index.html',events='trace/events.jsonl',
                          log='logs/runner.log',node_log='fractal/scene/logs/codex.log')
            atomic_json(self.run/'result.json', result)

    def message(self, message):
        path=self.run/'logs/runner.log'; path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a') as f:
            fcntl.flock(f,fcntl.LOCK_EX); f.write(f'{now()} [{self.node}] {message}\n'); f.flush()
        print(f'[{self.node}] {message}',flush=True)

    def signal(self, signum, frame):
        self.signum = signum
        raise StopRun('interrupted', f'interrupted by signal {signum}', 128+signum)

    def cleanup(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
        deadline=time.monotonic()+10
        for proc in self.processes:
            if proc.poll() is None:
                try: proc.wait(timeout=max(.1,deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    try: os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait()

    def task(self):
        text=self.prompt.read_text().replace('__NODE__',self.node).replace('__CHAIN__',str(self.run.relative_to(self.workspace))).replace('__DEPTH__',str(self.depth))
        text += '\n\n# Required delivery and log contract (v2)\n' + self.contract.read_text()
        text += f'\nYour node_id is {self.node}; parent_id is {json.dumps(self.parent)}.\n'
        text += f'Publisher: {CODE}/tools/publish_delivery.py. Use the runtime Python with Pillow.\n'
        if self.depth >= self.max_depth or self.cycle >= self.max_cycles:
            text += '\nNo child requests are permitted in this session: depth or integration-cycle budget is exhausted. Finish locally.\n'
        (self.nd/'task.md').write_text(text)
        return text

    def session(self, purpose='modeling', repair_error=None):
        task=self.task()
        number=max([int(p.stem.split('-')[-1]) for p in (self.logs/'sessions').glob('session-*.log')] or [0])+1
        relative=f'logs/sessions/session-{number:04d}.log'; path=self.nd/relative
        args=['codex','exec','--skip-git-repo-check','--cd',str(self.workspace),'--sandbox','workspace-write',
              '-c',f'model="{self.model}"','-c',f'model_reasoning_effort="{self.effort}"',
              '-c','sandbox_workspace_write.network_access=true',
              '-c','sandbox_workspace_write.writable_roots='+json.dumps([os.environ.get('PLAYWRIGHT_BROWSERS_PATH',str(Path.home()/'.cache/ms-playwright'))])]
        sid=self.nd/'.sid'
        if purpose=='packaging':
            task += '\nPACKAGING-ONLY REPAIR: '+repair_error+'\nCorrect manifest fields/paths and publish already-rendered images. Do not change JS/source, do not launch new children, and do not remodel.\n'
        elif sid.exists() and sid.read_text().strip():
            task += '\nContinue this level. Validated children: '+', '.join(self.state.get('validated_children',[]))+'. Integrate and review the whole again.\n'
        if sid.exists() and sid.read_text().strip(): args += ['resume',sid.read_text().strip(),task]
        else: args += [task]
        env=dict(os.environ,RCWM_NODE_DIR=str(self.nd),RCWM_NODE_ID=self.node,RCWM_PARENT_ID=self.parent or '-')
        self.event('session_start',session=number,purpose=purpose,model=self.model,reasoning=self.effort,log=relative)
        start=time.monotonic(); exit_code=None
        try:
            with path.open('wb') as log:
                proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,cwd=self.workspace,env=env,start_new_session=True)
                self.processes.append(proc)
                try: exit_code=proc.wait()
                except StopRun:
                    os.killpg(proc.pid,self.signum or signal.SIGTERM)
                    try: proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                    exit_code=proc.returncode
                    raise
        finally:
            content=path.read_text(errors='replace') if path.exists() else ''
            with (self.logs/'codex.log').open('a') as combined:
                combined.write(f'\n=== session {number:04d} purpose={purpose} ===\n'+content)
            match=re.search(r'session id:\s*([\w-]+)',content)
            if match: sid.write_text(match.group(1)+'\n')
            matches=re.findall(r'tokens used\s*\n?\s*([\d,]+)',content)
            usage=int(matches[-1].replace(',','')) if matches else None
            warnings=sum('Reconnecting...' in l or 'Falling back from WebSockets' in l for l in content.splitlines())
            self.event('session_end',session=number,purpose=purpose,exit_code=exit_code,
                       elapsed_seconds=round(time.monotonic()-start,3),usage_total=usage,
                       transport_warning_lines=warnings,log=relative)
        if exit_code != 0: raise StopRun('executor_failed',f'Codex exited {exit_code}; see {relative}')

    def requests(self):
        path=self.nd/'children.json'
        kids=read_json(path) if path.exists() else []
        if not isinstance(kids,list) or any(not isinstance(k,str) for k in kids) or len(set(kids))!=len(kids):
            raise InvalidDelivery('children.json must contain unique node IDs')
        for k in kids:
            node_id(k)
            if k in (self.node,self.parent,'scene'): raise InvalidDelivery('child request points to self/ancestor/root')
            # Walk recorded ownership to reject longer cycles before launching.
            ancestor=self.parent
            while ancestor:
                if k==ancestor: raise InvalidDelivery('child request creates a cycle')
                m=self.run/'fractal'/ancestor/'manifest.json'
                ancestor=read_json(m).get('parent_id') if m.exists() else None
        return kids

    def children(self, kids, recovering=False):
        if self.depth >= self.max_depth or self.cycle >= self.max_cycles:
            raise StopRun('budget_exhausted','child request leaves no depth or whole-again cycle')
        self.status('waiting_children',requested_children=kids)
        pending=[]; validated=[]
        for kid in kids:
            if recovering:
                try:
                    validate(self.run/'fractal'/kid/'part.json',seals=True,owner=self.node)
                    validated.append(kid);continue
                except (InvalidDelivery,OSError): pass
            self.event('child_call',child=kid)
            command=[sys.executable,str(CODE/'runner/run_node.py'),str(self.run.relative_to(self.workspace)),kid,self.node,str(self.depth+1),self.run_id]
            proc=subprocess.Popen(command,cwd=self.workspace,start_new_session=True)
            self.processes.append(proc);pending.append((kid,proc))
        failed=[]
        for kid,proc in pending:
            code=proc.wait(); good=code==0
            if good:
                try: validate(self.run/'fractal'/kid/'part.json',seals=True,owner=self.node)
                except (InvalidDelivery,OSError): good=False
            self.event('child_return',child=kid,delivered=good,exit_code=code)
            (validated if good else failed).append(kid)
        self.state['validated_children']=sorted(set(self.state.get('validated_children',[])+validated))
        if failed: raise StopRun('child_failed','invalid or failed children: '+', '.join(failed))
        self.state['requested_children']=[]
        self.cycle+=1;self.status('running')

    def accept(self):
        report=validate(self.nd/'part.json',owner=self.parent)
        kids=read_json(self.nd/'part.json')['children']
        if set(kids)!=set(self.state.get('validated_children',[])):
            raise InvalidDelivery('part.json children must equal the validated children requested by this node')
        for kid in kids: validate(self.run/'fractal'/kid/'part.json',seals=True,owner=self.node)
        if self.requests(): raise InvalidDelivery('clear pending children.json before delivery')
        atomic_json(self.nd/'outputs/validation.json',report)
        return report

    def execute(self):
        previous=self.nd/'result.json'
        if previous.exists(): self.state=read_json(previous)
        self.cycle=max(1,int(self.state.get('cycle',1)))
        prior_requests=self.state.get('requested_children',[])
        provenance=self.nd/'manifest.json'
        if provenance.exists():
            old=read_json(provenance)
            if 'parent_id' in old and old['parent_id'] != self.parent:
                raise StopRun('invalid_delivery','node already owned by another parent')
        else:
            atomic_json(provenance,dict(interface_version=1,node_id=self.node,parent_id=self.parent,
                                       reference_sha256=sha(file_at(self.nd,'target.png')),
                                       solver_hash=sha(self.prompt),output_contract_version=VERSION))
        self.status('running',exit_code=None,error=None)
        self.message('started')
        if prior_requests:
            self.event('recover_children',children=prior_requests)
            self.children(prior_requests,recovering=True)
        while self.cycle <= self.max_cycles:
            pending=self.nd/'children.json'
            if pending.exists(): os.replace(pending,self.nd/'children.json.prev')
            self.session()
            kids=self.requests()
            if kids:
                self.children(kids); continue
            error=None
            for attempt in range(self.repairs+1):
                try:
                    self.accept();error=None;break
                except (InvalidDelivery,OSError) as e:
                    error=str(e);self.event('validation_failed',error=error,repair_attempt=attempt)
                    atomic_json(self.nd/'outputs/validation.json',dict(schema_version=VERSION,valid=False,error=error,checked_at=now()))
                    if attempt==self.repairs: break
                    before=self.source_hashes()
                    self.session('packaging',error)
                    if self.source_hashes()!=before:
                        error='packaging-only repair changed implementation files';break
            if error: raise StopRun('invalid_delivery',error)
            self.status('completed',exit_code=0,error=None,delivery_sha256=sha(self.nd/'part.json'))
            self.event('stop',stop_reason='completed',status='completed',exit_code=0)
            self.message('completed: outputs/final.png');return 0
        raise StopRun('budget_exhausted','no whole-again cycle remains')

    def source_hashes(self):
        result={}
        for folder in (self.nd,self.nd/'src'):
            for p in (folder.glob('*') if folder==self.nd else folder.rglob('*')):
                if p.is_file() and (folder != self.nd or p.suffix in ('.js','.mjs','.cjs','.html','.css') or (p.suffix=='.json' and p.name not in ('part.json','children.json','manifest.json','view.json','result.json'))):
                    result[str(p.relative_to(self.nd))]=sha(p)
        return result

    def run_node(self):
        for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,self.signal)
        try: return self.execute()
        except (StopRun,InvalidDelivery,OSError,ValueError) as error:
            status=error.status if isinstance(error,StopRun) else 'invalid_delivery'
            code=error.exit_code if isinstance(error,StopRun) else 1
            self.status(status,exit_code=code,error=str(error.message if isinstance(error,StopRun) else error))
            self.event('stop',stop_reason=status,status=status,exit_code=code)
            self.message(f'{status}: {self.state["error"]}')
            return code
        finally:
            # Further signals must not interrupt child cleanup/status finalization.
            signal.signal(signal.SIGINT,signal.SIG_IGN);signal.signal(signal.SIGTERM,signal.SIG_IGN)
            self.cleanup();self.lock.close()

if __name__ == '__main__':
    try:
        args=sys.argv[1:]
        if not 2 <= len(args) <= 5: raise ValueError('usage: run_node.py <chain> <node> [parent=-] [depth=0] [run_id=r0]')
        args += ['-','0','r0'][len(args)-2:]
        sys.exit(Runner(*args).run_node())
    except (ValueError,OSError,TypeError) as error: sys.exit(f'runner startup failed: {error}')
