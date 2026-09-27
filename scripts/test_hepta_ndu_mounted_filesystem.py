#!/usr/bin/env python3
"""Orchestrator unit tests, not real mounted-filesystem qualification evidence."""
import copy
import errno
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load('hepta-ndu-mounted-filesystem')
qualification = load('hepta-ndu-qualification')


class MountedFilesystemOrchestratorTests(unittest.TestCase):
    def test_phase_handshake_is_bounded_and_checks_exact_observations(self):
        process = subprocess.Popen([sys.executable, '-c', "print('READY', flush=True)"], stdout=subprocess.PIPE)
        try:
            self.assertEqual(runner.expect_phase(process, 'READY'), 'READY')
            self.assertEqual(process.wait(timeout=5), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
        process = subprocess.Popen([sys.executable, '-c', "print('SKIPPED', flush=True)"], stdout=subprocess.PIPE)
        try:
            with self.assertRaises(RuntimeError):
                runner.expect_phase(process, 'READY')
        finally:
            process.wait(timeout=5)
            process.stdout.close()

    def test_read_only_probe_requires_actual_erofs_not_permission_denial(self):
        for observed, accepted in [(errno.EROFS, True), (errno.EACCES, False), (errno.ENOSPC, False)]:
            with self.subTest(observed=observed), patch.object(Path, 'open', side_effect=OSError(observed, 'test')):
                if accepted:
                    runner.probe_erofs(Path('/synthetic/probe'))
                else:
                    with self.assertRaises(OSError):
                        runner.probe_erofs(Path('/synthetic/probe'))

    def test_filler_cannot_fill_beyond_the_registered_bound(self):
        with patch.object(Path, 'open', return_value=io.BytesIO()):
            with self.assertRaises(RuntimeError):
                runner.fill_to_enospc(Path('/synthetic/filler'))

    def test_receipt_rejects_skips_wrong_identity_cleanup_and_missing_cuts(self):
        fixture = {
            'schema': 'hepta.ndu.mounted-filesystem-qualification.v1',
            'sourceSha': 'a' * 40, 'sourceTree': 'b' * 40, 'lane': 'source-head',
            'host': qualification.platform.node(), 'binaryUnchanged': True,
            'binarySha256': 'c' * 64, 'passed': True, 'productionActivation': False,
            'cases': [
                {'fault': fault, 'filesystem': 'tmpfs', 'observedErrno': code,
                 'passed': True, 'cleanupPassed': True, 'exitCode': 0, 'filledBytes': 4_000_000,
                 'phases': ['READY', 'FAULT_OBSERVED', 'RECOVERED']}
                for fault, code in [('enospc', 28), ('erofs', 30)]
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            def validate(receipt):
                path.write_text(json.dumps(receipt))
                return qualification.validate_mounted_receipt(path, 'a'*40, 'b'*40, 'source-head')
            self.assertTrue(validate(fixture)['identityValidated'])
            for field, value in [('sourceSha', 'd'*40), ('binaryUnchanged', False), ('passed', 1), ('productionActivation', True), ('cases', [])]:
                changed = copy.deepcopy(fixture)
                changed[field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    validate(changed)
            for field, value in [('cleanupPassed', False), ('phases', ['READY']), ('exitCode', 1), ('observedErrno', 13), ('filledBytes', 9_000_000)]:
                changed = copy.deepcopy(fixture)
                changed['cases'][0][field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    validate(changed)

    def test_host_suite_builds_and_executes_native_binary_not_a_skippable_test(self):
        commands = {name: command for name, _, command in qualification.commands('host', 'a'*40, 'b'*40)}
        self.assertIn('ndu-mounted-filesystem-qualification', commands['mounted-filesystem-binary'])
        self.assertEqual(commands['mounted-filesystem'][0], 'python3')
        self.assertIn('scripts/hepta-ndu-mounted-filesystem.py', commands['mounted-filesystem'])


if __name__ == '__main__':
    unittest.main()
