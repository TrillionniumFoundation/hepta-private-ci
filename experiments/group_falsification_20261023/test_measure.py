"""Regression coverage for completed-child and child-launch failure accounting."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MEASURE = Path(__file__).with_name('measure.py')


class MeasurementTests(unittest.TestCase):
    def record(self, command):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            result = subprocess.run([sys.executable, str(MEASURE), str(path), *command],
                                    capture_output=True, text=True, check=False)
            self.assertTrue(path.is_file(), result.stderr)
            return result.returncode, json.loads(path.read_text())

    def test_nonzero_child_records_measured_cost(self):
        code, record = self.record([sys.executable, '-c', 'raise SystemExit(7)'])
        self.assertEqual((code, record['exit_code'], record['status']), (7, 7, 'child_failed'))
        for key in ('wall_seconds', 'user_cpu_seconds', 'system_cpu_seconds', 'peak_rss_KiB'):
            self.assertGreaterEqual(record[key], 0)

    def test_missing_executable_records_unknown_child_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            code, record = self.record([str(Path(directory) / 'does-not-exist')])
        self.assertEqual((code, record['exit_code'], record['status']), (127, None, 'launch_failed'))
        self.assertEqual(record['error']['type'], 'FileNotFoundError')
        self.assertGreaterEqual(record['wall_seconds'], 0)
        for key in ('user_cpu_seconds', 'system_cpu_seconds', 'peak_rss_KiB'):
            self.assertIsNone(record[key])

    def test_success_records_measured_cost(self):
        code, record = self.record([sys.executable, '-c', 'pass'])
        self.assertEqual((code, record['exit_code'], record['status']), (0, 0, 'succeeded'))


if __name__ == '__main__':
    unittest.main()
