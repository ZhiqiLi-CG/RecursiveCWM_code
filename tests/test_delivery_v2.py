"""Offline contract/regression tests; all model calls are fake and all data temporary."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import signal
import unittest
from PIL import Image

CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE/'runner'))
from delivery import OUTPUTS, InvalidDelivery, atomic_json, check_run, validate

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)

    def node(self,n='scene',parent=None,children=()):
        run=self.base/'run';nd=run/'fractal'/n;(nd/'outputs/compass').mkdir(parents=True)
        (run/'camera-contract.json').write_text('{}')
        for f in ['view.json','manifest.json']:(nd/f).write_text('{}')
        (nd/'brief.md').write_text('brief');(nd/'account.md').write_text('account')
        (nd/'component.js').write_text('export function build(){}')
        (nd/'index.html').write_text('<html></html>')
        for f in ['target.png',OUTPUTS['final'],OUTPUTS['overlay'],*OUTPUTS['compass']]:Image.new('RGB',(32,24)).save(nd/f)
        Image.new('RGB',(64,24)).save(nd/OUTPUTS['comparison'])
        d=dict(schema_version=2,node_id=n,parent_id=parent,module='component.js',export='build',children=list(children),account='account.md',outputs=OUTPUTS)
        if n=='scene':d['viewer']='index.html'
        atomic_json(nd/'part.json',d)
        return nd

    def test_module_alias_regression_city3_and_park2(self):
        nd=self.node()
        for alias in ('entrypoint','component'):
            d=json.loads((nd/'part.json').read_text());d.pop('entrypoint',None);d.pop('component',None);d[alias]=d.pop('module','component.js');atomic_json(nd/'part.json',d)
            with self.assertRaisesRegex(InvalidDelivery,'Missing required fields.*module'):validate(nd/'part.json')

    def test_missing_corrupt_and_wrong_resolution_images(self):
        nd=self.node();image=nd/'outputs/final.png'
        image.unlink()
        with self.assertRaises(InvalidDelivery):validate(nd/'part.json')
        image.write_bytes(b'not PNG')
        with self.assertRaisesRegex(InvalidDelivery,'Invalid PNG'):validate(nd/'part.json')
        Image.new('RGB',(64,48)).save(image)
        with self.assertRaisesRegex(InvalidDelivery,'expected'):validate(nd/'part.json')

    def test_transitive_invalid_child_and_cycles(self):
        nd=self.node(children=['child']);child=self.node('child','scene')
        validate(nd/'part.json')
        (child/'outputs/final.png').unlink()
        with self.assertRaises(InvalidDelivery):validate(nd/'part.json')
        Image.new('RGB',(32,24)).save(child/'outputs/final.png')
        d=json.loads((child/'part.json').read_text());d['children']=['scene'];atomic_json(child/'part.json',d)
        with self.assertRaisesRegex(InvalidDelivery,'Cycle'):validate(nd/'part.json')

    def test_escaping_paths_and_symlinks(self):
        nd=self.node();d=json.loads((nd/'part.json').read_text());d['module']='../outside.js';atomic_json(nd/'part.json',d)
        with self.assertRaisesRegex(InvalidDelivery,'relative'):validate(nd/'part.json')
        outside=self.base/'outside.js';outside.write_text('export function build(){}')
        (nd/'component.js').unlink();(nd/'component.js').symlink_to(outside)
        d['module']='component.js';atomic_json(nd/'part.json',d)
        with self.assertRaisesRegex(InvalidDelivery,'escaping'):validate(nd/'part.json')

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.ws=Path(self.tmp.name);rt=CODE/'runtime'
        (self.ws/'.venv').symlink_to(rt/'.venv',target_is_directory=True)
        (self.ws/'.render-tools').symlink_to(rt/'.render-tools',target_is_directory=True)
        home=self.ws/'account';home.mkdir();(home/'auth.json').write_text('{"fake":true}')
        Image.new('RGB',(32,24)).save(self.ws/'ref.png')
        self.env=dict(os.environ,RCWM_ROOT=str(self.ws),CODEX_HOME=str(home),
                      PATH=str(CODE/'tests/fake-codex')+os.pathsep+os.environ['PATH'],RCWM_PACKAGING_REPAIRS='0')
        for key in ['RCWM_PROMPT','RCWM_CLEAN_CODEX_HOME','RCWM_CODEX_CONFIG','RCWM_TEST_MODE','NODE_OPTIONS']:
            self.env.pop(key,None)
        self.run=self.ws/'runs/test'

    def launch(self,mode='success',cycles=3,repairs=0):
        env=dict(self.env,RCWM_TEST_MODE=mode,RCWM_PACKAGING_REPAIRS=str(repairs))
        result=subprocess.run(['bash',str(CODE/'rcwm.sh'),str(self.ws/'ref.png'),'test','4',str(cycles)],env=env,capture_output=True,text=True,timeout=30)
        return result

    def events(self):return [json.loads(l) for l in (self.run/'trace/events.jsonl').read_text().splitlines()]

    def test_success_result_logs_and_stale_picker(self):
        result=self.launch();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(check_run(self.run),self.run/'fractal/scene/outputs/final.png')
        events=self.events();ends=[e for e in events if e['event']=='session_end']
        self.assertEqual(len(ends),4);self.assertEqual(sum(e['usage_total'] for e in ends),4936)
        self.assertTrue(all(e['exit_code']==0 for e in ends))
        for n in ['scene','house-a','house-b']:
            self.assertTrue((self.run/'fractal'/n/'logs/codex.log').exists())
            self.assertTrue((self.run/'fractal'/n/'logs/events.jsonl').exists())
        self.assertTrue((self.run/'logs/run.log').exists())
        self.assertEqual(len(list((self.run/'fractal/scene/logs/sessions').glob('*.log'))),2)
        sys.path.insert(0,str(CODE/'experiments'));import pickers
        pickers.OURS_CHAIN=str(self.run)
        self.assertTrue(pickers.ours(str(self.ws),'test')[1])
        # A legacy-looking image must not override invalidated v2 status.
        shutil.copyfile(self.ws/'ref.png',self.run/'fractal/scene/final.png')
        (self.run/'fractal/house-a/component.js').write_text('changed source')
        self.assertEqual(pickers.ours(str(self.ws),'test'),(None,False))

    def test_interruption_records_failure_and_session_exit(self):
        env=dict(self.env,RCWM_TEST_MODE='wait')
        proc=subprocess.Popen(['bash',str(CODE/'rcwm.sh'),str(self.ws/'ref.png'),'test','4','3'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+10
            while not (self.run/'fractal/scene/work/waiting').exists():
                if proc.poll() is not None or time.monotonic()>deadline:self.fail('fixture did not start')
                time.sleep(.03)
            state=json.loads((self.run/'result.json').read_text())
            os.kill(state['pid'],signal.SIGTERM)
            self.assertNotEqual(proc.wait(timeout=15),0)
            self.assertEqual(json.loads((self.run/'result.json').read_text())['status'],'interrupted')
            ends=[e for e in self.events() if e['event']=='session_end']
            self.assertEqual(len(ends),1)
            self.assertNotEqual(ends[0]['exit_code'],0)
            with self.assertRaises(InvalidDelivery):check_run(self.run)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()

    def test_executor_failure_cannot_be_hidden_by_part(self):
        result=self.launch('executor_failure');self.assertNotEqual(result.returncode,0)
        state=json.loads((self.run/'result.json').read_text());self.assertEqual(state['status'],'child_failed')
        ends=[e for e in self.events() if e['event']=='session_end' and e['node_id']=='house-a']
        self.assertEqual(ends[0]['exit_code'],7)
        self.assertEqual(sum(e['event']=='session_start' and e['node_id']=='scene' for e in self.events()),1)

    def test_invalid_child_is_not_delivered(self):
        result=self.launch('invalid_manifest');self.assertNotEqual(result.returncode,0)
        returns=[e for e in self.events() if e['event']=='child_return' and e['child']=='house-a']
        self.assertFalse(returns[0]['delivered'])
        self.assertEqual(json.loads((self.run/'fractal/house-a/result.json').read_text())['status'],'invalid_delivery')

    def test_bounded_packaging_repair(self):
        result=self.launch('repair_manifest',repairs=1);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        repairs=[e for e in self.events() if e['event']=='session_start' and e.get('purpose')=='packaging']
        self.assertEqual(len(repairs),1);self.assertEqual(repairs[0]['cycle'],1)
        check_run(self.run)

    def test_persistent_invalid_manifest_exits_after_one_repair(self):
        result=self.launch('invalid_manifest',repairs=1);self.assertNotEqual(result.returncode,0)
        self.assertEqual(sum(e['event']=='session_start' and e.get('purpose')=='packaging' for e in self.events()),1)

    def test_last_cycle_does_not_launch_unintegratable_children(self):
        result=self.launch(cycles=1);self.assertNotEqual(result.returncode,0)
        self.assertEqual(json.loads((self.run/'result.json').read_text())['status'],'budget_exhausted')
        self.assertFalse(any(e['event']=='child_call' for e in self.events()))

    def test_resume_failed_child_then_integrate_without_repeating_good_child(self):
        result=self.launch('executor_failure');self.assertNotEqual(result.returncode,0)
        good_log=self.run/'fractal/house-b/logs/codex.log';before=good_log.read_bytes()
        result=subprocess.run(['bash',str(CODE/'tools/resume_run.sh'),'test'],env=self.env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(good_log.read_bytes(),before)
        self.assertEqual(len(list((self.run/'fractal/house-a/logs/sessions').glob('*.log'))),2)
        check_run(self.run)

if __name__=='__main__':unittest.main()
