"""R8 adversarial checks alter valid files; all originals remain read-only."""
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
    def attempt(self, kind, expected):
        source=Path(os.environ['NDU_R8_SOURCE']); runs=Path(os.environ['NDU_R8_RUNS'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); fake=root/'runs'; fake.mkdir()
            for n in ('PLAN.json','COMPLETE.json','TRAIN_LAWS.npz'):
                shutil.copy2(runs/n,fake/n)
            census=json.loads((fake/'COMPLETE.json').read_text());first=census['census'][0]['name']
            for row in census['census']:
                if row['name']==first:
                    shutil.copytree(runs/first,fake/first)
                else:
                    (fake/row['name']).symlink_to(runs/row['name'],target_is_directory=True)
            report_path=fake/first/'REPORT.json';report=json.loads(report_path.read_text())
            if kind=='census':
                census['census'].pop()
            elif kind=='tensor':
                path=fake/first/'WEIGHTS.npz';t=np.load(path,allow_pickle=False)['theta'].copy();t[0]+=.1
                np.savez_compressed(path,theta=t)
            elif kind=='score':
                report['metrics']['cc17']+=.1
            elif kind=='time':
                info=report['fit'];expected='false observed time' if info['success'] else 'censoring converted to success'
                info['observed_wall']=0.0
                (fake/first/'FIT.json').write_text(json.dumps(info))
                sealpath=fake/first/'FIT_SEAL.json';seal=json.loads(sealpath.read_text())
                seal['fit_sha256']=hashlib.sha256((fake/first/'FIT.json').read_bytes()).hexdigest()
                sealpath.write_text(json.dumps(seal))
            elif kind=='law':
                path=fake/'TRAIN_LAWS.npz';data=dict(np.load(path,allow_pickle=False))
                data['cc5_weights']=data['cc5_weights'].copy();data['cc5_weights'][0]+=.00001
                np.savez_compressed(path,**data)
                planpath=fake/'PLAN.json';plan=json.loads(planpath.read_text())
                plan['law_hash']=hashlib.sha256(path.read_bytes()).hexdigest();planpath.write_text(json.dumps(plan))
                census['plan_sha256']=hashlib.sha256(planpath.read_bytes()).hexdigest()
            if kind in ('score','time'):
                report_path.write_text(json.dumps(report))
                census['census'][0]['report_sha256']=hashlib.sha256(report_path.read_bytes()).hexdigest()
            (fake/'COMPLETE.json').write_text(json.dumps(census))
            command=[sys.executable,'-O',str(Path(__file__).with_name('verify.py')),
                     '--source',str(source),'--runs',str(fake),'--out',str(root/'audit')]
            result=subprocess.run(command,capture_output=True,text=True,timeout=60)
            self.assertNotEqual(result.returncode,0);self.assertIn(expected,result.stderr)
            self.assertFalse((root/'audit/AUDIT.json').exists())

    def test_missing_case(self):self.attempt('census','incomplete census')
    def test_tensor_changed(self):self.attempt('tensor','weight mismatch')
    def test_rehashed_score(self):self.attempt('score','metric mismatch')
    def test_rehashed_observed_time(self):self.attempt('time','censoring converted to success')
    def test_rehashed_integration_mass(self):self.attempt('law','Arrays are not equal')


if __name__=='__main__':unittest.main(verbosity=2)
