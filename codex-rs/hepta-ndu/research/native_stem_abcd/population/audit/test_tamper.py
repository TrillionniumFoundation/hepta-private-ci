"""Real-artifact tamper tests, including optimized Python; originals untouched."""
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
    def attempt(self,kind):
        source=Path(os.environ['NDU_R4_SOURCE']).resolve();runs=Path(os.environ['NDU_R4_RUNS']).resolve()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fake=root/'runs';fake.mkdir()
            for n in ('PLAN.json','COMPLETE.json'):shutil.copy2(runs/n,fake/n)
            c=json.loads((fake/'COMPLETE.json').read_text());first=c['census'][0]['name']
            for r in c['census']:
                if r['name']==first:shutil.copytree(runs/first,fake/first)
                else:(fake/r['name']).symlink_to(runs/r['name'],target_is_directory=True)
            if kind=='census':c['census'].pop()
            elif kind=='weights':
                p=fake/first/'WEIGHTS.npy';b=bytearray(p.read_bytes());b[-1]^=1;p.write_bytes(b)
            else:
                p=fake/first/'REPORT.json';r=json.loads(p.read_text())
                if kind=='metric':r['metrics']['new_initial']['objective_gap']+=.1
                else:r['run']['cap']=999
                p.write_text(json.dumps(r));c['census'][0]['report_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
            (fake/'COMPLETE.json').write_text(json.dumps(c))
            cmd=[sys.executable,'-O',str(Path(__file__).with_name('verify.py')),
                 '--source',str(source),'--runs',str(fake),'--out',str(root/'checked')]
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=40)
            self.assertNotEqual(r.returncode,0);self.assertIn('ValueError',r.stderr)
            self.assertFalse((root/'checked'/'AUDIT.json').exists())

    def test_incomplete_census(self):self.attempt('census')
    def test_altered_weights(self):self.attempt('weights')
    def test_rehashed_false_metric(self):self.attempt('metric')
    def test_rehashed_budget_identity(self):self.attempt('identity')


if __name__=='__main__':unittest.main(verbosity=2)
