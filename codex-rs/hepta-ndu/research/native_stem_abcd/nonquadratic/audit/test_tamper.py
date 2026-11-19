"""R5 real-evidence rejection tests, including rehashed alterations and python -O."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import numpy as np

class Tamper(unittest.TestCase):
    def attempt(self,kind):
        source=Path(os.environ['NDU_R5_SOURCE']).resolve();runs=Path(os.environ['NDU_R5_RUNS']).resolve()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fake=root/'runs';fake.mkdir()
            for p in ('PLAN.json','COMPLETE.json'):shutil.copy2(runs/p,fake/p)
            c=json.loads((fake/'COMPLETE.json').read_text());first=c['census'][0]['name']
            for r in c['census']:
                if r['name']==first:shutil.copytree(runs/first,fake/first)
                else:(fake/r['name']).symlink_to(runs/r['name'],target_is_directory=True)
            if kind=='census':c['census'].pop()
            elif kind=='weight':
                p=fake/first/'WEIGHTS.npz';theta=np.load(p,allow_pickle=False)['theta'];theta[0]+=.1
                with open(p,'wb') as f:np.savez_compressed(f,theta=theta)
            else:
                p=fake/first/'REPORT.json';r=json.loads(p.read_text())
                if kind=='metric':r['train_objective']+=.1
                else:r['spec']['budget']+=1
                p.write_text(json.dumps(r));c['census'][0]['report_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
            (fake/'COMPLETE.json').write_text(json.dumps(c))
            result=subprocess.run([sys.executable,'-O',str(Path(__file__).with_name('verify.py')),'--source',str(source),
                                   '--runs',str(fake),'--out',str(root/'audit'),'--precheck'],capture_output=True,text=True,timeout=30)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((root/'audit/PRECHECK.json').exists())
            expected={'census':'incomplete census','metric':'rehashed false metric','budget':'run identity mismatch'}
            if kind=='weight':self.assertIn('weight hash mismatch',result.stderr)
            else:self.assertIn(expected[kind],result.stderr)
    def test_incomplete_census(self):self.attempt('census')
    def test_corrupt_weight(self):self.attempt('weight')
    def test_rehashed_false_metric(self):self.attempt('metric')
    def test_rehashed_budget(self):self.attempt('budget')

if __name__=='__main__':unittest.main(verbosity=2)
