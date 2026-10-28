"""Actual child-tree, filesystem, failure and missing-observation checks."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from resource_monitor import integrate
from resource_samples import storage_snapshot, validate_roots


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux resource profile')
class ResourceMonitorTests(unittest.TestCase):
    def execute(self, root, code):
        stock = root / 'stock'
        stock.mkdir()
        paths = {key: root / (key + ('.json' if key == 'output' else '.log'))
                 for key in ('output', 'samples', 'stdout', 'stderr')}
        command = [sys.executable, '-I', '-B', str(HERE / 'resource_monitor.py')]
        for key, path in paths.items():
            command.extend(['--' + key, str(path)])
        command.extend(['--root', str(stock), '--interval-ms', '10', '--timeout-seconds', '10',
                        '--', sys.executable, '-I', '-B', '-c', code, str(stock)])
        result = subprocess.run(command, capture_output=True, timeout=15, check=False)
        return result, json.loads(paths['output'].read_bytes()), paths

    def test_observes_descendant_memory_and_growing_then_removed_stock(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-resource-') as temporary:
            code = ("import pathlib,subprocess,sys,time; p=pathlib.Path(sys.argv[1])/'value'; "
                    "p.write_bytes(b'a'*8192); data=bytearray(8*1024*1024); "
                    "child=subprocess.Popen([sys.executable,'-c','import time; a=bytearray(6*1024*1024); time.sleep(.3)']); "
                    "time.sleep(.15); p.write_bytes(b'b'*16384); child.wait(); p.unlink(); print('hepta-observed')")
            result, receipt, paths = self.execute(Path(temporary), code)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertTrue(receipt['passed'])
            self.assertFalse(receipt['full_cost_exact'])
            self.assertGreaterEqual(len(receipt['observed_process_identities']), 3)
            self.assertGreaterEqual(receipt['peaks_of_sequential_sample_sums']['storage_logical_bytes'], 16384)
            self.assertGreater(receipt['integrals']['tree_rss_bytes']['sampled_byte_ns_estimate'], 0)
            self.assertGreater(receipt['integrals']['storage_logical_bytes']['sampled_byte_ns_estimate'], 0)
            self.assertEqual(paths['stdout'].read_text(), 'hepta-observed\n')
            self.assertEqual(receipt['samples']['sha256'], hashlib.sha256(paths['samples'].read_bytes()).hexdigest())
            self.assertIsNotNone(receipt['child_exit_rusage'])

    def test_failed_child_preserves_exit_stderr_and_evidence(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-resource-fail-') as temporary:
            result, receipt, paths = self.execute(Path(temporary), "import sys; print('deliberate failure',file=sys.stderr); sys.exit(7)")
            self.assertEqual((result.returncode, receipt['passed'], receipt['exit_code']), (1, False, 7))
            self.assertEqual(paths['stderr'].read_text(), 'deliberate failure\n')

    def test_missing_measurement_never_becomes_zero_cost(self):
        totals = {'rss': {'trapezoid_numerator_byte_ns': 0, 'observed_interval_ns': 0, 'unobserved_interval_ns': 0}}
        integrate({'monotonic_ns': 10, 'metrics': {'rss': 20}},
                  {'monotonic_ns': 40, 'metrics': {'rss': None}}, totals)
        self.assertEqual(totals, {'rss': {'trapezoid_numerator_byte_ns': 0,
                                        'observed_interval_ns': 0, 'unobserved_interval_ns': 30}})

    def test_overlapping_roots_and_symlink_stock_are_not_silently_counted(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-resource-path-') as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                validate_roots([str(root), str(root / 'nested')])
            (root / 'linked').symlink_to('/dev/null')
            observed = storage_snapshot([root])
            self.assertIsNone(observed['logical_bytes'])
            self.assertGreater(observed['error_count'], 0)


if __name__ == '__main__':
    unittest.main()
