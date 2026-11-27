"""Reject changed real evidence, including under python -O. Originals stay read-only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class TamperTests(unittest.TestCase):
    def attempt(self, kind):
        source=Path(os.environ['NDU_R3_SOURCE']);runs=Path(os.environ['NDU_R3_RUNS'])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fake=root/'runs';fake.mkdir()
            for n in ('PLAN.json','COMPLETE.json'):shutil.copy2(runs/n,fake/n)
            c=json.loads((fake/'COMPLETE.json').read_text());first=c['census'][0]['name']
            for r in c['census']:
                if r['name']==first:shutil.copytree(runs/first,fake/first)
                else:(fake/r['name']).symlink_to(runs/r['name'],target_is_directory=True)
            if kind=='census':c['census'].pop()
            elif kind=='prediction':
                p=fake/first/'PREDICTIONS.npz';b=bytearray(p.read_bytes());b[100]^=1;p.write_bytes(b)
            else:
                p=fake/first/'REPORT.json';r=json.loads(p.read_text())
                if kind=='metric':r['metrics']['new_composed']['rmse']+=.1
                else:r['intervals']=128
                p.write_text(json.dumps(r));c['census'][0]['report_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
            (fake/'COMPLETE.json').write_text(json.dumps(c))
            cmd=[sys.executable,'-O',str(Path(__file__).with_name('integral_audit.py')),
                 '--source',str(source),'--runs',str(fake),'--out',str(root/'audit')]
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=40)
            self.assertNotEqual(r.returncode,0)
            self.assertIn('ValueError',r.stderr)
            self.assertFalse((root/'audit'/'AUDIT.json').exists())

    def test_incomplete_census(self):self.attempt('census')
    def test_prediction_bytes(self):self.attempt('prediction')
    def test_rehashed_false_metric(self):self.attempt('metric')
    def test_rehashed_grid_substitution(self):self.attempt('grid')


if __name__=='__main__':unittest.main(verbosity=2)
