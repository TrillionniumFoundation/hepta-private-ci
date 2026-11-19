"""R14 reject real rehashed evidence tampering even under python -O."""
import hashlib
import os
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import numpy as np

SRC=Path(__file__).resolve().parent
RUNS=Path(os.environ.get('NDU_R14_RUNS',str(SRC/'runs')))

class TamperTests(unittest.TestCase):
    def corrupt(self,kind,error_text):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);fake=base/'runs';fake.mkdir()
            for filename in ('PLAN.json','COMPLETE.json','CERTIFICATE.json'):
                shutil.copy2(RUNS/filename,fake/filename)
            complete=json.loads((fake/'COMPLETE.json').read_text())
            first=complete['census'][0]['name']
            for row in complete['census']:
                if row['name']==first:shutil.copytree(RUNS/first,fake/first)
                else:(fake/row['name']).symlink_to(RUNS/row['name'],target_is_directory=True)
            report_path=fake/first/'REPORT.json'
            report=json.loads(report_path.read_text())
            if kind=='missing':complete['census'].pop()
            elif kind=='weights':
                p=fake/first/'WEIGHTS.npy';a=np.load(p,allow_pickle=False).copy();a[0]+=.4
                with p.open('wb') as f:np.save(f,a,allow_pickle=False)
            elif kind=='time':report['result']['first_quality_cpu']=0.
            elif kind=='cost':report['result']['final_cost']+=.1
            elif kind=='source':
                p=fake/'PLAN.json';s=json.loads(p.read_text());s['source']['solver.py']='0'*64
                p.write_text(json.dumps(s));complete['plan_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
            elif kind=='certificate':
                p=fake/'CERTIFICATE.json';s=json.loads(p.read_text());s['global_hessian_lower_bound']='0'
                p.write_text(json.dumps(s))
            if kind in ('time','cost'):
                report_path.write_text(json.dumps(report))
                complete['census'][0]['report_sha256']=hashlib.sha256(report_path.read_bytes()).hexdigest()
            (fake/'COMPLETE.json').write_text(json.dumps(complete))
            command=[sys.executable,'-O',str(SRC/'audit.py'),'--source',str(SRC),
                     '--runs',str(fake),'--out',str(base/'verified')]
            process=subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertNotEqual(process.returncode,0,kind)
            self.assertIn(error_text,process.stderr)
            self.assertFalse((base/'verified/RECEIPT.json').exists())
    def test_missing_run(self):self.corrupt('missing','missing or reordered cases')
    def test_changed_weight(self):self.corrupt('weights','trained weight SHA mismatch')    def test_rehashed_false_time(self):self.corrupt('time','forged time')
    def test_rehashed_false_cost(self):self.corrupt('cost','forged final cost')
    def test_rehashed_source_forgery(self):self.corrupt('source','source identity mismatch')
    def test_exact_certificate_forgery(self):self.corrupt('certificate','exact certificate mismatch')

if __name__=='__main__':unittest.main(verbosity=2)
