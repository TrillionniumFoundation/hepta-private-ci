"""Real archive tampering tests: missing run, false cost/time, weight and certificate."""
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
    def attempt(self,kind,expected):
        source=Path(os.environ['NDU_R15_SOURCE'])
        runs=Path(os.environ['NDU_R15_RUNS'])
        with tempfile.TemporaryDirectory() as tmp:
            temp=Path(tmp);fake=temp/'runs';fake.mkdir()
            for filename in ('PLAN.json','COMPLETE.json','CERTIFICATE.json'):
                shutil.copy2(runs/filename,fake/filename)
            done=json.loads((fake/'COMPLETE.json').read_text())
            original=done['census'][0]['name']
            for entry in done['census']:
                if entry['name']==original:
                    shutil.copytree(runs/original,fake/original)
                else:
                    (fake/entry['name']).symlink_to(runs/entry['name'],target_is_directory=True)
            p=fake/original/'REPORT.json';r=json.loads(p.read_text())
            if kind=='missing':done['census'].pop()
            elif kind=='weights':
                f=fake/original/'WEIGHTS.npz'
                with np.load(f,allow_pickle=False) as z:theta=z['theta'].copy()
                theta[0]+=.125
                np.savez_compressed(f,theta=theta)
            elif kind=='cost':r['final_direct_cost']+=.25
            elif kind=='history':
                r['fit']['history'][0]['objective']+=.25
                (fake/original/'FIT.json').write_text(json.dumps(r['fit']))
                sp=fake/original/'FIT_SEAL.json';seal=json.loads(sp.read_text())
                seal['fit_sha256']=hashlib.sha256((fake/original/'FIT.json').read_bytes()).hexdigest()
                sp.write_text(json.dumps(seal))
            elif kind=='time':r['fit']['quality_first_cpu']=0.
            elif kind=='certificate':
                f=fake/'CERTIFICATE.json';c=json.loads(f.read_text())
                c['true_global_optimum_distance_upper']='0'
                f.write_text(json.dumps(c))
            if kind in ('cost','history','time'):
                p.write_text(json.dumps(r))
                done['census'][0]['report_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
            (fake/'COMPLETE.json').write_text(json.dumps(done))
            cmd=[sys.executable,'-O',str(source/'audit.py'),'--runs',str(fake),'--out',str(temp/'audit')]
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=90,
                                  env=dict(os.environ,OPENBLAS_NUM_THREADS='1'))
            self.assertNotEqual(result.returncode,0)
            self.assertIn(expected,result.stderr)
            self.assertFalse((temp/'audit/AUDIT.json').exists())
    def test_01_missing_census(self):self.attempt('missing','incomplete census')
    def test_02_changed_tensor(self):self.attempt('weights','selected weights altered')
    def test_03_rehashed_false_cost(self):self.attempt('cost','false independent cost')
    def test_04_rehashed_history(self):self.attempt('history','checkpoint score corrupted')
    def test_05_fake_quality_time(self):self.attempt('time','fit history altered')
    def test_06_cert_forgery(self):self.attempt('certificate','certificate mismatch')

if __name__=='__main__':unittest.main(verbosity=2)
