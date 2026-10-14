import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import run_checked_tests as checked


class CheckedRunnerTests(unittest.TestCase):
    def run_inner(self, body):
        # Construct nested suites dynamically; do not expose them to discovery.
        case = type('Inner', (unittest.TestCase,), {'test_body': body})
        return checked.run_checked_suite(unittest.defaultTestLoader.loadTestsFromTestCase(case),
                                         stream=io.StringIO())

    def test_complete_success_reports_exact_ids(self):
        report = self.run_inner(lambda self: self.assertEqual(1 + 1, 2))
        self.assertTrue(report['passed'])
        self.assertEqual(report['planned_ids'], report['executed_ids'])
        self.assertFalse(report['model_qualification'])

    def test_skip_and_expected_failure_are_not_success(self):
        skipped = self.run_inner(lambda self: self.skipTest('missing dependency'))
        self.assertFalse(skipped['passed'])
        self.assertEqual(skipped['skips'], 1)
        body = unittest.expectedFailure(lambda self: self.fail('known bug'))
        expected = self.run_inner(body)
        self.assertFalse(expected['passed'])
        self.assertEqual(expected['expected_failures'], 1)

    def test_setup_failure_marks_inventory_incomplete(self):
        def broken(cls):
            raise RuntimeError('setup failed')
        case = type('Broken', (unittest.TestCase,), {
            'setUpClass': classmethod(broken), 'test_body': lambda self: None})
        report = checked.run_checked_suite(unittest.defaultTestLoader.loadTestsFromTestCase(case),
                                           stream=io.StringIO())
        self.assertFalse(report['passed'])
        self.assertFalse(report['complete'])
        self.assertEqual(report['executed'], 0)
        self.assertEqual(report['errors'], 1)

    def test_empty_duplicate_or_discovery_error_refuses_green(self):
        with self.assertRaises(ValueError):
            checked.run_checked_suite(unittest.TestSuite(), stream=io.StringIO())
        case = type('Inner', (unittest.TestCase,), {'test_body': lambda self: None})
        with self.assertRaises(ValueError):
            checked.run_checked_suite(unittest.TestSuite([case('test_body'), case('test_body')]),
                                       stream=io.StringIO())
        report = checked.run_checked_suite(unittest.TestSuite([case('test_body')]),
                                           loader_errors=['import failed'], stream=io.StringIO())
        self.assertFalse(report['passed'])

    def test_cli_keeps_import_error_and_prevents_output_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'test_missing.py').write_text('import hepta_deliberately_absent_dependency\n')
            output = root/'result.json'
            cmd = [sys.executable, checked.__file__, '--start', td, '--output', str(output)]
            first = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertEqual(first.returncode, 1)
            report = json.loads(output.read_text())
            self.assertFalse(report['passed'])
            self.assertEqual(len(report['discovery_errors']), 1)
            self.assertIn('hepta_deliberately_absent_dependency', first.stderr)
            before = output.read_bytes()
            self.assertNotEqual(subprocess.run(cmd, capture_output=True, timeout=15).returncode, 0)
            self.assertEqual(output.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
