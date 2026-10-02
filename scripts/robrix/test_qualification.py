"""Guard against counting compile-only, empty, skipped or failed tests as execution."""
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
import qualify
from browser_test_runner import passing_summary


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


class TestNativeWindowIdentity(unittest.TestCase):
    def test_unique_resource_instance_and_exact_title_are_required(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(qualify.subprocess, 'run', return_value=Mock(returncode=0, stdout='42\n')) as search:
            with patch.object(qualify, 'run', return_value=qualify.FIXTURE_TITLE):
                self.assertEqual(qualify.select_fixture_window(process, 'unique-fixture'), '42')
        self.assertEqual(search.call_args.args[0], ['xdotool', 'search', '--onlyvisible',
                                                   '--classname', r'^unique\-fixture$'])

    def test_duplicate_identity_is_rejected(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(qualify.subprocess, 'run', return_value=Mock(returncode=0, stdout='42\n43\n')):
            with self.assertRaisesRegex(RuntimeError, 'Multiple'):
                qualify.select_fixture_window(process, 'fixture')

    def test_dead_process_is_rejected_before_matching_a_window(self):
        process = Mock(returncode=1)
        process.poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, 'exited'):
            qualify.select_fixture_window(process, 'fixture')

    def test_unrelated_title_cannot_be_accepted(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(qualify.time, 'monotonic', side_effect=[0, 1, 61]):
            with patch.object(qualify.time, 'sleep'):
                with patch.object(qualify.subprocess, 'run', return_value=Mock(returncode=0, stdout='42\n')):
                    with patch.object(qualify, 'run', return_value='Unrelated app'):
                        with self.assertRaisesRegex(RuntimeError, 'exact fixture title'):
                            qualify.select_fixture_window(process, 'fixture')


class TestBrowserCompletion(unittest.TestCase):
    def test_success_requires_executed_nonignored_tests(self):
        self.assertTrue(passing_summary('test result: ok. 13 passed; 0 failed; 0 ignored;'))
        for output in ['Loading scripts...', 'test result: ok. 0 passed; 0 failed; 0 ignored;',
                       'test result: ok. 12 passed; 0 failed; 1 ignored;',
                       'test result: FAILED. 12 passed; 1 failed; 0 ignored;']:
            self.assertFalse(passing_summary(output))


if __name__ == '__main__':
    unittest.main()
