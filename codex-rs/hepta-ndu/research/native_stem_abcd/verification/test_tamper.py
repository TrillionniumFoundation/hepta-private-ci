"""Real-file tamper rejection under optimized Python; R10 original is never modified."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class CertificateTamperTests(unittest.TestCase):
    def attempt(self, kind, expected):
        packet=Path(os.environ['NDU_R11_PACKET'])
        original=Path(os.environ['NDU_R11_RUNS'])
        archive=Path(os.environ['NDU_R11_ARCHIVE'])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            fake=root/'fake';fake.mkdir()
            for name in ('PLAN.json','COMPLETE.json','MANUFACTURED.json','INPUT_AUDIT.json'):
                shutil.copy2(original/name,fake/name)
            allcases=sorted(p.name for p in original.glob('w*.json'))
            self.assertEqual(len(allcases),96)
            first=allcases[0]
            for name in allcases:
                if name==first:
                    shutil.copy2(original/name,fake/name)
                else:
                    (fake/name).symlink_to(original/name)
            path=fake/first
            row=json.loads(path.read_text())
            if kind=='missing':path.unlink()
            elif kind=='value':row['new_evaluations']['gl11']+=0.02
            elif kind=='radius':row['quad_radii']['gl11']['radius_upper']*=.01
            elif kind=='authority':row['machine_certified']=True
            elif kind=='weight':row['r10_weight_sha256']='0'*64
            elif kind=='old':row['frozen_cc17']+=.01
            elif kind=='limit':
                manifest=json.loads((fake/'COMPLETE.json').read_text())
                manifest['legacy_pass']=96
                (fake/'COMPLETE.json').write_text(json.dumps(manifest))
            if kind not in ('missing','limit'):
                path.write_text(json.dumps(row))
            cmd=[sys.executable,'-O',str(Path(__file__).with_name('audit.py')),
                 '--packet',str(packet),'--archive',str(archive),
                 '--runs',str(fake),'--out',str(root/'verified')]
            done=subprocess.run(cmd,capture_output=True,text=True,timeout=60,
                                env=dict(os.environ,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1'))
            self.assertNotEqual(done.returncode,0)
            self.assertIn(expected,done.stderr)
            self.assertFalse((root/'verified'/'AUDIT.json').exists())

    def test_missing_case(self):self.attempt('missing','missing frozen-candidate result')
    def test_manipulated_rule(self):self.attempt('value','independent numerical rule mismatch')
    def test_false_radius(self):self.attempt('radius','W1 radius mismatch')
    def test_false_machine_certificate(self):self.attempt('authority','false machine certification')
    def test_bad_prior_weight_binding(self):self.attempt('weight','weight binding mismatch')
    def test_false_prior_reference(self):self.attempt('old','frozen R10 cost changed')
    def test_fake_qualification_count(self):self.attempt('limit','historical gate count changed')


if __name__=='__main__':unittest.main(verbosity=2)
