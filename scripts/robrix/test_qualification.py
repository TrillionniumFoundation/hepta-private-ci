"""Guard against counting compile-only, empty, skipped or failed tests as execution."""
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import qualify


class TestExecutionGate(unittest.TestCase):
    def check(self, output, minimum=4):
        with patch.object(qualify, 'run', return_value=output):
            qualify.checked_tests(['not-executed'], 'unused', minimum)

    def test_executed_tests_pass(self):
        self.check('test result: ok. 4 passed; 0 failed; 0 ignored; 12 filtered out')

    def test_compile_only_rejected(self):
        with self.assertRaises(AssertionError):
            self.check('Finished `test` profile. Executable app.wasm')

    def test_zero_tests_rejected(self):
        with self.assertRaises(AssertionError):
            self.check('test result: ok. 0 passed; 0 failed; 0 ignored; 19 filtered out')

    def test_missing_required_count_rejected(self):
        with self.assertRaises(AssertionError):
            self.check('test result: ok. 3 passed; 0 failed; 0 ignored')

    def test_ignored_tests_rejected(self):
        with self.assertRaises(AssertionError):
            self.check('test result: ok. 4 passed; 0 failed; 1 ignored')

    def test_failed_tests_rejected(self):
        with self.assertRaises(AssertionError):
            self.check('test result: FAILED. 4 passed; 1 failed; 0 ignored')

    def test_failed_process_keeps_partial_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(qualify, 'OUT', Path(directory)):
                with self.assertRaises(subprocess.CalledProcessError):
                    qualify.run([sys.executable, '-c', 'print("partial evidence"); raise SystemExit(7)'],
                                log='failure.log')
                self.assertEqual((Path(directory) / 'failure.log').read_text(), 'partial evidence\n')

    def test_nonzero_process_rejected(self):
        with patch.object(qualify, 'run', side_effect=subprocess.CalledProcessError(1, 'test')):
            with self.assertRaises(subprocess.CalledProcessError):
                qualify.checked_tests(['not-executed'], 'unused', 1)


if __name__ == '__main__':
    unittest.main()
