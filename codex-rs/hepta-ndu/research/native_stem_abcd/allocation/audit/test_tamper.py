"""R9 real-file tampering tests, including rehashed logs and exact-skip identity."""
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
        source, runs = Path(os.environ['NDU_R9_SOURCE']), Path(os.environ['NDU_R9_RUNS'])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); fake = root/'runs'; fake.mkdir()
            for name in ('PLAN.json', 'COMPLETE.json', 'LAWS.npz'):
                shutil.copy2(runs/name, fake/name)
            census = json.loads((fake/'COMPLETE.json').read_text())
            first = census['census'][0]['name']
            for row in census['census']:
                if row['name'] == first:
                    shutil.copytree(runs/first, fake/first)
                else:
                    (fake/row['name']).symlink_to(runs/row['name'], target_is_directory=True)
            folder = fake/first
            report = json.loads((folder/'REPORT.json').read_text())
            if kind == 'census':
                census['census'].pop()
            elif kind == 'tensor':
                with np.load(folder/'WEIGHTS.npz', allow_pickle=False) as data:
                    theta = data['theta'].copy()
                theta[0] += .1
                np.savez_compressed(folder/'WEIGHTS.npz', theta=theta)
            elif kind == 'metric':
                report['costs']['gl9'] += .1
            elif kind in ('time', 'skip'):
                info = report['fit']
                if kind == 'time':
                    expected = 'false observed time' if info['success'] else 'censoring became success time'
                    info['observed_wall'] = 0.
                else:
                    info['checks'][0]['cc9'] = None
                (folder/'FIT.json').write_text(json.dumps(info))
                seal = json.loads((folder/'FIT_SEAL.json').read_text())
                seal['fit'] = hashlib.sha256((folder/'FIT.json').read_bytes()).hexdigest()
                (folder/'FIT_SEAL.json').write_text(json.dumps(seal))
            elif kind == 'law':
                with np.load(fake/'LAWS.npz', allow_pickle=False) as data:
                    laws = {key: data[key].copy() for key in data.files}
                laws['gl5_weights'][0] += .00001
                np.savez_compressed(fake/'LAWS.npz', **laws)
                plan = json.loads((fake/'PLAN.json').read_text())
                plan['law_sha256'] = hashlib.sha256((fake/'LAWS.npz').read_bytes()).hexdigest()
                (fake/'PLAN.json').write_text(json.dumps(plan))
                census['plan_sha256'] = hashlib.sha256((fake/'PLAN.json').read_bytes()).hexdigest()
            if kind in ('metric', 'time', 'skip'):
                (folder/'REPORT.json').write_text(json.dumps(report))
                census['census'][0]['report_sha256'] = hashlib.sha256((folder/'REPORT.json').read_bytes()).hexdigest()
            (fake/'COMPLETE.json').write_text(json.dumps(census))
            cmd = [sys.executable, '-O', str(Path(__file__).with_name('verify.py')),
                   '--source', str(source), '--runs', str(fake), '--out', str(root/'audit')]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected, result.stderr)
            self.assertFalse((root/'audit/AUDIT.json').exists())

    def test_missing_case(self): self.attempt('census', 'incomplete census')
    def test_changed_tensor(self): self.attempt('tensor', 'weight hash mismatch')
    def test_rehashed_cost(self): self.attempt('metric', 'metric mismatch')
    def test_rehashed_time(self): self.attempt('time', 'false observed time')
    def test_rehashed_illegal_skip(self): self.attempt('skip', 'invalid fine skip')
    def test_rehashed_gaussian_law(self): self.attempt('law', 'Arrays are not equal')


if __name__ == '__main__':
    unittest.main(verbosity=2)
