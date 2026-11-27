"""Adversarial changes to COPIES of completed runs, tested with python -O."""
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


class TamperTests(unittest.TestCase):
    def attempt(self, kind):
        source=Path(os.environ['NDU_R7_SOURCE'])
        runs=Path(os.environ['NDU_R7_RUNS'])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fake=root/'runs';fake.mkdir()
            for n in ('PLAN.json','COMPLETE.json','EVALUATION_LAWS.npz'):
                shutil.copy2(runs/n,fake/n)
            complete=json.loads((fake/'COMPLETE.json').read_text())
            first=complete['census'][0]['name']
            for row in complete['census']:
                if row['name']==first:
                    shutil.copytree(runs/first,fake/first)
                else:
                    (fake/row['name']).symlink_to(runs/row['name'],target_is_directory=True)
            expected=None
            if kind=='census':
                complete['census'].pop();expected='census mismatch'
            elif kind=='weights':
                path=fake/first/'WEIGHTS.npz'
                weights=np.load(path,allow_pickle=False)['theta'];weights[0]+=.125
                np.savez_compressed(path,theta=weights);expected='weight hash mismatch'
            elif kind=='law':
                path=fake/first/'TRAIN_LAWS.npz'
                arrays=dict(np.load(path,allow_pickle=False));arrays['cc5_weights']=arrays['cc5_weights'].copy()
                arrays['cc5_weights'][0]+=.0001;arrays['cc5_weights'][1]-=.0001
                np.savez_compressed(path,**arrays)
                rp=fake/first/'REPORT.json';r=json.loads(rp.read_text())
                r['law_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                rp.write_text(json.dumps(r))
                complete['census'][0]['report_sha256']=hashlib.sha256(rp.read_bytes()).hexdigest()
                expected='training law content mismatch'
            else:
                rp=fake/first/'REPORT.json';r=json.loads(rp.read_text())
                if kind=='metric':
                    r['metrics']['cc17']+=.1;expected='metric mismatch'
                else:
                    r['budget']=1000.;expected='budget mismatch'
                rp.write_text(json.dumps(r))
                complete['census'][0]['report_sha256']=hashlib.sha256(rp.read_bytes()).hexdigest()
            (fake/'COMPLETE.json').write_text(json.dumps(complete))
            result=subprocess.run([sys.executable,'-O',str(Path(__file__).with_name('verify.py')),
                '--source',str(source),'--runs',str(fake),'--out',str(root/'audit')],
                capture_output=True,text=True,timeout=60)
            self.assertNotEqual(result.returncode,0)
            self.assertIn(expected,result.stderr)
            self.assertFalse((root/'audit'/'AUDIT.json').exists())

    def test_incomplete_census(self):self.attempt('census')
    def test_real_weight_tamper(self):self.attempt('weights')
    def test_rehashed_integration_law(self):self.attempt('law')
    def test_rehashed_false_score(self):self.attempt('metric')
    def test_rehashed_budget(self):self.attempt('budget')


if __name__=='__main__':
    unittest.main(verbosity=2)
