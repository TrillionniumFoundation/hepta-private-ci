"""Synthetic runner controls, not product/native qualification."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import nextest_fd_runner as runner


class FdRunnerControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / 'target'
        self.target.mkdir()
        self.image = self.target / 'fixture_probe-0123456789abcdef'
        shutil.copyfile(Path('/proc/self/exe').resolve(), self.image)
        self.image.chmod(0o700)
        self.directory = self.root / 'captures'
        self.directory.mkdir()
        self.config = self.root / 'config.json'
        self.data = {'schema': 'hepta-nextest-fd-runner-v1', 'target': str(self.target),
                     'crate': 'fixture_probe', 'gate': 'synthetic-only',
                     'directory': str(self.directory), 'selected_names': ['fixture::case'],
                     'predicate': None, 'source': {'scope': 'synthetic fixture only'},
                     'coordinator': {'pid': os.getpid(), 'start_ticks': runner.task(os.getpid())[1]}}
        self.config.write_text(json.dumps(self.data))
        self.env = dict(os.environ, HEPTA_NEXTEST_FD_CAPTURE_CONFIG=str(self.config),
                        NEXTEST_TEST_PHASE='run', PYTHONHOME=sys.prefix,
                        PYTHONDONTWRITEBYTECODE='1')

    def tearDown(self):
        self.temp.cleanup()

    def test_short_processes_keep_exact_fd_and_pid_without_polling(self):
        script = ('import json,os;print(json.dumps({"pid":os.getpid(),'
                  '"inode":os.stat("/proc/self/exe").st_ino,"argv":__import__("sys").argv}))')
        for _ in range(8):
            proc = subprocess.Popen([sys.executable, str(Path(runner.__file__)), str(self.image),
                                     '-c', script, '--exact', 'fixture::case', '--nocapture'],
                                    env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = proc.communicate(timeout=10)
            self.assertEqual(proc.returncode, 0, stderr)
            actual = json.loads(stdout)
            self.assertEqual(actual['pid'], proc.pid)
            records = [json.loads(path.read_text()) for path in self.directory.glob('*.json')]
            own = [record for record in records if record['pid'] == proc.pid]
            self.assertEqual(len(own), 1)
            self.assertEqual(own[0]['inode'], actual['inode'])
            self.assertEqual(own[0]['sha256'], hashlib.sha256(self.image.read_bytes()).hexdigest())
            self.assertEqual(own[0]['exact_test'], 'fixture::case')
        self.assertEqual(len(list(self.directory.glob('*.json'))), 8)
        self.assertEqual(len(list(self.directory.glob('*.elf'))), 1)

    def test_discovery_has_no_test_credit_and_unselected_run_refuses_exec(self):
        script = 'print("discovery output from exact image")'
        listed = subprocess.run([sys.executable, str(Path(runner.__file__)), str(self.image),
                                 '-c', script, '--list', '--format', 'terse'],
                                env=dict(self.env, NEXTEST_TEST_PHASE='list'), capture_output=True, text=True, timeout=10)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(listed.stdout, 'discovery output from exact image\n')
        self.assertEqual(list(self.directory.iterdir()), [])
        sentinel = self.root / 'must-not-execute'
        refused = subprocess.run([sys.executable, str(Path(runner.__file__)), str(self.image),
                                  '-c', 'from pathlib import Path;Path(__import__("sys").argv[1]).touch()',
                                  str(sentinel), '--exact', 'fixture::wrong'],
                                 env=self.env, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(refused.stdout, '')
        self.assertFalse(sentinel.exists())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_changed_fd_identity_and_failed_exec_are_rejected(self):
        fd = os.open(self.image, os.O_RDONLY)
        original = os.fstat(fd)
        changed = mock.Mock(st_dev=original.st_dev, st_ino=original.st_ino,
                            st_size=original.st_size, st_mtime_ns=original.st_mtime_ns,
                            st_ctime_ns=original.st_ctime_ns + 1)
        try:
            with mock.patch.object(runner.os, 'fstat', side_effect=[original, changed]):
                with self.assertRaisesRegex(ValueError, 'changed while retained'):
                    runner.retain(fd, self.directory, 'changed-fixture')
        finally:
            os.close(fd)
        # Remove the fixture's execute permission so fexecve itself, after the
        # opened-image record has been written, must fail and retain its error.
        self.image.chmod(0o600)
        failed = subprocess.run([sys.executable, str(Path(runner.__file__)), str(self.image),
                                 '-c', 'print("must not run")', '--exact', 'fixture::case'],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(failed.stdout, '')
        errors = list(self.directory.glob('*.exec-error.json'))
        self.assertEqual(len(errors), 1)
        self.assertEqual(json.loads(errors[0].read_text())['status'], 'exec_failed')


if __name__ == '__main__':
    unittest.main(verbosity=2)
