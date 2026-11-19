"""Adversarial audit tests on real archived outputs; never modifies originals."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class AuditTamperTests(unittest.TestCase):
    def execute_case(self, mutation):
        source = Path(os.environ['NDU_R2_SOURCE']).resolve()
        runs = Path(os.environ['NDU_R2_RUNS']).resolve()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / 'runs'
            fake.mkdir()
            shutil.copy2(runs / 'PLAN.json', fake / 'PLAN.json')
            shutil.copy2(runs / 'COMPLETE.json', fake / 'COMPLETE.json')
            complete = json.loads((fake / 'COMPLETE.json').read_text())
            first = complete['census'][0]['name']
            for item in complete['census']:
                name = item['name']
                if name == first:
                    shutil.copytree(runs / name, fake / name)
                else:
                    (fake / name).symlink_to(runs / name, target_is_directory=True)
            mutation(fake, first)
            command = [sys.executable, str(Path(__file__).with_name('structure_audit.py')),
                       '--source', str(source), '--runs', str(fake), '--out', str(root / 'out')]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30,
                                    env=dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                                             OPENBLAS_NUM_THREADS='1'))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('AssertionError', result.stderr)
            self.assertFalse((root / 'out' / 'AUDIT.json').exists())

    def test_missing_run_cannot_be_complete_success(self):
        def mutation(root, first):
            data = json.loads((root / 'COMPLETE.json').read_text())
            data['census'].pop()
            (root / 'COMPLETE.json').write_text(json.dumps(data))
        self.execute_case(mutation)

    def test_prediction_byte_tamper_rejected(self):
        def mutation(root, first):
            path = root / first / 'PREDICTIONS.npz'
            data = bytearray(path.read_bytes())
            data[100] ^= 1
            path.write_bytes(data)
        self.execute_case(mutation)

    def test_metric_tamper_even_with_recomputed_report_hash(self):
        def mutation(root, first):
            path = root / first / 'REPORT.json'
            data = json.loads(path.read_text())
            data['metrics']['new_uniform']['rmse'] += 0.2
            path.write_text(json.dumps(data))
            complete = json.loads((root / 'COMPLETE.json').read_text())
            complete['census'][0]['report_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            (root / 'COMPLETE.json').write_text(json.dumps(complete))
        self.execute_case(mutation)


if __name__ == '__main__':
    unittest.main(verbosity=2)
